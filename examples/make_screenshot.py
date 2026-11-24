"""Render docs/screenshot.png: the example drawing coloured by layer, next to its real quantities.

    pip install "dxf-takeoff[docs]"     # matplotlib
    python examples/make_screenshot.py

The drawing is rendered by ezdxf's drawing add-on; every number on the right
comes from running dxf-takeoff on the same file.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402

from dxf_takeoff import takeoff  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DXF = ROOT / "examples" / "tank_farm.dxf"
OUT = ROOT / "docs" / "screenshot.png"
INK, MUTED, RULE = "#1f2328", "#57606a", "#d0d7de"
SANS, MONO = "DejaVu Sans", "DejaVu Sans Mono"


def main() -> None:
    doc = ezdxf.readfile(DXF)
    result = takeoff(DXF, out_units="m", group_by_attribs=["SIZE"], rules=ROOT / "examples" / "takeoff.toml")

    def swatch(layer: str) -> str:
        rgb = doc.layers.get(layer).rgb
        return "#%02x%02x%02x" % rgb if rgb else "#555555"

    fig = plt.figure(figsize=(16, 8), dpi=100, facecolor="white")
    fig.text(0.012, 0.955, "examples/tank_farm.dxf", fontsize=18, color=INK, weight="bold", family=SANS)
    fig.text(0.012, 0.915, "tank-farm piping plan, coloured by layer (rendered with ezdxf)", fontsize=13,
             color=MUTED, family=SANS)
    ax = fig.add_axes((0.004, 0.0, 0.60, 0.9))
    config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                           lineweight_scaling=1.5)
    backend = MatplotlibBackend(ax, adjust_figure=False)  # keep the figure size
    Frontend(RenderContext(doc), backend, config=config).draw_layout(doc.modelspace(), finalize=True)

    panel = fig.add_axes((0.625, 0.015, 0.36, 0.97))
    panel.set_axis_off()
    panel.set_xlim(0, 1)
    panel.set_ylim(0, 1)
    y = 0.985

    def text(x: float, s: str, *, size: float = 12.5, color: str = INK, ha: str = "left",
             family: str = SANS, bold: bool = False) -> None:
        panel.text(x, y, s, fontsize=size, color=color, ha=ha, va="top", family=family,
                   weight="bold" if bold else "normal")

    def heading(s: str) -> None:
        nonlocal y
        y -= 0.022
        text(0.0, s, size=14, bold=True)
        y -= 0.045
        panel.plot([0, 1], [y + 0.006, y + 0.006], color=RULE, lw=1)
        y -= 0.006

    def row(label: str, value: str, note: str = "", color: str | None = None, bold: bool = False) -> None:
        nonlocal y
        if color:
            panel.add_patch(plt.Rectangle((0.0, y - 0.027), 0.028, 0.022, color=color, lw=0))
        text(0.045, label, family=MONO, bold=bold)
        if note:
            text(0.40, note, color=MUTED, size=11.5)
        text(1.0, value, family=MONO, ha="right", bold=bold)
        y -= 0.038

    text(0.0, "dxf-takeoff results", size=18, bold=True)
    y -= 0.045
    text(0.0, "mm drawing, reported in m and m2 (real output)", size=13, color=MUTED)
    y -= 0.03
    heading("Pipe length by layer")
    for r in result.lengths:
        if r.layer.startswith("P-"):
            row(r.layer, f"{r.length:,.3f} m" + ("~" if r.approximate else " "), color=swatch(r.layer))
    heading("Areas from hatches")
    notes = {"C-DIKE-FLOOR": "bund floor minus tanks", "A-FLOOR": "pump room floor"}
    for r in result.areas:
        if r.layer in notes:
            row(r.layer, f"{r.area:,.3f} m2 ", notes[r.layer], color=swatch(r.layer))
    heading("Valve counts by SIZE attribute")
    for r in result.blocks:
        if r.block.endswith("VALVE"):
            row(r.block, f"{r.count} ", f"DN{r.attribs.get('SIZE', '')}")
    y += 0.004
    text(0.045, "  ".join(f"{r.block} {r.count}" for r in result.blocks if not r.block.endswith("VALVE")),
         size=11.5, color=MUTED)
    y -= 0.04
    heading("Priced BOQ (examples/takeoff.toml)")
    row(f"{len(result.boq.lines)} items, incl. waste", f"{result.boq.total:,.2f} {result.boq.currency}", bold=True)
    text(0.0, "~ = spline measured by flattening.  Full table: docs/example-output.md", size=10.5, color=MUTED)

    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT, facecolor="white")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
