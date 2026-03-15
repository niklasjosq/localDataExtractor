from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
import traceback

try:
    from PySide6.QtCore import QObject, Qt, QThread, Signal
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QPlainTextEdit,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for GUI. Install with `pip install PySide6`") from exc

from localdataextractor.config import load_config
from localdataextractor.pipeline import IngestionPipeline


class DropListWidget(QListWidget):
    paths_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        paths: list[str] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(local)
        if paths:
            self.paths_dropped.emit(paths)
        event.acceptProposedAction()


class PipelineWorker(QObject):
    progress = Signal(dict)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        mode: str,
        config_path: Path | None,
        input_paths: list[Path],
        output_dir: Path,
        resume_state: Path | None = None,
        explain_route: bool = True,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.config_path = config_path
        self.input_paths = input_paths
        self.output_dir = output_dir
        self.resume_state = resume_state
        self.explain_route = explain_route

    def run(self) -> None:
        try:
            config = load_config(self.config_path)
            pipeline = IngestionPipeline(config)

            def callback(progress):
                self.progress.emit(asdict(progress))

            if self.mode == "resume":
                if not self.resume_state:
                    raise ValueError("Resume state file is required")
                state_path = pipeline.resume(
                    state_path=self.resume_state,
                    explain_route=self.explain_route,
                    progress_callback=callback,
                )
                self.finished.emit(str(state_path))
                return

            last_state = ""
            for source in self.input_paths:
                state_file = pipeline.ingest(
                    input_path=source,
                    output_root=self.output_dir,
                    explain_route=self.explain_route,
                    progress_callback=callback,
                )
                last_state = str(state_file)
            self.finished.emit(last_state)
        except Exception as exc:
            tb = traceback.format_exc()
            self.failed.emit(f"{exc}\n{tb}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("localDataExtractor")
        self.resize(1120, 760)

        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._file_row_map: dict[str, int] = {}

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header = QLabel("Drag and drop files or folders")
        layout.addWidget(header)

        self.drop_list = DropListWidget()
        self.drop_list.paths_dropped.connect(self._on_paths_dropped)
        layout.addWidget(self.drop_list)

        io_row = QHBoxLayout()
        self.output_input = QLineEdit(str((Path.cwd() / "output").resolve()))
        pick_output_btn = QPushButton("Choose Output")
        pick_output_btn.clicked.connect(self._choose_output)
        io_row.addWidget(QLabel("Output:"))
        io_row.addWidget(self.output_input)
        io_row.addWidget(pick_output_btn)
        layout.addLayout(io_row)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start_ingest)
        self.resume_btn = QPushButton("Resume Interrupted Job")
        self.resume_btn.clicked.connect(self._resume_job)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear_inputs)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.resume_btn)
        controls.addWidget(self.clear_btn)
        layout.addLayout(controls)

        self.status_table = QTableWidget(0, 6)
        self.status_table.setHorizontalHeaderLabels(
            ["File", "Status", "Route", "Retries", "Confidence", "Outcome"]
        )
        self.status_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.status_table)

        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        layout.addWidget(QLabel("Logs / Errors"))
        layout.addWidget(self.log_panel)

    def _is_worker_running(self) -> bool:
        if self._thread is None:
            return False
        try:
            return self._thread.isRunning()
        except RuntimeError:
            # The underlying C++ QThread object may already be deleted.
            self._thread = None
            self._worker = None
            return False

    def _cleanup_worker_refs(self) -> None:
        self._thread = None
        self._worker = None

    def _on_paths_dropped(self, paths: list[str]) -> None:
        for path in paths:
            if path not in self._current_paths():
                self.drop_list.addItem(path)

    def _current_paths(self) -> list[str]:
        return [self.drop_list.item(i).text() for i in range(self.drop_list.count())]

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select output folder")
        if selected:
            self.output_input.setText(selected)

    def _clear_inputs(self) -> None:
        self.drop_list.clear()
        self.status_table.setRowCount(0)
        self._file_row_map.clear()

    def _start_ingest(self) -> None:
        paths = [Path(p) for p in self._current_paths()]
        if not paths:
            QMessageBox.warning(self, "No input", "Drop at least one file or folder.")
            return

        output_dir = Path(self.output_input.text()).expanduser().resolve()
        self._start_worker(
            PipelineWorker(
                mode="ingest",
                config_path=None,
                input_paths=paths,
                output_dir=output_dir,
                explain_route=True,
            )
        )

    def _resume_job(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select job_state.json",
            str(Path.cwd()),
            "JSON Files (*.json)",
        )
        if not file_path:
            return

        state_path = Path(file_path)
        output_dir = Path(self.output_input.text()).expanduser().resolve()
        self._start_worker(
            PipelineWorker(
                mode="resume",
                config_path=None,
                input_paths=[],
                output_dir=output_dir,
                resume_state=state_path,
                explain_route=True,
            )
        )

    def _start_worker(self, worker: PipelineWorker) -> None:
        if self._is_worker_running():
            QMessageBox.information(self, "Running", "A job is already running.")
            return

        self._worker = worker
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._cleanup_worker_refs)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        self.log_panel.appendPlainText("Job started")

    def _on_progress(self, payload: dict) -> None:
        source_path = payload.get("source_path", "")
        status = payload.get("status", "")
        route = payload.get("route", "")
        retries = payload.get("retries", 0)
        confidence = payload.get("confidence", 0.0)
        outcome = payload.get("message", "")

        row = self._file_row_map.get(source_path)
        if row is None:
            row = self.status_table.rowCount()
            self.status_table.insertRow(row)
            self._file_row_map[source_path] = row

        values = [
            source_path,
            str(status),
            str(route),
            str(retries),
            f"{float(confidence):.2f}",
            str(outcome),
        ]
        for col, value in enumerate(values):
            self.status_table.setItem(row, col, QTableWidgetItem(value))

        self.log_panel.appendPlainText(
            f"{source_path} | status={status} route={route} retries={retries} confidence={confidence}"
        )

    def _on_finished(self, state_file: str) -> None:
        self.log_panel.appendPlainText(f"Job finished. state={state_file}")
        QMessageBox.information(self, "Finished", f"Job completed.\nState file: {state_file}")

    def _on_failed(self, error: str) -> None:
        self.log_panel.appendPlainText(error)
        QMessageBox.critical(self, "Failed", error)


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
