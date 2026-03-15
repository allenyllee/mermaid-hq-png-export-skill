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

KROKI_SVG_URL = "https://kroki.io/mermaid/svg"
KROKI_PNG_URL = "https://kroki.io/mermaid/png"
DEFAULT_NODE_VERSION = os.environ.get("MERMAID_SKILL_NODE_VERSION", "v24.14.0")
DEFAULT_KROKI_LOCAL_MERMAID_VERSION = os.environ.get("MERMAID_SKILL_KROKI_LOCAL_VERSION", "11.12.3")
DEFAULT_PUPPETEER_CORE_VERSION = os.environ.get("MERMAID_SKILL_PPTR_CORE_VERSION", "23.11.1")
DEFAULT_PUPPETEER_VERSION = os.environ.get("MERMAID_SKILL_PPTR_VERSION", "23.11.1")

SKILL_LOCAL_ROOT = pathlib.Path.home() / ".local/mermaid-hq-png-export"
LOCAL_NODE_ROOT = SKILL_LOCAL_ROOT / "node"
LOCAL_NODE_CURRENT = LOCAL_NODE_ROOT / "current"
LOCAL_NODE_BIN = LOCAL_NODE_CURRENT / "bin"
LOCAL_NPM_GLOBAL = SKILL_LOCAL_ROOT / "npm-global"
LOCAL_KROKI_LOCAL_ROOT = SKILL_LOCAL_ROOT / "kroki-mermaid-local-cli"
LOCAL_MMDC = LOCAL_NPM_GLOBAL / "bin" / "mmdc"
LOCAL_MMDC_WINDOWS = LOCAL_NPM_GLOBAL / "mmdc"
LEGACY_MMDC = pathlib.Path.home() / ".local/node/current/bin/mmdc"
LEGACY_NODE_BIN = pathlib.Path.home() / ".local/node/current/bin"
LOCAL_KROKI_LOCAL_SCRIPT = pathlib.Path(__file__).with_name("render_kroki_mermaid_local.mjs")
IS_WINDOWS = platform.system().lower() == "windows"


