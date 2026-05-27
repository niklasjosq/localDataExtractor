# localDataExtractor

Privacy-first, fully local document-to-Markdown extraction pipeline for macOS Apple Silicon.

## Features

- Local-only processing (no cloud APIs)
- Parser-first routing with explainable route decisions
- LM Studio localhost integration via `glm-ocr` for vision OCR and table repair
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
- `png`, `jpg`, `jpeg`, `tiff`, `tif`, `bmp` (via GLM-OCR mode)

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

1. Start LM Studio local server on `http://127.0.0.1:1234/v1`.
2. Load the `glm-ocr` model (used for both vision OCR and table repair).
3. Run:

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
- `--mode standard|glm_ocr|highest_accuracy`

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
- extraction mode selector (Standard, GLM-OCR, Highest Accuracy)
- GLM-OCR model availability indicator
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

## Extraction modes

Three extraction modes are available via `--mode` (CLI) or the GUI dropdown:

| Mode | Behavior |
|------|----------|
| `standard` (default) | Parser-first routing per file type; stops at first result meeting the confidence threshold |
| `glm_ocr` | GLM-OCR vision model as primary extractor (PDFs and images), with standard routes as fallback |
| `highest_accuracy` | Tries all available parsers including GLM-OCR and selects the highest confidence result |

GLM-OCR mode requires the `glm-ocr` model loaded in LM Studio. It renders each PDF page to an image and sends it to the vision model for high-accuracy OCR of text, tables, and graphics.

## Routing behavior

### Standard mode

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

### GLM-OCR mode

- `pdf`, `png`, `jpg`, `jpeg`, `tiff`, `tif`, `bmp`:
  - GLM-OCR vision model first
  - standard routes as fallback
- all other formats: standard routing

### Highest Accuracy mode

- all standard routes tried first
- GLM-OCR appended for PDFs and images
- no early stopping: every parser runs, best confidence wins

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

If table confidence is low, LM Studio repair via `glm-ocr` is attempted locally.

## Verification

`localdataextractor verify <output>` checks:

- required output files exist (`.md`, `.json`, `.log`)
- JSON validity and schema keys
- confidence fields and below-threshold flag
- route history presence
- table presence in JSON and Markdown approximation when tables were detected

## GLM-OCR configuration

The `[glm_ocr]` section in `config.toml` controls vision-based OCR:

```toml
[llm]
base_url = "http://127.0.0.1:1234/v1"
primary_model = "glm-ocr"
fallback_model = "glm-ocr"

[glm_ocr]
enabled = true           # enabled by default; glm-ocr serves as the single model
model_name = "glm-ocr"   # model ID as loaded in LM Studio
page_dpi = 300            # DPI for rendering PDF pages to images
max_pages = 50            # safety cap on pages sent to vision API
timeout_seconds = 180     # per-request timeout (vision is slower)
```

The extraction mode can also be set in config:

```toml
[routing]
extraction_mode = "standard"  # standard | glm_ocr | highest_accuracy
```

## Tradeoffs and known limitations

- Docling/MarkItDown APIs may vary across versions; fallbacks are included.
- Legacy `doc/ppt` fidelity depends on local LibreOffice conversion quality.
- `xls` support depends on local `xlrd` availability.
- Tika fallback requires Java runtime and local `tika-app.jar` path in config.
- Markdown tables may lose some advanced layout semantics; JSON table representation is authoritative.
- GLM-OCR mode processes pages one at a time; large PDFs will be slow. Use `max_pages` to cap.
- Highest Accuracy mode runs all parsers and does not stop early, so it is slower than other modes.

## Privacy notes

- No cloud APIs are used by default.
- LM Studio is enforced as localhost-only.
- Document processing remains on-device.
