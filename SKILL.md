---
name: mermaid-hq-png-export
description: Render Mermaid diagrams into high-resolution PNG with sharp text (non-upscaled). Use when users ask to convert Mermaid code to PNG, request higher resolution, complain about blurry output, report missing text after SVG/PNG conversion, or need batch export for many Mermaid files.
---

# Mermaid HQ PNG Export

## Workflow

1. Save Mermaid text to a `.mmd` file.
2. Run `scripts/render_mermaid_png.py` to render PNG natively from SVG.
3. Return the output path and rendered pixel size.

Use this command:

```bash
python3 scripts/render_mermaid_png.py \
  --input /abs/path/diagram.mmd \
  --output /abs/path/diagram-4x.png \
  --scale 4 \
  --target-width 2000
```

Batch mode:

```bash
python3 scripts/render_mermaid_png.py \
  --batch-dir /abs/path/mermaid-files \
  --output-dir /abs/path/png-output \
  --pattern '*.mmd' \
  --recursive \
  --scale 4
```

## Why This Works

- Default to `mmdc` for PNG output so flowchart labels are preserved.
- Auto-install local `mmdc` when missing (`~/.local/mermaid-hq-png-export`).
- Fall back to `kroki` only when `mmdc` install is unavailable.
- Keep Mermaid init config `flowchart.htmlLabels=false` to reduce label loss risk.
- Support `--target-width` for stable final width across backends.

## Requirements

- Runtime:
  - For default `mmdc`: no preinstalled `mmdc` required (script auto-installs).
  - For `kroki` fallback/path: `curl`, `ffmpeg`, and network access to `https://kroki.io`.
- Auto-install dependencies:
  - `curl` and `tar` are needed if Node.js must be downloaded automatically.

## Regression Tests

Run regression tests from the skill root:

```bash
python3 tests/run_regression_tests.py
```

Expected behavior:
- `mmdc_flowchart_text`: PASS
- `mmdc_target_width`: PASS
- `kroki_flowchart_text`: XFAIL (known limitation: some flowcharts lose text in PNG)
- `kroki_target_width`: PASS (when Kroki is reachable)

## Troubleshooting

- If local Chromium sandbox blocks `mmdc` in restricted environments, run outside sandbox or with compatible Chromium flags.
- If `mmdc` install fails and Kroki is unavailable, install Node.js + `@mermaid-js/mermaid-cli` manually.
- If text still disappears, verify the SVG contains `<text>` nodes, not only `<foreignObject>`.
- If output is too large/small, change `--scale` or set `--target-width`.
