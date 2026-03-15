# localDataExtractor

Privacy-first, fully local document-to-Markdown extraction pipeline for macOS Apple Silicon.

## Features

- Local-only processing (no cloud APIs)
- Parser-first routing with explainable route decisions
- LM Studio localhost integration for selective repair/normalization
- Outputs per file:
  - Markdown (`.md`)
  - structured audit JSON (`.json`)
  - extraction log (`.log`)
- Resumable state (`job_state.json`)
- Confidence scoring (0-100) with automatic retries below threshold (`95` by default)
- Table-first validation and recovery logic
- CLI and local drag-and-drop GUI

## Supported input formats

- `pdf`
- `doc`
- `docx`
- `css`
- `xls`
- `xlsx`
- `txt`
- `ppt`
- `pptx`

## Recommended setup (macOS)

```bash
./scripts/setup_macos.sh
```

This installs local dependencies (`tesseract`, `ocrmypdf`, `LibreOffice`, `Java`) and Python packages.

## Manual setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e .[full,dev]
cp config.sample.toml config.toml
```

Install native dependencies with Homebrew:

```bash
brew install tesseract ocrmypdf poppler openjdk
brew install --cask libreoffice
```

## Public repo hygiene

- `config.toml` is local-only and gitignored; commit `config.sample.toml` instead.
- Generated runtime folders (`output/`, `_out_smoke/`) are gitignored.
- If this directory is nested in another git repo, initialize and push from this folder:

```bash
cd /path/to/localDataExtractor
git init
git add .
git commit -m "Initial public release"
```

## LM Studio setup

1. Start LM Studio local server on `http://localhost:1234/v1`.
2. Load primary model: `qwen3-vl-8b` (or closest local name).
3. Load fallback model: `qwen2.5-vl-7b`.
4. Run:

```bash
localdataextractor --config config.toml check-llm
```

## CLI usage

### Ingest

```bash
localdataextractor --config config.toml ingest ./input_docs ./output --explain-route --max-workers 2
```

Options:

- `--include "**/*.pdf"` (repeatable)
- `--exclude "**/~$*"` (repeatable)
- `--dry-run`
- `--verbose`
- `--max-workers <int>`
- `--explain-route`

### Resume

```bash
localdataextractor --config config.toml resume ./output/job_state.json --explain-route
```

### Verify

```bash
localdataextractor verify ./output
```

### Create sample config

```bash
localdataextractor init-config ./config.toml
```

## GUI usage

```bash
localdataextractor-gui
# or
python gui.py
```

GUI supports:

- drag-and-drop files/folders
- output folder picker
- start processing
- resume interrupted jobs
- per-file status panel with route, retries, confidence, outcome
- live log/error panel

## Output layout

For each source file:

- `output/<relative_path>/<basename>.md`
- `output/<relative_path>/<basename>.json`
- `output/<relative_path>/<basename>.log`
- optional debug files under `output/<relative_path>/_debug/`

Job-level resumable state:

- `output/job_state.json`

## Routing behavior

- `txt`, `css`:
  - deterministic direct read
  - no LLM usage
  - CSS wrapped in fenced `css` code block
- `pdf`:
  - Docling first
  - OCR-assisted Docling retry via OCRmyPDF
  - Tika fallback when enabled
- `docx`, `pptx`, `xlsx`, `xls`:
  - MarkItDown first
  - Docling fallback
  - Tika fallback when enabled
- `doc`, `ppt`:
  - LibreOffice headless conversion to modern format
  - then MarkItDown/Docling path
  - Tika fallback when enabled

Every decision is logged in route history and can be printed with `--explain-route`.

## Confidence and retries

- Confidence range: `0-100`
- Default threshold: `95`
- Retries trigger when:
  - overall confidence `< 95`, or
  - any important table confidence `< 95`
- Each attempt stores:
  - timestamp
  - route and parser used
  - model used (if any)
  - confidence details
  - retry reasons
  - warnings and artifacts
- If all strategies fail to reach threshold, best result is emitted and marked `below_threshold=true`.

## Table handling

Tables are first-class and include:

- table id
- source location metadata
- header/body rows
- row/column counts
- merged-cell metadata (when recoverable)
- confidence score
- validation warnings

Validation heuristics include:

- column consistency
- weak header detection
- duplicate-row ratio
- empty-cell anomaly ratio
- collapse risk

If table confidence is low, optional LM Studio repair is attempted locally.

## Verification

`localdataextractor verify <output>` checks:

- required output files exist (`.md`, `.json`, `.log`)
- JSON validity and schema keys
- confidence fields and below-threshold flag
- route history presence
- table presence in JSON and Markdown approximation when tables were detected

## Tradeoffs and known limitations

- Docling/MarkItDown APIs may vary across versions; fallbacks are included.
- Legacy `doc/ppt` fidelity depends on local LibreOffice conversion quality.
- `xls` support depends on local `xlrd` availability.
- Tika fallback requires Java runtime and local `tika-app.jar` path in config.
- Markdown tables may lose some advanced layout semantics; JSON table representation is authoritative.

## Privacy notes

- No cloud APIs are used by default.
- LM Studio is enforced as localhost-only.
- Document processing remains on-device.
