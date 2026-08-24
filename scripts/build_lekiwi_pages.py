#!/usr/bin/env python3
"""Build the public LeKiwi guide and hardware-free diagnostics preview."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
TEMPLATE = ROOT / "src/lerobot/robots/lekiwi/templates/lekiwi_diagnostics.html"
STATIC = ROOT / "src/lerobot/robots/lekiwi/static"
MEDIA_README = ROOT / "media/readme"

DIRECTION_CONTRACT = """<!--
THESIS: Let visitors inspect a believable robot state immediately; refuse a screenshot-only product tour.
OWN-WORLD: Inherit the diagnostics app's restrained workbench UI, indigo actions, semantic health colors, and dense evidence views.
STORY: Try three synthetic hardware conditions, inspect the exact motor in the CAD twin, then run the local service to connect a real robot.
FIRST VIEWPORT: A compact simulated-data rail precedes the full operator deck, with scenario controls and the real-hardware action always visible.
FORM: Existing operator-console extension; the product UI itself is the demonstration and GitHub Pages is only its safe sample-data host.
-->"""


def build(output: Path) -> None:
    output = output.resolve()
    if output in {ROOT, SITE, STATIC, TEMPLATE.parent} or ROOT not in output.parents:
        raise ValueError(f"Refusing unsafe Pages output directory: {output}")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(SITE, output)
    shutil.copytree(STATIC, output / "static")
    shutil.copytree(MEDIA_README, output / "media/readme")

    demo_dir = output / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace(
        "<title>LeKiwi Diagnostics</title>",
        '<meta name="description" content="Try LeKiwi Diagnostics with safe synthetic motor telemetry and the real clickable CAD twin.">\n'
        '    <link rel="canonical" href="https://raunaqbn.github.io/lekiwi-lerobot/demo/">\n'
        '    <meta property="og:type" content="website">\n'
        '    <meta property="og:title" content="LeKiwi Diagnostics — Interactive Demo">\n'
        '    <meta property="og:description" content="Explore leader and follower motor health, power states, battery confidence, and the clickable LeKiwi CAD twin.">\n'
        '    <meta property="og:url" content="https://raunaqbn.github.io/lekiwi-lerobot/demo/">\n'
        '    <meta property="og:image" content="https://raunaqbn.github.io/lekiwi-lerobot/media/readme/lekiwi-diagnostics-digital-twin.jpg">\n'
        '    <meta name="twitter:card" content="summary_large_image">\n'
        "    <title>LeKiwi Diagnostics — Interactive Demo</title>",
    )
    html = html.replace(
        '<link rel="stylesheet" href="../static/lekiwi_diagnostics.css">',
        '<link rel="stylesheet" href="../static/lekiwi_diagnostics.css">\n'
        '    <link rel="stylesheet" href="./demo.css">',
    )
    html = html.replace(
        '<script type="module" src="../static/lekiwi_3d.js?v=20260810a"></script>',
        '<script src="./lekiwi_demo.js"></script>\n'
        '    <script type="module" src="../static/lekiwi_3d.js?v=20260810a"></script>',
    )
    html = html.replace(
        "<body>",
        f"""<body>\n    {DIRECTION_CONTRACT}\n    <aside class="demo-rail" aria-label="Interactive preview controls">\n      <div class="demo-rail__copy">\n        <span class="demo-flag">Interactive preview</span>\n        <span><strong>Synthetic telemetry</strong> — safe to explore; no robot is connected.</span>\n      </div>\n      <div class="demo-scenarios" role="group" aria-label="Preview a robot condition">\n        <button type="button" data-demo-scenario="healthy">All healthy</button>\n        <button type="button" data-demo-scenario="wheel" aria-pressed="true">Wheel offline</button>\n        <button type="button" data-demo-scenario="rail">Servo rail off</button>\n      </div>\n      <a class="demo-connect" href="../#connect">Connect your LeKiwi <span aria-hidden="true">→</span></a>\n    </aside>""",
        1,
    )
    html = html.replace(
        "See the workspace. Manipulate the robot.", "Preview the workspace. Inspect the robot."
    )
    html = html.replace(">All healthy</button>", ">All motors healthy</button>")
    transparent_pixel = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
    html = html.replace("/api/cameras/front/stream", transparent_pixel)
    html = html.replace("/api/cameras/wrist/stream", transparent_pixel)
    (demo_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
