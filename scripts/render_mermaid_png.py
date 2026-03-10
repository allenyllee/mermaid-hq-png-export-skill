#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile

KROKI_URL = "https://kroki.io/mermaid/svg"
INIT_LINE = '%%{init: { "flowchart": { "htmlLabels": false } } }%%\n'
DEFAULT_NODE_VERSION = os.environ.get("MERMAID_SKILL_NODE_VERSION", "v24.14.0")
DEFAULT_MERMAID_VERSION = os.environ.get("MERMAID_SKILL_MERMAID_VERSION", "11.13.0")
DEFAULT_PUPPETEER_CORE_VERSION = os.environ.get("MERMAID_SKILL_PPTR_CORE_VERSION", "23.11.1")

SKILL_LOCAL_ROOT = pathlib.Path.home() / ".local/mermaid-hq-png-export"
LOCAL_NODE_ROOT = SKILL_LOCAL_ROOT / "node"
LOCAL_NODE_CURRENT = LOCAL_NODE_ROOT / "current"
LOCAL_NODE_BIN = LOCAL_NODE_CURRENT / "bin"
LOCAL_NPM_GLOBAL = SKILL_LOCAL_ROOT / "npm-global"
LOCAL_MERMAID_JS_ROOT = SKILL_LOCAL_ROOT / "mermaid-js-cli"
LOCAL_MMDC = LOCAL_NPM_GLOBAL / "bin" / "mmdc"
LEGACY_MMDC = pathlib.Path.home() / ".local/node/current/bin/mmdc"
LEGACY_NODE_BIN = pathlib.Path.home() / ".local/node/current/bin"
LOCAL_MERMAID_JS_SCRIPT = pathlib.Path(__file__).with_name("render_mermaid_local.mjs")


