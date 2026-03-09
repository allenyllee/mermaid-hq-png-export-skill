---
name: mermaid-hq-png-export
description: Render Mermaid diagrams into high-resolution PNG with sharp text (non-upscaled). Use when users ask to convert Mermaid code to PNG, request higher resolution, complain about blurry output, or report missing text after SVG/PNG conversion.
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

## Why This Works

- Render from Mermaid source again instead of scaling an old PNG.
- Add Mermaid init config `flowchart.htmlLabels=false` (if not present) so text is emitted as SVG `<text>`, avoiding dropped labels during rasterization.
- Set explicit SVG width/height from `viewBox * scale` before converting to PNG.

## Requirements

- `curl` and `ffmpeg` in PATH.
- Network access to `https://kroki.io`.

## Troubleshooting

- If DNS/network fails, retry with network-enabled execution.
- If text still disappears, verify the SVG contains `<text>` nodes, not only `<foreignObject>`.
- If output is too large/small, change `--scale`.
