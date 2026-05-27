from __future__ import annotations

from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
import sys
import traceback

try:
    from PySide6.QtCore import QObject, Qt, QThread, QSize, Signal
    from PySide6.QtGui import (
        QFont, QGuiApplication, QIcon, QPalette, QPixmap,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QPlainTextEdit,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QStatusBar,
        QStyle,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "PySide6 is required for GUI. "
        "Install with `uv pip install PySide6` or "
        "`uv pip install -e .[full]`"
    ) from exc

from localdataextractor.config import load_config
from localdataextractor.pipeline import IngestionPipeline


STYLE_SHEET = """
QMainWindow {
    background-color: palette(window);
}
QGroupBox {
    font-weight: 600;
    border: 1px solid palette(mid);
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: palette(window-text);
}
QPushButton {
    padding: 6px 14px;
    border-radius: 6px;
    min-height: 24px;
}
QPushButton#primary {
    background-color: #1f6feb;
    color: white;
    font-weight: 600;
    border: 1px solid #1858b8;
}
QPushButton#primary:hover {
    background-color: #2178f4;
}
QPushButton#primary:disabled {
    background-color: #9ab5d9;
    border-color: #8aa6cc;
}
QLineEdit, QPlainTextEdit, QComboBox {
    border: 1px solid palette(mid);
    border-radius: 5px;
    padding: 4px 6px;
    selection-background-color: #1f6feb;
}
QTableWidget {
    alternate-background-color: palette(alternate-base);
    gridline-color: palette(mid);
    border: 1px solid palette(mid);
    border-radius: 6px;
}
QHeaderView::section {
    padding: 6px;
    border: none;
    border-bottom: 1px solid palette(mid);
    background-color: palette(window);
    font-weight: 600;
}
QProgressBar {
    border: 1px solid palette(mid);
    border-radius: 5px;
    text-align: center;
    height: 16px;
}
QProgressBar::chunk {
    background-color: #1f6feb;
    border-radius: 4px;
}
QLabel#title {
    font-size: 18pt;
    font-weight: 700;
}
QLabel#subtitle {
    color: palette(placeholder-text);
}
QLabel#statusDot {
    border-radius: 7px;
    min-width: 14px;
    max-width: 14px;
    min-height: 14px;
    max-height: 14px;
}
"""


def _hwrap(*widgets) -> QWidget:
    """Pack widgets into a horizontal layout inside a container widget,
    so QFormLayout can treat them as a single field cell."""
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    for widget in widgets:
        if isinstance(widget, QLineEdit):
            row.addWidget(widget, stretch=1)
        else:
            row.addWidget(widget)
    return container


def _is_dark_palette() -> bool:
    """True if the active Qt palette has a dark window background."""
    app = QGuiApplication.instance()
    if app is None:
        return False
    color = app.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128


def _resolve_asset(name: str) -> Path | None:
    try:
        ref = files("localdataextractor.assets").joinpath(name)
        as_path = Path(str(ref))
        if as_path.is_file():
            return as_path
    except Exception:
        pass
    fallback = (
        Path(__file__).resolve().parent.parent / "assets" / name
    )
    return fallback if fallback.is_file() else None


def _logo_path(is_dark: bool | None = None) -> Path | None:
    """Pick the light or dark logo variant based on the current
    palette (or the explicit override)."""
    if is_dark is None:
        is_dark = _is_dark_palette()
    preferred = (
        ("logo_dark.png", "logo_light.png")
        if is_dark
        else ("logo_light.png", "logo_dark.png")
    )
    for name in preferred + ("logo.png", "logo.svg"):
        resolved = _resolve_asset(name)
        if resolved is not None:
            return resolved
    return None


