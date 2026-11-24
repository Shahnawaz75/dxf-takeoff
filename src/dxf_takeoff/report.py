"""Plain-text, CSV and JSON reports of a takeoff result."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path

from ._version import __version__
from .model import TakeoffResult


def _num(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]], align: str,
           total: Sequence[str] | None = None) -> list[str]:
    """Format an aligned text table; `align` has one ``l``/``r`` per column."""
    body = [list(r) for r in rows] + ([list(total)] if total else [])
    widths = [max([len(h)] + [len(r[i]) for r in body]) for i, h in enumerate(headers)]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(c.ljust(w) if a == "l" else c.rjust(w) for c, w, a in zip(cells, widths, align)).rstrip()

    rule = line(["-" * w for w in widths])
    out = [line(headers), rule] + [line(r) for r in rows]
    if total:
        out += [rule, line(total)]
    return out


def _units_line(result: TakeoffResult) -> str:
    if result.drawing_units:
        drawing = f"{result.drawing_units} ($INSUNITS={result.insunits})"
    else:
        drawing = f"none ($INSUNITS={result.insunits})"
    return (f"Units: drawing {drawing} -> report {result.length_unit} / {result.area_unit}, "
            f"scale {result.scale:g}")


def format_text(result: TakeoffResult, *, perimeter: bool = False, decimals: int = 3) -> str:
    """Human-readable report: lengths, areas, blocks, BOQ and notes."""
    lu, au = result.length_unit, result.area_unit
    out = [f"dxf-takeoff {__version__} | {result.file} | layout {result.layout}", _units_line(result), ""]

    out.append(f"LENGTHS BY {result.group_by.upper()}")
    if result.lengths:
        extra = {"layer+linetype": ["Linetype"], "layer+color": ["Color"]}.get(result.group_by, [])
        rows = []
        for r in result.lengths:
            cells = [r.layer] + ([r.linetype or ""] if r.linetype is not None else []) + (
                [r.color or ""] if r.color is not None else [])
            rows.append(cells + [str(r.entities), _num(r.length, decimals) + ("~" if r.approximate else " ")])
        total = ["Total"] + [""] * len(extra) + [str(sum(r.entities for r in result.lengths)),
                                                 _num(result.total_length, decimals) + " "]
        out += _table(["Layer", *extra, "Entities", f"Length [{lu}] "], rows, "l" * (1 + len(extra)) + "rr", total)
    else:
        out.append("(no lines, arcs, polylines or splines)")
    out.append("")

    out.append("AREAS BY LAYER")
    if result.areas:
        headers = ["Layer", "Shapes", f"Area [{au}] "] + ([f"Perimeter [{lu}]"] if perimeter else [])
        rows = [[r.layer, str(r.shapes), _num(r.area, decimals) + ("~" if r.approximate else " ")]
                + ([_num(r.perimeter, decimals)] if perimeter else []) for r in result.areas]
        total = ["Total", str(sum(r.shapes for r in result.areas)), _num(result.total_area, decimals) + " "] + (
            [_num(sum(r.perimeter for r in result.areas), decimals)] if perimeter else [])
        out += _table(headers, rows, "lrrr", total)
    else:
        out.append("(no closed shapes or hatches)")
    out.append("")

    out.append("BLOCKS")
    if result.blocks:
        tags = list(result.attrib_tags)
        headers = ["Block", *tags, "Count"] + (["Nested"] if result.nested else [])
        rows = [[r.block, *(r.attribs.get(t, "") or "-" for t in tags), str(r.count)]
                + ([str(r.nested)] if result.nested else []) for r in result.blocks]
        total = ["Total", *([""] * len(tags)), str(result.total_blocks)] + (
            [str(sum(r.nested for r in result.blocks))] if result.nested else [])
        out += _table(headers, rows, "l" * (1 + len(tags)) + "rr", total)
    else:
        out.append("(no block references)")

    boq = result.boq
    if boq is not None:
        cur = f" [{boq.currency}]" if boq.currency else ""
        out += ["", "BOQ" + (f" - {boq.title}" if boq.title else "")]
        rows = []
        for i, line in enumerate(boq.lines, 1):
            count = line.quantity == "count"
            fmt = (lambda v: f"{v:,.0f}") if count and line.waste == 0 else (lambda v: _num(v, decimals))
            rows.append([
                line.code or str(i), line.description, fmt(line.net), line.unit, f"{line.waste:g}",
                fmt(line.gross), "" if line.rate is None else _num(line.rate, 2),
                "" if line.amount is None else _num(line.amount, 2),
            ])
        total = ["", "Total", "", "", "", "", "", _num(boq.total, 2)]
        out += _table(["Item", "Description", "Qty", "Unit", "Waste %", "Qty+waste", f"Rate{cur}",
                       f"Amount{cur}"], rows, "llrlrrrr", total)
        if boq.not_in_boq:
            out.append("Not in the BOQ: " + "; ".join(boq.not_in_boq))

    if result.notes:
        out += ["", "Notes:"] + [f"- {n}" for n in result.notes]
    return "\n".join(out) + "\n"


def to_json(result: TakeoffResult) -> str:
    """JSON document with all tables, totals, BOQ and notes."""
    return json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n"


def write_csv(result: TakeoffResult, directory: str | Path) -> list[Path]:
    """Write lengths.csv, areas.csv, blocks.csv (and boq.csv with rules) into `directory`."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    lu, au = result.length_unit, result.area_unit
    by_lt, by_color = result.group_by == "layer+linetype", result.group_by == "layer+color"

    def types(d: dict[str, int]) -> str:
        return ";".join(f"{k}:{v}" for k, v in d.items())

    tables: dict[str, tuple[list[str], list[list[object]]]] = {
        "lengths.csv": (
            ["layer"] + (["linetype"] if by_lt else []) + (["color"] if by_color else [])
            + ["entities", f"length_{lu}", "approximate", "types"],
            [[r.layer] + ([r.linetype] if by_lt else []) + ([r.color] if by_color else [])
             + [r.entities, f"{r.length:.6f}", r.approximate, types(r.types)] for r in result.lengths],
        ),
        "areas.csv": (
            ["layer", "shapes", f"area_{au}", f"perimeter_{lu}", "approximate", "types"],
            [[r.layer, r.shapes, f"{r.area:.6f}", f"{r.perimeter:.6f}", r.approximate, types(r.types)]
             for r in result.areas],
        ),
        "blocks.csv": (
            ["block", *(t.lower() for t in result.attrib_tags), "count", "nested"],
            [[r.block, *(r.attribs.get(t, "") for t in result.attrib_tags), r.count, r.nested]
             for r in result.blocks],
        ),
    }
    if result.boq is not None:
        tables["boq.csv"] = (
            ["code", "description", "quantity", "unit", "net", "waste_pct", "gross", "rate", "amount"],
            [[ln.code, ln.description, ln.quantity, ln.unit, f"{ln.net:.6f}", ln.waste, f"{ln.gross:.6f}",
              "" if ln.rate is None else ln.rate, "" if ln.amount is None else f"{ln.amount:.2f}"]
             for ln in result.boq.lines],
        )
    written = []
    for name, (header, rows) in tables.items():
        path = folder / name
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
        written.append(path)
    return written
