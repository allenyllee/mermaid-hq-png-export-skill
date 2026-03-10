#!/usr/bin/env python3
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts" / "render_mermaid_png.py"
CASES = pathlib.Path(__file__).resolve().parent / "cases"
KROKI_LOCAL_ROOT = pathlib.Path.home() / ".local" / "mermaid-hq-png-export" / "kroki-mermaid-local-cli"


def png_size(path: pathlib.Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"Not a PNG: {path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def dark_pixel_ratio(path: pathlib.Path) -> float:
    width, height = png_size(path)
    # Sample inside the first node body where text should exist.
    x0, x1 = int(width * 0.08), int(width * 0.32)
    y0, y1 = int(height * 0.28), int(height * 0.72)

    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    )

    dark = 0
    total = 0
    for y in range(y0, y1):
        row = y * width * 4
        for x in range(x0, x1):
            i = row + x * 4
            r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
            if a > 180:
                total += 1
                if r < 90 and g < 90 and b < 90:
                    dark += 1

    return (dark / total) if total else 0.0


def svg_viewbox(path: pathlib.Path) -> tuple[float, float, float, float]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'viewBox="([^"]+)"', text)
    if not match:
        raise RuntimeError(f"Missing viewBox in SVG: {path}")
    vals = [float(x) for x in match.group(1).split()]
    if len(vals) != 4:
        raise RuntimeError(f"Malformed viewBox in SVG: {path}")
    return vals[0], vals[1], vals[2], vals[3]


def expected_kroki_local_version() -> str:
    text = RENDERER.read_text(encoding="utf-8")
    match = re.search(
        r'DEFAULT_KROKI_LOCAL_MERMAID_VERSION = os\.environ\.get\("MERMAID_SKILL_KROKI_LOCAL_VERSION", "([^"]+)"\)',
        text,
    )
    if not match:
        raise RuntimeError("Could not find DEFAULT_KROKI_LOCAL_MERMAID_VERSION in renderer")
    return match.group(1)


def installed_package_version(module_root: pathlib.Path, package_name: str) -> str | None:
    package_path = module_root / "node_modules" / package_name / "package.json"
    if not package_path.exists():
        return None
    data = json.loads(package_path.read_text(encoding="utf-8"))
    version = data.get("version")
    return version if isinstance(version, str) else None


def run_renderer(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(RENDERER)] + args,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def report(status: str, name: str, detail: str = "") -> None:
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)


