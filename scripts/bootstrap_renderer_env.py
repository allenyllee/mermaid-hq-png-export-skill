#!/usr/bin/env python3
import json
import pathlib
import sys

import render_mermaid_png as renderer


def package_version(module_root: pathlib.Path, package_name: str) -> str | None:
    package_path = module_root / "node_modules" / package_name / "package.json"
    if not package_path.exists():
        return None
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = data.get("version")
    return version if isinstance(version, str) else None


def main() -> int:
    if not renderer.install_local_node():
        print("Bootstrap failed: could not install or locate Node.js.", file=sys.stderr)
        return 1

    if not renderer.install_mmdc():
        print("Bootstrap failed: could not install or locate `mmdc`.", file=sys.stderr)
        return 1

    chrome_path = renderer.resolve_chromium()
    if chrome_path is None:
        print(
            "Bootstrap failed: could not locate Chromium/Chrome for `kroki-local`.",
            file=sys.stderr,
        )
        return 1

    if not renderer.install_kroki_local():
        print("Bootstrap failed: could not install `kroki-local` dependencies.", file=sys.stderr)
        return 1

    node, npm = renderer.resolve_node_tools()
    mmdc = renderer.resolve_mmdc()
    mermaid_version = package_version(renderer.LOCAL_KROKI_LOCAL_ROOT, "mermaid")
    pptr_version = package_version(renderer.LOCAL_KROKI_LOCAL_ROOT, "puppeteer-core")

    print("Bootstrap complete")
    print(f"Node: {node or 'missing'}")
    print(f"npm: {npm or 'missing'}")
    print(f"mmdc: {mmdc or 'missing'}")
    print(f"Chrome: {chrome_path}")
    print(f"kroki-local mermaid: {mermaid_version or 'missing'}")
    print(f"kroki-local puppeteer-core: {pptr_version or 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
