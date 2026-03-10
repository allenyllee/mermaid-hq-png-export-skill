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
  --scale 4
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
- Add `kroki-local`, a local CLI/backend that targets Kroki-like Mermaid output.
- Auto-install local `mmdc` when missing (`~/.local/mermaid-hq-png-export`).
- `auto` fallback order is `mmdc` -> `kroki-local` -> `kroki`.
- Do not inject `flowchart.htmlLabels=false` by default; it breaks HTML-styled labels in tested `block-beta` cases.

## Requirements

- Runtime:
  - For default `mmdc`: no preinstalled `mmdc` required (script auto-installs).
  - For `kroki-local`: local Chromium/Chrome is required.
  - For `kroki` fallback/path: `curl` and network access to `https://kroki.io`.
    - The current `kroki` path fetches PNG directly from remote Kroki.
    - If `--keep-svg` is requested, the renderer fetches remote SVG separately and saves it locally.
- Auto-install dependencies:
  - `curl` and `tar` are needed if Node.js must be downloaded automatically.
  - `kroki-local` packages are installed locally under `~/.local/mermaid-hq-png-export/kroki-mermaid-local-cli`.
  - `kroki-local` pins Mermaid `11.12.3`, and regression tests verify the installed version matches.

## Regression Tests

Run regression tests from the skill root:

```bash
python3 tests/run_regression_tests.py
```

Expected behavior:
- `mmdc_flowchart_text`: PASS
- `kroki_flowchart_text`: PASS
- `kroki_local_flowchart_text`: PASS
- `kroki_local_block_beta_geometry`: PASS

## Troubleshooting

- If local Chromium sandbox blocks `mmdc` in restricted environments, run outside sandbox or with compatible Chromium flags.
- If `backend=kroki-local` cannot start, set `MERMAID_SKILL_CHROME` to your Chromium/Chrome path.
- If `mmdc` install fails and Kroki is unavailable, install Node.js + `@mermaid-js/mermaid-cli` manually.
- If text still disappears, verify the SVG contains `<text>` nodes, not only `<foreignObject>`.
- If output is too large/small, change `--scale`.

## Implementation Notes

- `kroki-local` keeps a Kroki-style Mermaid SVG path, but PNG output uses browser screenshot instead of `ffmpeg`.
- This change was chosen after verifying that serializer-only normalization does not fix flowchart labels when SVG still contains `foreignObject`.
- HTML-styled label regressions are covered in tests for both `flowchart` and `block-beta`.
- `kroki-local` Mermaid is pinned to `11.12.3` because it stays closer to current Kroki layout than `11.13.0` in the tested `block-beta` case.