def _discover_config_path() -> Path | None:
    candidates = [
        Path.cwd() / "config.toml",
        Path.home() / ".config" / "localdataextractor" / "config.toml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class DropListWidget(QListWidget):
    paths_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setMinimumHeight(80)

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
        extraction_mode: str = "standard",
        api_token_override: str = "",
    ) -> None:
        super().__init__()
        self.mode = mode
        self.config_path = config_path
        self.input_paths = input_paths
        self.output_dir = output_dir
        self.resume_state = resume_state
        self.explain_route = explain_route
        self.extraction_mode = extraction_mode
        self.api_token_override = api_token_override

    def run(self) -> None:
        try:
            config = load_config(self.config_path)
            if self.api_token_override:
                config.llm.api_token = self.api_token_override
            if self.extraction_mode != "standard":
                config.routing.extraction_mode = self.extraction_mode
            if self.extraction_mode in ("glm_ocr", "highest_accuracy"):
                config.glm_ocr.enabled = True
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
        # Keep a small floor so the window stays grabbable but never
        # forces itself larger than the screen.
        self.setMinimumSize(820, 520)
        self._apply_initial_geometry(preferred=QSize(1200, 780))

        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._file_row_map: dict[str, int] = {}
        self._config_path: Path | None = _discover_config_path()
        self._files_total: int = 0
        self._files_done: int = 0

        logo = _logo_path()
        if logo is not None:
            self.setWindowIcon(QIcon(str(logo)))

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(10)

        outer.addLayout(self._build_header(logo))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        splitter.addWidget(self._build_left_pane())
        splitter.addWidget(self._build_right_pane())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 720])
        outer.addWidget(splitter, stretch=1)

        self.setStatusBar(self._build_status_bar())
        self.setStyleSheet(STYLE_SHEET)

    def _build_left_pane(self) -> QWidget:
        inner = QWidget()
        inner.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        col.addWidget(self._build_input_group())
        col.addWidget(self._build_config_group())
        col.addWidget(self._build_run_group())
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        scroll.setWidget(inner)
        scroll.setMinimumWidth(360)
        return scroll

    def _build_right_pane(self) -> QWidget:
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        split.addWidget(self._build_status_table())
        split.addWidget(self._build_log_panel())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        split.setSizes([400, 200])
        split.setMinimumWidth(360)
        return split

    def _build_header(self, logo: Path | None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        if logo is not None:
            label = QLabel()
            pix = QPixmap(str(logo))
            if not pix.isNull():
                # Use device pixel ratio so the logo stays crisp on
                # Retina displays. The dark variant includes a wordmark
                # so it benefits from a slightly larger header size.
                target_px = 72
                ratio = self.devicePixelRatioF() or 1.0
                pix.setDevicePixelRatio(ratio)
                scaled = pix.scaled(
                    QSize(
                        int(target_px * ratio),
                        int(target_px * ratio),
                    ),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                scaled.setDevicePixelRatio(ratio)
                label.setPixmap(scaled)
                label.setFixedSize(QSize(target_px, target_px))
            row.addWidget(label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel("localDataExtractor")
        title.setObjectName("title")
        subtitle = QLabel(
            "Privacy-first document → Markdown, local-only"
        )
        subtitle.setObjectName("subtitle")
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        row.addLayout(text_col)
        row.addStretch(1)
        return row

    def _build_input_group(self) -> QGroupBox:
        group = QGroupBox("Input")
        layout = QVBoxLayout(group)
        hint = QLabel(
            "Drag and drop files or folders below, or use the "
            "buttons to pick."
        )
        hint.setObjectName("subtitle")
        layout.addWidget(hint)
        self.drop_list = DropListWidget()
        self.drop_list.paths_dropped.connect(self._on_paths_dropped)
        layout.addWidget(self.drop_list)

        button_row = QHBoxLayout()
        add_files_btn = QPushButton("Add Files…")
        add_files_btn.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_FileIcon,
            )
        )
        add_files_btn.clicked.connect(self._pick_files)
        add_folder_btn = QPushButton("Add Folder…")
        add_folder_btn.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_DirIcon,
            )
        )
        add_folder_btn.clicked.connect(self._pick_folder)
        clear_btn = QPushButton("Clear")
        clear_btn.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_DialogResetButton,
            )
        )
        clear_btn.clicked.connect(self._clear_inputs)
        button_row.addWidget(add_files_btn)
        button_row.addWidget(add_folder_btn)
        button_row.addStretch(1)
        button_row.addWidget(clear_btn)
        layout.addLayout(button_row)
        return group

    def _build_config_group(self) -> QGroupBox:
        group = QGroupBox("Output & configuration")
        form = QFormLayout(group)
        form.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapLongRows,
        )
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow,
        )
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)

        self.output_input = QLineEdit(
            str((Path.cwd() / "output").resolve())
        )
        pick_output_btn = QPushButton("Browse…")
        pick_output_btn.clicked.connect(self._choose_output)
        form.addRow(
            "Output folder:",
            _hwrap(self.output_input, pick_output_btn),
        )

        self.config_input = QLineEdit(
            str(self._config_path) if self._config_path else ""
        )
        self.config_input.setPlaceholderText(
            "Optional path to config.toml (defaults used if blank)"
        )
        self.config_input.editingFinished.connect(
            self._on_config_changed
        )
        pick_config_btn = QPushButton("Browse…")
        pick_config_btn.clicked.connect(self._choose_config)
        form.addRow(
            "Config file:",
            _hwrap(self.config_input, pick_config_btn),
        )

        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText(
            "Paste here if your local server requires auth"
        )
        self.token_input.editingFinished.connect(
            lambda: self._refresh_lm_status(force=True),
        )
        test_btn = QPushButton("Test")
        test_btn.clicked.connect(
            lambda: self._refresh_lm_status(force=True),
        )
        form.addRow(
            "LM Studio token:",
            _hwrap(self.token_input, test_btn),
        )

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Standard (parser-first routing)",
            "GLM-OCR / VLM (vision model primary)",
            "Highest Accuracy (try every method)",
        ])
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(
            self._on_mode_changed,
        )
        form.addRow("Extraction mode:", self.mode_combo)
        return group

    def _build_run_group(self) -> QGroupBox:
        group = QGroupBox("Run")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        button_row = QHBoxLayout()
        self.start_btn = QPushButton("Start extraction")
        self.start_btn.setObjectName("primary")
        self.start_btn.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaPlay,
            )
        )
        self.start_btn.clicked.connect(self._start_ingest)
        button_row.addWidget(self.start_btn)

        self.resume_btn = QPushButton("Resume job…")
        self.resume_btn.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_BrowserReload,
            )
        )
        self.resume_btn.clicked.connect(self._resume_job)
        button_row.addWidget(self.resume_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("idle")
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        return group

    def _build_status_table(self) -> QGroupBox:
        group = QGroupBox("Files")
        layout = QVBoxLayout(group)
        self.status_table = QTableWidget(0, 6)
        self.status_table.setHorizontalHeaderLabels([
            "File", "Status", "Route", "Retries",
            "Confidence", "Outcome",
        ])
        header = self.status_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents,
            )
        self.status_table.setAlternatingRowColors(True)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setMinimumHeight(80)
        layout.addWidget(self.status_table)
        return group

    def _build_log_panel(self) -> QGroupBox:
        group = QGroupBox("Logs / Errors")
        layout = QVBoxLayout(group)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.log_panel.setFont(mono)
        self.log_panel.setMinimumHeight(60)
        layout.addWidget(self.log_panel)
        return group

    def _build_status_bar(self) -> QStatusBar:
        bar = QStatusBar()
        self.lm_dot = QLabel()
        self.lm_dot.setObjectName("statusDot")
        self.lm_dot.setStyleSheet(
            "background-color: #9ca3af;"
        )
        self.lm_status_label = QLabel("LM Studio: idle")
        bar.addPermanentWidget(self.lm_dot)
        bar.addPermanentWidget(self.lm_status_label)
        return bar

    def _apply_initial_geometry(self, preferred: QSize) -> None:
        """Size the window to fit the available screen, then center."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(preferred)
            return
        avail = screen.availableGeometry()
        target_w = min(preferred.width(), int(avail.width() * 0.92))
        target_h = min(preferred.height(), int(avail.height() * 0.92))
        self.resize(target_w, target_h)
        x = avail.x() + (avail.width() - target_w) // 2
        y = avail.y() + (avail.height() - target_h) // 2
        self.move(x, y)

    def _set_lm_status(self, color: str, text: str) -> None:
        self.lm_dot.setStyleSheet(f"background-color: {color};")
        self.lm_status_label.setText(text)

    def _is_worker_running(self) -> bool:
        if self._thread is None:
            return False
        try:
            return self._thread.isRunning()
        except RuntimeError:
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
        return [
            self.drop_list.item(i).text()
            for i in range(self.drop_list.count())
        ]

    def _pick_files(self) -> None:
        files_chosen, _ = QFileDialog.getOpenFileNames(
            self, "Choose files to extract", str(Path.cwd()),
        )
        for f in files_chosen:
            if f not in self._current_paths():
                self.drop_list.addItem(f)

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose folder to extract", str(Path.cwd()),
        )
        if folder and folder not in self._current_paths():
            self.drop_list.addItem(folder)

    def _on_mode_changed(self, index: int) -> None:
        if index == 0:
            self._set_lm_status("#9ca3af", "LM Studio: idle (standard mode)")
            return
        self._refresh_lm_status(force=False)

    def _on_config_changed(self) -> None:
        text = self.config_input.text().strip()
        self._config_path = Path(text) if text else None
        if self.mode_combo.currentIndex() != 0:
            self._refresh_lm_status(force=True)

    def _choose_config(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select config.toml",
            str(Path.cwd()),
            "TOML Files (*.toml)",
        )
        if file_path:
            self.config_input.setText(file_path)
            self._config_path = Path(file_path)
            if self.mode_combo.currentIndex() != 0:
                self._refresh_lm_status(force=True)

    def _resolve_llm_config(self):
        from localdataextractor.config import (
            ConfigError,
            LLMConfig,
            last_dotenv_loaded,
            load_config,
        )
        cfg_err: str | None = None
        toml_path = (
            self._config_path
            if self._config_path and self._config_path.is_file()
            else None
        )
        try:
            cfg = load_config(toml_path)
            llm_cfg = cfg.llm
            source = "config.toml" if toml_path else "defaults"
        except ConfigError as exc:
            return LLMConfig(), f"config error: {exc}"
        except Exception as exc:
            return LLMConfig(), f"config load failed: {exc}"

        dotenv = last_dotenv_loaded()
        if dotenv is not None and llm_cfg.api_token:
            source = f".env ({dotenv})"

        gui_token = self.token_input.text().strip()
        if gui_token:
            llm_cfg.api_token = gui_token
            source = "GUI field"
        token_origin = "(no token)" if not llm_cfg.api_token else source
        self.log_panel.appendPlainText(
            f"LM Studio token source: {token_origin}"
        )
        if dotenv is None:
            self.log_panel.appendPlainText(
                f"(no .env file found in CWD={Path.cwd()})"
            )
        return llm_cfg, cfg_err

    def _refresh_lm_status(self, force: bool) -> None:
        from localdataextractor.llm.client import LMStudioClient

        if not force and self.mode_combo.currentIndex() == 0:
            self._set_lm_status(
                "#9ca3af", "LM Studio: idle (standard mode)",
            )
            return

        self._set_lm_status("#eab308", "LM Studio: checking…")
        llm_cfg, cfg_err = self._resolve_llm_config()
        if cfg_err:
            self._set_lm_status("#dc2626", cfg_err)
            self.log_panel.appendPlainText(
                f"LM Studio check: {cfg_err}"
            )
            return

        try:
            client = LMStudioClient(llm_cfg)
        except ValueError as exc:
            self._set_lm_status("#dc2626", f"LM Studio: {exc}")
            self.log_panel.appendPlainText(
                f"LM Studio check: {exc} (url={llm_cfg.base_url})"
            )
            return

        ok, detail = client.check_server()
        if ok:
            models = client.list_models()
            wanted = llm_cfg.primary_model or "glm-ocr"
            if wanted in models:
                self._set_lm_status(
                    "#16a34a",
                    f"LM Studio: '{wanted}' available",
                )
            else:
                listed = ", ".join(models[:3]) or "no models listed"
                self._set_lm_status(
                    "#eab308",
                    f"LM Studio: '{wanted}' not loaded ({listed})",
                )
            self.log_panel.appendPlainText(
                f"LM Studio check OK @ {llm_cfg.base_url} -> {detail}"
            )
        else:
            self._set_lm_status(
                "#dc2626",
                f"LM Studio not reachable: {detail[:60]}",
            )
            self.log_panel.appendPlainText(
                f"LM Studio check FAILED @ {llm_cfg.base_url}: {detail}"
            )

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select output folder",
        )
        if selected:
            self.output_input.setText(selected)

    def _clear_inputs(self) -> None:
        self.drop_list.clear()
        self.status_table.setRowCount(0)
        self._file_row_map.clear()
        self._files_total = 0
        self._files_done = 0
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("idle")

    def _start_ingest(self) -> None:
        paths = [Path(p) for p in self._current_paths()]
        if not paths:
            QMessageBox.warning(
                self,
                "No input",
                "Drop at least one file or folder, "
                "or use Add Files / Add Folder.",
            )
            return

        mode_map = {
            0: "standard",
            1: "glm_ocr",
            2: "highest_accuracy",
        }
        extraction_mode = mode_map.get(
            self.mode_combo.currentIndex(), "standard",
        )

        output_dir = Path(
            self.output_input.text()
        ).expanduser().resolve()
        self._begin_progress()
        self._start_worker(
            PipelineWorker(
                mode="ingest",
                config_path=self._config_path,
                input_paths=paths,
                output_dir=output_dir,
                explain_route=True,
                extraction_mode=extraction_mode,
                api_token_override=self.token_input.text().strip(),
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
        output_dir = Path(
            self.output_input.text()
        ).expanduser().resolve()
        self._begin_progress()
        self._start_worker(
            PipelineWorker(
                mode="resume",
                config_path=self._config_path,
                input_paths=[],
                output_dir=output_dir,
                resume_state=state_path,
                explain_route=True,
                api_token_override=self.token_input.text().strip(),
            )
        )

    def _begin_progress(self) -> None:
        self._files_total = 0
        self._files_done = 0
        self.progress_bar.setMaximum(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("starting…")
        self.start_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)

    def _end_progress(self) -> None:
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(1)
        self.progress_bar.setFormat("done")
        self.start_btn.setEnabled(True)
        self.resume_btn.setEnabled(True)

    def _start_worker(self, worker: PipelineWorker) -> None:
        if self._is_worker_running():
            QMessageBox.information(
                self, "Running", "A job is already running.",
            )
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
        is_new = row is None
        if is_new:
            row = self.status_table.rowCount()
            self.status_table.insertRow(row)
            self._file_row_map[source_path] = row
            self._files_total += 1
            self.progress_bar.setMaximum(self._files_total)

        values = [
            Path(source_path).name if source_path else "",
            str(status),
            str(route),
            str(retries),
            f"{float(confidence):.2f}",
            str(outcome),
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 0 and source_path:
                item.setToolTip(source_path)
            self.status_table.setItem(row, col, item)

        if status in {"completed", "completed_below_threshold", "failed"}:
            self._files_done += 1
            self.progress_bar.setValue(self._files_done)
            self.progress_bar.setFormat(
                f"{self._files_done} / {self._files_total} files"
            )

        self.log_panel.appendPlainText(
            f"{source_path} | status={status} route={route} "
            f"retries={retries} confidence={confidence}"
        )

    def _on_finished(self, state_file: str) -> None:
        self._end_progress()
        self.log_panel.appendPlainText(
            f"Job finished. state={state_file}"
        )
        QMessageBox.information(
            self,
            "Finished",
            f"Job completed.\nState file: {state_file}",
        )

    def _on_failed(self, error: str) -> None:
        self._end_progress()
        self.progress_bar.setFormat("failed")
        self.log_panel.appendPlainText(error)
        QMessageBox.critical(self, "Failed", error)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("localDataExtractor")
    app.setOrganizationName("localDataExtractor")
    logo = _logo_path()
    if logo is not None:
        app.setWindowIcon(QIcon(str(logo)))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