def run_cmd(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def mmdc_env() -> dict[str, str]:
    env = os.environ.copy()
    prepend: list[str] = []
    if LOCAL_NODE_BIN.exists():
        prepend.append(str(LOCAL_NODE_BIN))
    if LEGACY_NODE_BIN.exists():
        prepend.append(str(LEGACY_NODE_BIN))
    if LOCAL_NPM_GLOBAL.joinpath("bin").exists():
        prepend.append(str(LOCAL_NPM_GLOBAL / "bin"))
    if LEGACY_MMDC.parent.exists():
        prepend.append(str(LEGACY_MMDC.parent))
    if prepend:
        current = env.get("PATH", "")
        env["PATH"] = ":".join(prepend + ([current] if current else []))
    return env


def resolve_node_tools() -> tuple[str | None, str | None]:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node and npm:
        return node, npm

    fallback_node = LOCAL_NODE_BIN / "node"
    fallback_npm = LOCAL_NODE_BIN / "npm"
    if fallback_node.exists() and fallback_npm.exists():
        return str(fallback_node), str(fallback_npm)
    legacy_node = LEGACY_NODE_BIN / "node"
    legacy_npm = LEGACY_NODE_BIN / "npm"
    if legacy_node.exists() and legacy_npm.exists():
        return str(legacy_node), str(legacy_npm)
    return None, None


def resolve_mmdc() -> str | None:
    path = shutil.which("mmdc")
    if path:
        return path
    if LOCAL_MMDC.exists() and LOCAL_MMDC.is_file():
        return str(LOCAL_MMDC)
    if LEGACY_MMDC.exists() and LEGACY_MMDC.is_file():
        return str(LEGACY_MMDC)
    return None


def install_local_node() -> bool:
    node, npm = resolve_node_tools()
    if node and npm:
        return True

    system = platform.system().lower()
    arch = platform.machine().lower()
    arch_map = {
        "x86_64": "x64",
        "amd64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    if system != "linux" or arch not in arch_map:
        print(
            f"Auto Node install unsupported on this platform ({system}/{arch}).",
            file=sys.stderr,
        )
        return False

    if shutil.which("curl") is None or shutil.which("tar") is None:
        print("Cannot auto-install Node: `curl` and `tar` are required.", file=sys.stderr)
        return False

    node_arch = arch_map[arch]
    tar_name = f"node-{DEFAULT_NODE_VERSION}-linux-{node_arch}.tar.xz"
    url = f"https://nodejs.org/dist/{DEFAULT_NODE_VERSION}/{tar_name}"

    LOCAL_NODE_ROOT.mkdir(parents=True, exist_ok=True)
    archive_path = LOCAL_NODE_ROOT / tar_name

    print(f"Installing Node.js {DEFAULT_NODE_VERSION} locally...", file=sys.stderr)
    dl = run_cmd(["curl", "-fsSL", url, "-o", str(archive_path)])
    if dl.returncode != 0:
        err = dl.stderr.strip() or "download failed"
        print(f"Node download failed: {err}", file=sys.stderr)
        return False

    ext = run_cmd(["tar", "-xJf", str(archive_path), "-C", str(LOCAL_NODE_ROOT)])
    if ext.returncode != 0:
        err = ext.stderr.strip() or "extract failed"
        print(f"Node extract failed: {err}", file=sys.stderr)
        return False

    extracted = LOCAL_NODE_ROOT / f"node-{DEFAULT_NODE_VERSION}-linux-{node_arch}"
    if not extracted.exists():
        print("Node extract completed but target directory missing.", file=sys.stderr)
        return False

    if LOCAL_NODE_CURRENT.exists() or LOCAL_NODE_CURRENT.is_symlink():
        if LOCAL_NODE_CURRENT.is_symlink() or LOCAL_NODE_CURRENT.is_file():
            LOCAL_NODE_CURRENT.unlink()
        else:
            shutil.rmtree(LOCAL_NODE_CURRENT)
    LOCAL_NODE_CURRENT.symlink_to(extracted)

    try:
        archive_path.unlink(missing_ok=True)
    except OSError:
        pass

    node, npm = resolve_node_tools()
    return bool(node and npm)


def install_mmdc() -> bool:
    if resolve_mmdc() is not None:
        return True

    node, npm = resolve_node_tools()
    if not (node and npm):
        if not install_local_node():
            return False
        node, npm = resolve_node_tools()

    if not (node and npm):
        return False

    LOCAL_NPM_GLOBAL.mkdir(parents=True, exist_ok=True)
    print("Installing mermaid-cli (`mmdc`) locally...", file=sys.stderr)
    cmd = [
        npm,
        "install",
        "-g",
        "--prefix",
        str(LOCAL_NPM_GLOBAL),
        "@mermaid-js/mermaid-cli",
    ]
    proc = run_cmd(cmd, env=mmdc_env())
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip() or "npm install failed"
        print(f"mmdc install failed: {err}", file=sys.stderr)
        return False

    return resolve_mmdc() is not None


def resolve_chromium() -> str | None:
    env_path = os.environ.get("MERMAID_SKILL_CHROME") or os.environ.get("CHROME_BIN")
    cache_candidates = sorted(pathlib.Path.home().glob(".cache/puppeteer/chrome/*/chrome-linux64/chrome"))
    playwright_candidates = sorted(pathlib.Path.home().glob(".cache/ms-playwright/*/chrome-linux64/chrome"))
    candidates = [
        env_path,
        str(cache_candidates[-1]) if cache_candidates else None,
        str(playwright_candidates[-1]) if playwright_candidates else None,
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        "/snap/bin/chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).exists():
            return str(pathlib.Path(candidate))
    return None


def mermaid_js_modules_ready() -> bool:
    mermaid_pkg = LOCAL_MERMAID_JS_ROOT / "node_modules" / "mermaid" / "package.json"
    pptr_pkg = LOCAL_MERMAID_JS_ROOT / "node_modules" / "puppeteer-core" / "package.json"
    return mermaid_pkg.exists() and pptr_pkg.exists()


def install_mermaid_js() -> bool:
    if mermaid_js_modules_ready():
        return True

    node, npm = resolve_node_tools()
    if not (node and npm):
        if not install_local_node():
            return False
        node, npm = resolve_node_tools()
    if not (node and npm):
        return False

    chrome_path = resolve_chromium()
    if chrome_path is None:
        print(
            "Cannot enable backend=mermaid-js: no Chromium/Chrome executable found.",
            file=sys.stderr,
        )
        return False

    LOCAL_MERMAID_JS_ROOT.mkdir(parents=True, exist_ok=True)
    cmd = [
        npm,
        "install",
        "--prefix",
        str(LOCAL_MERMAID_JS_ROOT),
        "--no-fund",
        "--no-audit",
        "--save-exact",
        f"mermaid@{DEFAULT_MERMAID_VERSION}",
        f"puppeteer-core@{DEFAULT_PUPPETEER_CORE_VERSION}",
    ]
    print("Installing local Mermaid JS renderer dependencies...", file=sys.stderr)
    proc = run_cmd(cmd, env=mmdc_env())
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip() or "npm install failed"
        print(f"mermaid-js install failed: {err}", file=sys.stderr)
        return False
    return mermaid_js_modules_ready()


def resolve_backend(requested: str) -> str:
    if requested == "kroki":
        if shutil.which("curl") is None:
            raise SystemExit("backend=kroki requires `curl`")
        if shutil.which("ffmpeg") is None:
            raise SystemExit("backend=kroki requires `ffmpeg`")
        return "kroki"

    if requested == "mermaid-js":
        if resolve_chromium() is None:
            raise SystemExit("backend=mermaid-js requires local Chromium/Chrome")
        if not install_mermaid_js():
            raise SystemExit("backend=mermaid-js could not install required packages")
        return "mermaid-js"

    # requested == mmdc or auto
    if resolve_mmdc() is None:
        print("`mmdc` not found. Trying local install...", file=sys.stderr)
        if not install_mmdc():
            if resolve_chromium() is not None:
                print("`mmdc` unavailable; trying backend=mermaid-js.", file=sys.stderr)
                if install_mermaid_js():
                    return "mermaid-js"
            if shutil.which("curl") and shutil.which("ffmpeg"):
                print("`mmdc` unavailable; fallback to backend=kroki.", file=sys.stderr)
                return "kroki"
            raise SystemExit("`mmdc` install failed and no fallback backend is available")
    return "mmdc"


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


def read_png_size(png_path: pathlib.Path) -> tuple[int, int]:
    data = png_path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"Invalid PNG output: {png_path}")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def render_png_kroki(
    in_path: pathlib.Path,
    out_path: pathlib.Path,
    scale: float,
    keep_svg_path: pathlib.Path | None,
) -> tuple[int, int]:
    if shutil.which("curl") is None or shutil.which("ffmpeg") is None:
        raise SystemExit("backend=kroki requires `curl` and `ffmpeg`")

    source = in_path.read_text(encoding="utf-8")
    source = prepare_mermaid_source(source)
    try:
        svg = fetch_svg_kroki(source)
    except RuntimeError as exc:
        raise SystemExit(str(exc))

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

    return out_w, out_h


def render_png_mmdc(
    in_path: pathlib.Path,
    out_path: pathlib.Path,
    scale: float,
    keep_svg_path: pathlib.Path | None,
) -> tuple[int, int]:
    mmdc = resolve_mmdc()
    if mmdc is None:
        raise SystemExit("Missing required tool: mmdc")

    source = in_path.read_text(encoding="utf-8")
    source = prepare_mermaid_source(source)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        mmd_path = tmpdir_path / "input.mmd"
        pptr_path = tmpdir_path / "puppeteer.json"
        mmd_path.write_text(source, encoding="utf-8")
        pptr_path.write_text(
            json.dumps(
                {
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                    ]
                }
            ),
            encoding="utf-8",
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        png_cmd = [
            mmdc,
            "-p",
            str(pptr_path),
            "-i",
            str(mmd_path),
            "-o",
            str(out_path),
            "-e",
            "png",
            "-s",
            str(scale),
            "-b",
            "transparent",
            "-q",
        ]
        png_proc = subprocess.run(png_cmd, capture_output=True, text=True, env=mmdc_env())
        if png_proc.returncode != 0:
            err = png_proc.stderr.strip() or "unknown mmdc error"
            raise SystemExit(f"mmdc render failed: {err}")
        if not out_path.exists():
            raise SystemExit("mmdc did not generate PNG output")

        if keep_svg_path is not None:
            keep_svg_path.parent.mkdir(parents=True, exist_ok=True)
            svg_cmd = [
                mmdc,
                "-p",
                str(pptr_path),
                "-i",
                str(mmd_path),
                "-o",
                str(keep_svg_path),
                "-e",
                "svg",
                "-q",
            ]
            svg_proc = subprocess.run(svg_cmd, capture_output=True, text=True, env=mmdc_env())
            if svg_proc.returncode != 0:
                err = svg_proc.stderr.strip() or "unknown mmdc error"
                raise SystemExit(f"mmdc SVG export failed: {err}")

    return read_png_size(out_path)


def render_png_mermaid_js(
    in_path: pathlib.Path,
    out_path: pathlib.Path,
    scale: float,
    keep_svg_path: pathlib.Path | None,
) -> tuple[int, int]:
    node, _npm = resolve_node_tools()
    if node is None:
        raise SystemExit("backend=mermaid-js requires Node.js")
    if not mermaid_js_modules_ready() and not install_mermaid_js():
        raise SystemExit("backend=mermaid-js could not install required packages")
    chrome_path = resolve_chromium()
    if chrome_path is None:
        raise SystemExit("backend=mermaid-js requires local Chromium/Chrome")

    source = prepare_mermaid_source(in_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        mmd_path = tmpdir_path / "input.mmd"
        mmd_path.write_text(source, encoding="utf-8")

        cmd = [
            node,
            str(LOCAL_MERMAID_JS_SCRIPT),
            "--input",
            str(mmd_path),
            "--output",
            str(out_path),
            "--moduleRoot",
            str(LOCAL_MERMAID_JS_ROOT),
            "--chromePath",
            chrome_path,
            "--scale",
            str(scale),
        ]
        if keep_svg_path is not None:
            keep_svg_path.parent.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--outputSvg", str(keep_svg_path)])

        out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=mmdc_env())
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip() or "unknown mermaid-js error"
            raise SystemExit(f"mermaid-js render failed: {err}")
        if not out_path.exists():
            raise SystemExit("mermaid-js did not generate PNG output")
    return read_png_size(out_path)


def render_one(
    in_path: pathlib.Path,
    out_path: pathlib.Path,
    scale: float,
    backend: str,
    keep_svg_path: pathlib.Path | None = None,
) -> tuple[int, int, str]:
    if backend == "mmdc":
        out_w, out_h = render_png_mmdc(
            in_path=in_path,
            out_path=out_path,
            scale=scale,
            keep_svg_path=keep_svg_path,
        )
        return out_w, out_h, "mmdc"
    if backend == "mermaid-js":
        out_w, out_h = render_png_mermaid_js(
            in_path=in_path,
            out_path=out_path,
            scale=scale,
            keep_svg_path=keep_svg_path,
        )
        return out_w, out_h, "mermaid-js"

    out_w, out_h = render_png_kroki(
        in_path=in_path,
        out_path=out_path,
        scale=scale,
        keep_svg_path=keep_svg_path,
    )
    return out_w, out_h, "kroki"


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
        out_name = f"{in_path.stem}{args.name_suffix}.png"
        out_path = output_dir / out_name
        keep_svg_path = (keep_svg_dir / f"{in_path.stem}{args.name_suffix}.svg") if keep_svg_dir else None
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
    parser.add_argument("--scale", type=float, default=4.0, help="Scale factor from SVG/Puppeteer")
    parser.add_argument(
        "--backend",
        choices=("auto", "kroki", "mmdc", "mermaid-js"),
        default="mmdc",
        help="Default `mmdc`. If unavailable, `auto` tries `mmdc`, then local `mermaid-js`, then kroki.",
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
    elif not args.output_dir:
        raise SystemExit("--output-dir is required when using --batch-dir")

    args.backend = resolve_backend(args.backend)
    return args


def main() -> None:
    args = parse_args()
    exit_code = run_single(args) if args.input else run_batch(args)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
