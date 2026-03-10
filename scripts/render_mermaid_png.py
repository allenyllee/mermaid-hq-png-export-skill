#!/usr/bin/env python3
import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

KROKI_URL = "https://kroki.io/mermaid/svg"
INIT_LINE = '%%{init: { "flowchart": { "htmlLabels": false } } }%%\n'


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required tool: {name}")


def ensure_deps(backend: str) -> None:
    require_tool("ffmpeg")
    if backend == "kroki":
        require_tool("curl")
        return
    if backend == "mmdc":
        require_tool("mmdc")
        return
    if shutil.which("curl") is None and shutil.which("mmdc") is None:
        raise SystemExit("backend=auto requires either `curl` (Kroki) or `mmdc`")


def prepare_mermaid_source(raw: str) -> str:
    if "htmlLabels" in raw:
        return raw
    return INIT_LINE + raw


def fetch_svg_kroki(mermaid_source: str) -> str:
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
        err = proc.stderr.strip() or "unknown curl error"
        raise RuntimeError(f"Kroki request failed: {err}")
    svg = proc.stdout
    if "<svg" not in svg:
        preview = svg[:240].replace("\n", " ")
        raise RuntimeError(f"Kroki did not return SVG. Response: {preview}")
    return svg


def fetch_svg_mmdc(mermaid_source: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        mmd_path = tmpdir_path / "input.mmd"
        svg_path = tmpdir_path / "output.svg"
        mmd_path.write_text(mermaid_source, encoding="utf-8")

        cmd = ["mmdc", "-i", str(mmd_path), "-o", str(svg_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            err = proc.stderr.strip() or "unknown mmdc error"
            raise RuntimeError(f"mmdc render failed: {err}")
        if not svg_path.exists():
            raise RuntimeError("mmdc did not generate SVG output")
        svg = svg_path.read_text(encoding="utf-8", errors="replace")
        if "<svg" not in svg:
            raise RuntimeError("mmdc output is not valid SVG")
        return svg


def fetch_svg(mermaid_source: str, backend: str) -> tuple[str, str]:
    errors = []

    if backend in ("kroki", "auto") and shutil.which("curl") is not None:
        try:
            return fetch_svg_kroki(mermaid_source), "kroki"
        except RuntimeError as exc:
            errors.append(str(exc))
            if backend == "kroki":
                raise SystemExit(str(exc))

    if backend in ("mmdc", "auto") and shutil.which("mmdc") is not None:
        try:
            if backend == "auto" and errors:
                print("Kroki failed, fallback to local mmdc.", file=sys.stderr)
            return fetch_svg_mmdc(mermaid_source), "mmdc"
        except RuntimeError as exc:
            errors.append(str(exc))
            if backend == "mmdc":
                raise SystemExit(str(exc))

    if backend == "auto":
        detail = "; ".join(errors) if errors else "no available backend"
        raise SystemExit(f"Failed to render Mermaid (auto): {detail}")
    raise SystemExit(f"Failed to render Mermaid using backend={backend}")


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


def render_one(
    in_path: pathlib.Path,
    out_path: pathlib.Path,
    scale: float,
    backend: str,
    keep_svg_path: pathlib.Path | None = None,
) -> tuple[int, int, str]:
    source = in_path.read_text(encoding="utf-8")
    source = prepare_mermaid_source(source)
    svg, used_backend = fetch_svg(source, backend)
    svg, out_w, out_h = resize_svg(svg, scale)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if keep_svg_path is not None:
        keep_svg_path.parent.mkdir(parents=True, exist_ok=True)
        keep_svg_path.write_text(svg, encoding="utf-8")
        svg_path = keep_svg_path
    else:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8")
        tmp.write(svg)
        tmp.flush()
        tmp.close()
        svg_path = pathlib.Path(tmp.name)

    try:
        rasterize(svg_path, out_path)
    finally:
        if keep_svg_path is None and svg_path.exists():
            svg_path.unlink(missing_ok=True)

    return out_w, out_h, used_backend


def collect_inputs(batch_dir: pathlib.Path, pattern: str, recursive: bool) -> list[pathlib.Path]:
    if recursive:
        paths = sorted(p for p in batch_dir.rglob(pattern) if p.is_file())
    else:
        paths = sorted(p for p in batch_dir.glob(pattern) if p.is_file())
    return paths


def run_single(args: argparse.Namespace) -> int:
    in_path = pathlib.Path(args.input).expanduser().resolve()
    out_path = pathlib.Path(args.output).expanduser().resolve()
    keep_svg_path = pathlib.Path(args.keep_svg).expanduser().resolve() if args.keep_svg else None

    out_w, out_h, used_backend = render_one(
        in_path=in_path,
        out_path=out_path,
        scale=args.scale,
        backend=args.backend,
        keep_svg_path=keep_svg_path,
    )
    print(f"Rendered: {out_path}")
    print(f"Size: {out_w}x{out_h}")
    print(f"Backend: {used_backend}")
    return 0


def run_batch(args: argparse.Namespace) -> int:
    batch_dir = pathlib.Path(args.batch_dir).expanduser().resolve()
    output_dir = pathlib.Path(args.output_dir).expanduser().resolve()
    keep_svg_dir = pathlib.Path(args.keep_svg_dir).expanduser().resolve() if args.keep_svg_dir else None
    output_dir.mkdir(parents=True, exist_ok=True)
    if keep_svg_dir is not None:
        keep_svg_dir.mkdir(parents=True, exist_ok=True)

    inputs = collect_inputs(batch_dir, args.pattern, args.recursive)
    if not inputs:
        raise SystemExit(f"No input files found in {batch_dir} with pattern: {args.pattern}")

    failures = 0
    for in_path in inputs:
        suffix = args.name_suffix
        out_name = f"{in_path.stem}{suffix}.png"
        out_path = output_dir / out_name
        keep_svg_path = (keep_svg_dir / f"{in_path.stem}{suffix}.svg") if keep_svg_dir else None
        try:
            out_w, out_h, used_backend = render_one(
                in_path=in_path,
                out_path=out_path,
                scale=args.scale,
                backend=args.backend,
                keep_svg_path=keep_svg_path,
            )
            print(f"[OK] {in_path.name} -> {out_path.name} ({out_w}x{out_h}, backend={used_backend})")
        except SystemExit as exc:
            failures += 1
            print(f"[FAIL] {in_path.name}: {exc}", file=sys.stderr)

    total = len(inputs)
    success = total - failures
    print(f"Batch done: total={total}, success={success}, failed={failures}")
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Mermaid to native high-res PNG")
    parser.add_argument("--scale", type=float, default=4.0, help="Scale factor from SVG viewBox")
    parser.add_argument(
        "--backend",
        choices=("auto", "kroki", "mmdc"),
        default="auto",
        help="Render backend. auto tries Kroki first, then local mmdc.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", help="Path to Mermaid .mmd file (single mode)")
    mode.add_argument("--batch-dir", help="Directory containing .mmd files (batch mode)")

    parser.add_argument("--output", help="Path to output PNG (single mode)")
    parser.add_argument("--keep-svg", default="", help="Optional path to save intermediate SVG (single mode)")

    parser.add_argument("--output-dir", help="Output directory for batch mode")
    parser.add_argument("--keep-svg-dir", default="", help="Optional directory to save batch SVG files")
    parser.add_argument("--pattern", default="*.mmd", help="Glob pattern in batch mode (default: *.mmd)")
    parser.add_argument("--recursive", action="store_true", help="Recursively search batch-dir")
    parser.add_argument(
        "--name-suffix",
        default="-hq",
        help="Output filename suffix in batch mode before .png (default: -hq)",
    )

    args = parser.parse_args()
    if args.scale <= 0:
        raise SystemExit("--scale must be > 0")

    if args.input:
        if not args.output:
            raise SystemExit("--output is required when using --input")
    else:
        if not args.output_dir:
            raise SystemExit("--output-dir is required when using --batch-dir")
    return args


def main() -> None:
    args = parse_args()
    ensure_deps(args.backend)
    exit_code = run_single(args) if args.input else run_batch(args)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
