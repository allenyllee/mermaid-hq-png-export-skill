# mermaid-hq-png-export

Render Mermaid diagrams to high-resolution PNG with sharp text (not upscaled from an old PNG).

## What this skill does

- Defaults to local `mmdc` for PNG rendering (`.mmd -> .png`)
- Auto-installs `mmdc` locally when missing
- Adds a second local backend, `mermaid-js`, built from Mermaid JS library + Puppeteer Core + local Chromium
- Falls back in this order: `mmdc` -> `mermaid-js` -> Kroki
- Ensures labels stay visible by using Mermaid init config with `flowchart.htmlLabels=false`
- Supports batch export for multiple `.mmd` files in one command

## Repository structure

- `SKILL.md`: Skill instructions and workflow
- `agents/openai.yaml`: Codex skill metadata
- `scripts/render_mermaid_png.py`: CLI renderer script

## Requirements

- Python 3
- Runtime:
  - Default path (`mmdc`) auto-installs local dependencies under `~/.local/mermaid-hq-png-export`
  - `mermaid-js` needs a local Chromium/Chrome executable
  - Kroki path needs `curl` + `ffmpeg` + network access to `https://kroki.io`
- For automatic Node.js bootstrap (when system Node is absent): `curl` and `tar`

## Usage

```bash
python3 scripts/render_mermaid_png.py \
  --input /abs/path/diagram.mmd \
  --output /abs/path/diagram-4x.png \
  --scale 4
```

## Batch usage

```bash
python3 scripts/render_mermaid_png.py \
  --batch-dir /abs/path/mermaid-files \
  --output-dir /abs/path/png-output \
  --pattern '*.mmd' \
  --recursive \
  --scale 4
```

## Chat usage (direct prompt)

In Codex chat, you can directly send Mermaid content and ask for high-resolution PNG output, for example:

````text
```mermaid
block-beta
  columns 4
  gpio["GPIO"]:2 hwm["HWM"]:2
  backend["Backend Adapter Layer"]:4
  driver_up["Driver"]:1 cli["CLI"]:1 space:2
  driver["Driver"]:2 space:2
  os["OS"]:4
```

Export to high-resolution PNG.
````

The agent should render and output a high-resolution PNG directly from this prompt.

### Options

- `--backend`: `mmdc` (default), `mermaid-js`, `kroki`, or `auto`
- `--input`: Mermaid source file (`.mmd`, single mode)
- `--output`: Output PNG path (single mode)
- `--scale`: Scale factor from SVG `viewBox` (default: `4.0`)
- `--keep-svg`: Optional path to save the intermediate SVG (single mode)
- `--batch-dir`: Input directory for batch mode
- `--output-dir`: Output directory for batch mode
- `--pattern`: Batch file pattern (default: `*.mmd`)
- `--recursive`: Recursively search `--batch-dir`
- `--name-suffix`: Output filename suffix in batch mode (default: `-hq`)
- `--keep-svg-dir`: Optional directory to save batch SVG files

## Example

```bash
python3 scripts/render_mermaid_png.py \
  --input ./examples/arch.mmd \
  --output ./out/arch-8x.png \
  --scale 8 \
  --keep-svg ./out/arch-8x.svg
```

## Regression tests

```bash
python3 tests/run_regression_tests.py
```

Expected:
- `mmdc_flowchart_text`: PASS
- `mermaid_js_flowchart_text`: PASS
- `kroki_flowchart_text`: XFAIL (known limitation for this flowchart case)

## Notes

- This workflow produces native high-resolution output from source, not interpolation from an existing PNG.
- In this skill, `flowchart` diagrams are safest with `mmdc` because Kroki+ffmpeg can lose text on some cases.
- `mermaid-js` is a separate local render path. It does not shell out to `mmdc`, but output can still differ because the pipeline is different.
