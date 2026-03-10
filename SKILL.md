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
  --backend auto
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

- Render from Mermaid source again instead of scaling an old PNG.
- Add Mermaid init config `flowchart.htmlLabels=false` (if not present) so text is emitted as SVG `<text>`, avoiding dropped labels during rasterization.
- Set explicit SVG width/height from `viewBox * scale` before converting to PNG.
- Support backend fallback: `auto` tries Kroki first and falls back to local `mmdc` if network rendering fails.

## Requirements

- `ffmpeg` in PATH.
- For `--backend kroki` (or `auto` primary path): `curl` and network access to `https://kroki.io`.
- For `--backend mmdc` (or `auto` fallback path): `mmdc` in PATH.

## Troubleshooting

- If DNS/network fails, retry with network-enabled execution.
- If network is unavailable, set `--backend mmdc` or keep `--backend auto` with local `mmdc` installed.
- If text still disappears, verify the SVG contains `<text>` nodes, not only `<foreignObject>`.
- If output is too large/small, change `--scale`.
