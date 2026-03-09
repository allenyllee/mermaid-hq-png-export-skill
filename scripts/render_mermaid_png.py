#!/usr/bin/env python3
import argparse
import pathlib
import re
import shutil
import subprocess
import tempfile

KROKI_URL = "https://kroki.io/mermaid/svg"
INIT_LINE = '%%{init: { "flowchart": { "htmlLabels": false } } }%%\n'


def ensure_deps() -> None:
    missing = [name for name in ("curl", "ffmpeg") if shutil.which(name) is None]
    if missing:
        raise SystemExit(f"Missing required tools: {', '.join(missing)}")


def prepare_mermaid_source(raw: str) -> str:
    if "htmlLabels" in raw:
        return raw
    return INIT_LINE + raw


def fetch_svg(mermaid_source: str) -> str:
    cmd = [
        "curl",
        "-sS",
        "-X",
        "POST",
        "-H",
        "Content-Type: text/plain",
        "--data-binary",
        "@-",
        KROKI_URL,
    ]
    proc = subprocess.run(cmd, input=mermaid_source, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"Failed to render Mermaid via Kroki: {proc.stderr.strip()}")
    svg = proc.stdout
    if "<svg" not in svg:
        preview = svg[:240].replace("\n", " ")
        raise SystemExit(f"Kroki did not return SVG. Response: {preview}")
    return svg


def resize_svg(svg: str, scale: float) -> tuple[str, int, int]:
    root_match = re.search(r"<svg\b[^>]*>", svg)
    if not root_match:
        raise SystemExit("Invalid SVG: cannot find <svg> root tag")

    root = root_match.group(0)
    vb_match = re.search(r'viewBox="([^"]+)"', root)
    if not vb_match:
        raise SystemExit("Invalid SVG: missing viewBox")

    vb_vals = vb_match.group(1).split()
    if len(vb_vals) != 4:
        raise SystemExit("Invalid SVG: malformed viewBox")

    vb_w = float(vb_vals[2])
    vb_h = float(vb_vals[3])
    out_w = max(1, int(round(vb_w * scale)))
    out_h = max(1, int(round(vb_h * scale)))

    root = re.sub(r'\sstyle="max-width:[^"]*;"', "", root)
    if re.search(r'\swidth="[^"]+"', root):
        root = re.sub(r'width="[^"]+"', f'width="{out_w}"', root, count=1)
    else:
        root = root.replace("<svg", f'<svg width="{out_w}"', 1)

    if re.search(r'\sheight="[^"]+"', root):
        root = re.sub(r'height="[^"]+"', f'height="{out_h}"', root, count=1)
    else:
        root = root.replace("<svg", f'<svg height="{out_h}"', 1)

    updated_svg = svg[: root_match.start()] + root + svg[root_match.end() :]
    return updated_svg, out_w, out_h


def rasterize(svg_path: pathlib.Path, png_path: pathlib.Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(svg_path),
        "-frames:v",
        "1",
        "-update",
        "1",
        str(png_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed:\n{proc.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Mermaid to native high-res PNG")
    parser.add_argument("--input", required=True, help="Path to Mermaid .mmd file")
    parser.add_argument("--output", required=True, help="Path to output PNG")
    parser.add_argument("--scale", type=float, default=4.0, help="Scale factor from SVG viewBox")
    parser.add_argument("--keep-svg", default="", help="Optional path to save intermediate SVG")
    args = parser.parse_args()

    if args.scale <= 0:
        raise SystemExit("--scale must be > 0")

    ensure_deps()

    in_path = pathlib.Path(args.input).expanduser().resolve()
    out_path = pathlib.Path(args.output).expanduser().resolve()

    source = in_path.read_text(encoding="utf-8")
    source = prepare_mermaid_source(source)
    svg = fetch_svg(source)
    svg, out_w, out_h = resize_svg(svg, args.scale)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if args.keep_svg:
        svg_path = pathlib.Path(args.keep_svg).expanduser().resolve()
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(svg, encoding="utf-8")
    else:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8")
        tmp.write(svg)
        tmp.flush()
        tmp.close()
        svg_path = pathlib.Path(tmp.name)

    try:
        rasterize(svg_path, out_path)
    finally:
        if not args.keep_svg and svg_path.exists():
            svg_path.unlink(missing_ok=True)

    print(f"Rendered: {out_path}")
    print(f"Size: {out_w}x{out_h}")


if __name__ == "__main__":
    main()