def run_cmd(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def executable_candidates(base: pathlib.Path | str) -> list[str]:
    path = pathlib.Path(base)
    if IS_WINDOWS:
        return [str(path.with_suffix(".cmd")), str(path.with_suffix(".exe")), str(path), str(path.with_suffix(".ps1"))]
    return [str(path)]


def first_existing_path(candidates: list[str]) -> str | None:
    for candidate in candidates:
        if pathlib.Path(candidate).exists():
            return candidate
    return None


def which_first(names: list[str]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def mmdc_env() -> dict[str, str]:
    env = os.environ.copy()
    prepend: list[str] = []
    if LOCAL_NODE_BIN.exists():
        prepend.append(str(LOCAL_NODE_BIN))
    if LEGACY_NODE_BIN.exists():
        prepend.append(str(LEGACY_NODE_BIN))
    if LOCAL_NPM_GLOBAL.exists():
        prepend.append(str(LOCAL_NPM_GLOBAL))
    if LOCAL_NPM_GLOBAL.joinpath("bin").exists():
        prepend.append(str(LOCAL_NPM_GLOBAL / "bin"))
    if LEGACY_MMDC.parent.exists():
        prepend.append(str(LEGACY_MMDC.parent))
    if prepend:
        current = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(prepend + ([current] if current else []))
    return env


def resolve_node_tools() -> tuple[str | None, str | None]:
    node = which_first(["node", "node.exe"])
    npm = which_first(["npm.cmd", "npm", "npm.exe"])
    if node and npm:
        return node, npm

    fallback_node = first_existing_path(executable_candidates(LOCAL_NODE_BIN / "node"))
    fallback_npm = first_existing_path(executable_candidates(LOCAL_NODE_BIN / "npm"))
    if fallback_node and fallback_npm:
        return fallback_node, fallback_npm
    legacy_node = first_existing_path(executable_candidates(LEGACY_NODE_BIN / "node"))
    legacy_npm = first_existing_path(executable_candidates(LEGACY_NODE_BIN / "npm"))
    if legacy_node and legacy_npm:
        return legacy_node, legacy_npm
    return None, None


def resolve_mmdc() -> str | None:
    path = which_first(["mmdc.cmd", "mmdc", "mmdc.exe"])
    if path:
        return path
    local_windows_mmdc = first_existing_path(executable_candidates(LOCAL_MMDC_WINDOWS))
    if local_windows_mmdc:
        return local_windows_mmdc
    local_mmdc = first_existing_path(executable_candidates(LOCAL_MMDC))
    if local_mmdc:
        return local_mmdc
    legacy_mmdc = first_existing_path(executable_candidates(LEGACY_MMDC))
    if legacy_mmdc:
        return legacy_mmdc
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
        existing = resolve_mmdc()
        if existing is not None:
            return True
        err = (proc.stderr or proc.stdout).strip() or "npm install failed"
        print(f"mmdc install failed: {err}", file=sys.stderr)
        return False

    return resolve_mmdc() is not None


def resolve_chromium() -> str | None:
    env_path = os.environ.get("MERMAID_SKILL_CHROME") or os.environ.get("CHROME_BIN")
    cache_candidates = sorted(pathlib.Path.home().glob(".cache/puppeteer/chrome/*/chrome-linux64/chrome"))
    playwright_candidates = sorted(pathlib.Path.home().glob(".cache/ms-playwright/*/chrome-linux64/chrome"))
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates = [
        env_path,
        str(cache_candidates[-1]) if cache_candidates else None,
        str(playwright_candidates[-1]) if playwright_candidates else None,
        str(pathlib.Path(local_app_data) / "Google/Chrome/Application/chrome.exe") if local_app_data else None,
        str(pathlib.Path(local_app_data) / "Chromium/Application/chrome.exe") if local_app_data else None,
        str(pathlib.Path(local_app_data) / "Microsoft/Edge/Application/msedge.exe") if local_app_data else None,
        str(pathlib.Path(program_files) / "Google/Chrome/Application/chrome.exe"),
        str(pathlib.Path(program_files_x86) / "Google/Chrome/Application/chrome.exe"),
        str(pathlib.Path(program_files) / "Microsoft/Edge/Application/msedge.exe"),
        str(pathlib.Path(program_files_x86) / "Microsoft/Edge/Application/msedge.exe"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
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


def kroki_local_modules_ready() -> bool:
    return current_kroki_local_puppeteer_package() is not None


def read_installed_package_version(module_root: pathlib.Path, package_name: str) -> str | None:
    package_path = module_root / "node_modules" / package_name / "package.json"
    if not package_path.exists():
        return None
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = data.get("version")
    return version if isinstance(version, str) else None


def current_kroki_local_puppeteer_package() -> tuple[str, str] | None:
    mermaid_version = read_installed_package_version(LOCAL_KROKI_LOCAL_ROOT, "mermaid")
    if mermaid_version != DEFAULT_KROKI_LOCAL_MERMAID_VERSION:
        return None

    pptr_core_version = read_installed_package_version(LOCAL_KROKI_LOCAL_ROOT, "puppeteer-core")
    if pptr_core_version == DEFAULT_PUPPETEER_CORE_VERSION:
        return ("puppeteer-core", pptr_core_version)

    pptr_version = read_installed_package_version(LOCAL_KROKI_LOCAL_ROOT, "puppeteer")
    if pptr_version == DEFAULT_PUPPETEER_VERSION:
        return ("puppeteer", pptr_version)

    return None


def install_kroki_local() -> bool:
    if kroki_local_modules_ready():
        return True

    node, npm = resolve_node_tools()
    if not (node and npm):
        if not install_local_node():
            return False
        node, npm = resolve_node_tools()
    if not (node and npm):
        return False

    LOCAL_KROKI_LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    chrome_path = resolve_chromium()
    prefer_local_browser = chrome_path is not None
    puppeteer_pkg = (
        f"puppeteer-core@{DEFAULT_PUPPETEER_CORE_VERSION}"
        if prefer_local_browser
        else f"puppeteer@{DEFAULT_PUPPETEER_VERSION}"
    )
    remove_pkg = "puppeteer" if prefer_local_browser else "puppeteer-core"
    cmd = [
        npm,
        "install",
        "--prefix",
        str(LOCAL_KROKI_LOCAL_ROOT),
        "--no-fund",
        "--no-audit",
        "--save-exact",
        f"mermaid@{DEFAULT_KROKI_LOCAL_MERMAID_VERSION}",
        puppeteer_pkg,
    ]
    if prefer_local_browser:
        print("Installing local Kroki-style Mermaid renderer dependencies with `puppeteer-core`...", file=sys.stderr)
    else:
        print("Installing local Kroki-style Mermaid renderer dependencies with bundled `puppeteer`...", file=sys.stderr)
    proc = run_cmd(cmd, env=mmdc_env())
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip() or "npm install failed"
        print(f"kroki-local install failed: {err}", file=sys.stderr)
        return False
    cleanup = run_cmd([npm, "uninstall", "--prefix", str(LOCAL_KROKI_LOCAL_ROOT), remove_pkg], env=mmdc_env())
    if cleanup.returncode != 0 and "not in this workspace" not in (cleanup.stderr or ""):
        err = (cleanup.stderr or cleanup.stdout).strip() or "npm uninstall failed"
        print(f"kroki-local cleanup warning: {err}", file=sys.stderr)
    return kroki_local_modules_ready()


def resolve_backend(requested: str) -> str:
    if requested == "kroki":
        if shutil.which("curl") is None:
            raise SystemExit("backend=kroki requires `curl`")
        return "kroki"

    if requested == "kroki-local":
        if not install_kroki_local():
            raise SystemExit("backend=kroki-local could not install required packages")
        return "kroki-local"

    # requested == mmdc or auto
    if resolve_mmdc() is None:
        print("`mmdc` not found. Trying local install...", file=sys.stderr)
        if not install_mmdc():
            print("`mmdc` unavailable; trying backend=kroki-local.", file=sys.stderr)
            if install_kroki_local():
                return "kroki-local"
            if shutil.which("curl"):
                print("`mmdc` unavailable; fallback to backend=kroki.", file=sys.stderr)
                return "kroki"
            raise SystemExit("`mmdc` install failed and no fallback backend is available")
    return "mmdc"


def fetch_kroki(mermaid_source: str, url: str, *, binary: bool) -> bytes | str:
    cmd = [
        "curl",
        "-sS",
        "-X",
        "POST",
        "-H",
        "Content-Type: text/plain",
        "--data-binary",
        "@-",
        url,
    ]
    proc = subprocess.run(
        cmd,
        input=mermaid_source.encode("utf-8") if binary else mermaid_source,
        text=not binary,
        capture_output=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip() or "unknown curl error"
        raise RuntimeError(f"Kroki request failed: {err}")
    return proc.stdout if not binary else proc.stdout


def fetch_svg_kroki(mermaid_source: str) -> str:
    svg = fetch_kroki(mermaid_source, KROKI_SVG_URL, binary=False)
    if "<svg" not in svg:
        preview = svg[:240].replace("\n", " ")
        raise RuntimeError(f"Kroki did not return SVG. Response: {preview}")
    return svg


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
    if shutil.which("curl") is None:
        raise SystemExit("backend=kroki requires `curl`")

    source = in_path.read_text(encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        png_bytes = fetch_kroki(source, KROKI_PNG_URL, binary=True)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    out_path.write_bytes(png_bytes)

    if keep_svg_path is not None:
        try:
            svg = fetch_svg_kroki(source)
        except RuntimeError as exc:
            raise SystemExit(str(exc))
        keep_svg_path.parent.mkdir(parents=True, exist_ok=True)
        keep_svg_path.write_text(svg, encoding="utf-8")

    return read_png_size(out_path)


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


def render_svg_kroki_local_source(source: str) -> str:
    node, _npm = resolve_node_tools()
    if node is None:
        raise SystemExit("backend=kroki-local requires Node.js")
    if not kroki_local_modules_ready() and not install_kroki_local():
        raise SystemExit("backend=kroki-local could not install required packages")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        mmd_path = tmpdir_path / "input.mmd"
        svg_path = tmpdir_path / "output.svg"
        mmd_path.write_text(source, encoding="utf-8")
        cmd = [
            node,
            str(LOCAL_KROKI_LOCAL_SCRIPT),
            "--input",
            str(mmd_path),
            "--outputSvg",
            str(svg_path),
            "--moduleRoot",
            str(LOCAL_KROKI_LOCAL_ROOT),
        ]
        chrome_path = resolve_chromium()
        if chrome_path is not None:
            cmd.extend(["--chromePath", chrome_path])
        proc = subprocess.run(cmd, capture_output=True, text=True, env=mmdc_env())
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip() or "unknown kroki-local error"
            raise SystemExit(f"kroki-local render failed: {err}")
        if not svg_path.exists():
            raise SystemExit("kroki-local did not generate SVG output")
        return svg_path.read_text(encoding="utf-8")


def render_png_kroki_local(
    in_path: pathlib.Path,
    out_path: pathlib.Path,
    scale: float,
    keep_svg_path: pathlib.Path | None,
) -> tuple[int, int]:
    source = in_path.read_text(encoding="utf-8")
    node, _npm = resolve_node_tools()
    if node is None:
        raise SystemExit("backend=kroki-local requires Node.js")
    if not kroki_local_modules_ready() and not install_kroki_local():
        raise SystemExit("backend=kroki-local could not install required packages")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        mmd_path = tmpdir_path / "input.mmd"
        svg_path = keep_svg_path if keep_svg_path is not None else tmpdir_path / "output.svg"
        mmd_path.write_text(source, encoding="utf-8")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        if keep_svg_path is not None:
            keep_svg_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            node,
            str(LOCAL_KROKI_LOCAL_SCRIPT),
            "--input",
            str(mmd_path),
            "--outputPng",
            str(out_path),
            "--outputSvg",
            str(svg_path),
            "--moduleRoot",
            str(LOCAL_KROKI_LOCAL_ROOT),
            "--scale",
            str(scale),
        ]
        chrome_path = resolve_chromium()
        if chrome_path is not None:
            cmd.extend(["--chromePath", chrome_path])
        proc = subprocess.run(cmd, capture_output=True, text=True, env=mmdc_env())
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip() or "unknown kroki-local error"
            raise SystemExit(f"kroki-local render failed: {err}")
        if not out_path.exists():
            raise SystemExit("kroki-local did not generate PNG output")

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
    if backend == "kroki-local":
        out_w, out_h = render_png_kroki_local(
            in_path=in_path,
            out_path=out_path,
            scale=scale,
            keep_svg_path=keep_svg_path,
        )
        return out_w, out_h, "kroki-local"

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

    if args.backend == "kroki" and args.scale != 1.0:
        print(
            "Warning: backend=kroki ignores local raster scaling; remote Kroki PNG size is used as-is.",
            file=sys.stderr,
        )

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

    if args.backend == "kroki" and args.scale != 1.0:
        print(
            "Warning: backend=kroki ignores local raster scaling; remote Kroki PNG size is used as-is.",
            file=sys.stderr,
        )

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
    parser.add_argument(
        "--scale",
        type=float,
        default=4.0,
        help="Scale factor for local backends (`mmdc`, `kroki-local`). Remote `kroki` PNG output ignores local scaling.",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "kroki", "kroki-local", "mmdc"),
        default="mmdc",
        help="Default `mmdc`. If unavailable, `auto` tries `mmdc`, then `kroki-local`, then kroki.",
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