def main() -> int:
    failures = 0
    xfails = 0

    if not RENDERER.exists():
        print(f"Renderer script not found: {RENDERER}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="mermaid-skill-regression-") as tmp:
        out = pathlib.Path(tmp)
        expected_kroki_version = expected_kroki_local_version()

        # 1) mmdc regression: flowchart text must be visible in PNG.
        flow_src = CASES / "arch2-flowchart.mmd"
        flow_png_mmdc = out / "arch2-mmdc.png"
        flow_svg_mmdc = out / "arch2-mmdc.svg"

        rc, so, se = run_renderer(
            [
                "--backend",
                "mmdc",
                "--input",
                str(flow_src),
                "--output",
                str(flow_png_mmdc),
                "--scale",
                "3",
                "--keep-svg",
                str(flow_svg_mmdc),
            ]
        )
        if rc != 0:
            failures += 1
            report("FAIL", "mmdc_flowchart_text", f"renderer failed: {se.strip() or so.strip()}")
        else:
            ratio = dark_pixel_ratio(flow_png_mmdc)
            if ratio < 0.01:
                failures += 1
                report("FAIL", "mmdc_flowchart_text", f"dark ratio too low ({ratio:.4f})")
            else:
                report("PASS", "mmdc_flowchart_text", f"dark ratio={ratio:.4f}")

        # 2) kroki known limitation: this flowchart often loses text in PNG (XFAIL).
        flow_png_kroki = out / "arch2-kroki.png"
        flow_svg_kroki = out / "arch2-kroki.svg"
        rc, so, se = run_renderer(
            [
                "--backend",
                "kroki",
                "--input",
                str(flow_src),
                "--output",
                str(flow_png_kroki),
                "--scale",
                "3",
                "--keep-svg",
                str(flow_svg_kroki),
            ]
        )
        if rc != 0:
            xfails += 1
            report("XFAIL", "kroki_flowchart_text", f"kroki render unavailable: {se.strip() or so.strip()}")
        else:
            ratio = dark_pixel_ratio(flow_png_kroki)
            if ratio < 0.01:
                xfails += 1
                report("XFAIL", "kroki_flowchart_text", f"known limitation observed (dark ratio={ratio:.4f})")
            else:
                report("PASS", "kroki_flowchart_text", f"limitation not observed (dark ratio={ratio:.4f})")

        # 3) kroki-local should preserve flowchart text using browser screenshot PNG output.
        flow_png_kroki_local = out / "arch2-kroki-local.png"
        flow_svg_kroki_local = out / "arch2-kroki-local.svg"
        rc, so, se = run_renderer(
            [
                "--backend",
                "kroki-local",
                "--input",
                str(flow_src),
                "--output",
                str(flow_png_kroki_local),
                "--scale",
                "3",
                "--keep-svg",
                str(flow_svg_kroki_local),
            ]
        )
        if rc != 0:
            failures += 1
            report("FAIL", "kroki_local_flowchart_text", f"renderer failed: {se.strip() or so.strip()}")
        else:
            ratio = dark_pixel_ratio(flow_png_kroki_local)
            if ratio < 0.01:
                failures += 1
                report("FAIL", "kroki_local_flowchart_text", f"dark ratio too low ({ratio:.4f})")
            else:
                report("PASS", "kroki_local_flowchart_text", f"dark ratio={ratio:.4f}")

        # 4) kroki-local should stay geometrically close to remote kroki on block-beta.
        block_src = CASES / "arch1-block-beta.mmd"
        block_png_kroki_local = out / "arch1-kroki-local.png"
        block_svg_kroki_local = out / "arch1-kroki-local.svg"
        rc, so, se = run_renderer(
            [
                "--backend",
                "kroki-local",
                "--input",
                str(block_src),
                "--output",
                str(block_png_kroki_local),
                "--scale",
                "3",
                "--keep-svg",
                str(block_svg_kroki_local),
            ]
        )
        if rc != 0:
            failures += 1
            report("FAIL", "kroki_local_block_beta_render", f"renderer failed: {se.strip() or so.strip()}")
        else:
            ratio = dark_pixel_ratio(block_png_kroki_local)
            if ratio < 0.01:
                failures += 1
                report("FAIL", "kroki_local_block_beta_text", f"dark ratio too low ({ratio:.4f})")
            else:
                report("PASS", "kroki_local_block_beta_text", f"dark ratio={ratio:.4f}")

        # 5) kroki sanity check for block-beta case (expected to show text).
        block_png_kroki = out / "arch1-kroki.png"
        block_svg_kroki = out / "arch1-kroki.svg"
        rc, so, se = run_renderer(
            [
                "--backend",
                "kroki",
                "--input",
                str(block_src),
                "--output",
                str(block_png_kroki),
                "--scale",
                "3",
                "--keep-svg",
                str(block_svg_kroki),
            ]
        )
        if rc != 0:
            xfails += 1
            report("XFAIL", "kroki_block_beta_text", f"kroki render unavailable: {se.strip() or so.strip()}")
        else:
            ratio = dark_pixel_ratio(block_png_kroki)
            if ratio < 0.01:
                failures += 1
                report("FAIL", "kroki_block_beta_text", f"unexpected low dark ratio ({ratio:.4f})")
            else:
                report("PASS", "kroki_block_beta_text", f"dark ratio={ratio:.4f}")

        if block_svg_kroki.exists() and block_svg_kroki_local.exists():
            _, ky, kw, kh = svg_viewbox(block_svg_kroki)
            _, ly, lw, lh = svg_viewbox(block_svg_kroki_local)
            width_delta = abs(kw - lw) / kw if kw else 1.0
            height_delta = abs(kh - lh) / kh if kh else 1.0
            y_delta = abs(ky - ly)
            if width_delta <= 0.02 and height_delta <= 0.10 and y_delta <= 10.0:
                report(
                    "PASS",
                    "kroki_local_block_beta_geometry",
                    f"width_delta={width_delta:.4f}, height_delta={height_delta:.4f}, y_delta={y_delta:.1f}",
                )
            else:
                failures += 1
                report(
                    "FAIL",
                    "kroki_local_block_beta_geometry",
                    f"width_delta={width_delta:.4f}, height_delta={height_delta:.4f}, y_delta={y_delta:.1f}",
                )

        installed_kroki_version = installed_package_version(KROKI_LOCAL_ROOT, "mermaid")
        if installed_kroki_version == expected_kroki_version:
            report("PASS", "kroki_local_mermaid_version", f"version={installed_kroki_version}")
        else:
            failures += 1
            report(
                "FAIL",
                "kroki_local_mermaid_version",
                f"expected={expected_kroki_version}, got={installed_kroki_version or 'missing'}",
            )

    print(f"Summary: FAIL={failures}, XFAIL={xfails}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
