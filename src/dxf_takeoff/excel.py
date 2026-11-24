"""Excel workbook output (needs the optional ``openpyxl`` dependency: ``pip install "dxf-takeoff[xlsx]"``).

Sheets: Summary, Lengths, Areas, Blocks and BOQ.  Totals are real ``=SUM()``
formulas and the BOQ amounts are ``quantity x rate`` formulas, so an
estimator can change rates or waste factors in Excel and the totals follow.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ._version import __version__
from .errors import TakeoffError
from .model import TakeoffResult

QTY = "#,##0.000"
INT = "#,##0"
MONEY = "#,##0.00"


def write_xlsx(result: TakeoffResult, path: str | Path) -> Path:
    """Write the takeoff (and BOQ) to an .xlsx workbook."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.workbook.properties import CalcProperties
    except ImportError:
        raise TakeoffError('Excel output needs openpyxl: pip install "dxf-takeoff[xlsx]"') from None

    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")
    bold = Font(bold=True)
    wb = Workbook()
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    lu, au = result.length_unit, result.area_unit

    def method(approximate: bool) -> str:
        return "approx. (spline flattened)" if approximate else "exact"

    def sheet(title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]], formats: Sequence[str | None],
              sums: Sequence[int] = ()):
        """Add a formatted table sheet; returns it and the row number of its totals."""
        ws = wb.create_sheet(title)
        ws.append(list(headers))
        for cell in ws[1]:
            cell.font, cell.fill = head_font, head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in rows:
            ws.append(list(row))
        last = ws.max_row
        if sums:
            ws.cell(last + 1, 1, "Total").font = bold
            for col in sums:
                letter = get_column_letter(col)
                formula = f"=SUM({letter}2:{letter}{last})" if last >= 2 else 0
                ws.cell(last + 1, col, formula).font = bold
        for col, fmt in enumerate(formats, 1):
            if fmt:
                for (cell,) in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                    cell.number_format = fmt
        for col in range(1, len(headers) + 1):
            values = [f"{c.value:,.3f}" if isinstance(c.value, float) else str(c.value)
                      for (c,) in ws.iter_rows(min_col=col, max_col=col) if c.value is not None]
            longest = max((len(v) for v in values if not v.startswith("=")), default=8)
            ws.column_dimensions[get_column_letter(col)].width = min(max(longest + 2, 10), 60)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(last, 1)}"
        return ws, last + 1

    summary = wb.active
    summary.title = "Summary"

    by_lt, by_color = result.group_by == "layer+linetype", result.group_by == "layer+color"
    extra = (["Linetype"] if by_lt else []) + (["Color"] if by_color else [])
    rows = [[r.layer] + ([r.linetype] if by_lt else []) + ([r.color] if by_color else [])
            + [r.entities, r.length, ", ".join(f"{k} x{v}" for k, v in r.types.items()), method(r.approximate)]
            for r in result.lengths]
    n = 1 + len(extra)
    _, len_total = sheet("Lengths", ["Layer", *extra, "Entities", f"Length [{lu}]", "Entity types", "Method"],
                         rows, [None] * n + [INT, QTY], sums=[n + 1, n + 2])

    rows = [[r.layer, r.shapes, r.area, r.perimeter, ", ".join(f"{k} x{v}" for k, v in r.types.items()),
             method(r.approximate)] for r in result.areas]
    _, area_total = sheet("Areas", ["Layer", "Shapes", f"Area [{au}]", f"Perimeter [{lu}]", "Entity types", "Method"],
                          rows, [None, INT, QTY, QTY], sums=[2, 3, 4])

    tags = list(result.attrib_tags)
    rows = [[r.block, *(r.attribs.get(t, "") for t in tags), r.count] + ([r.nested] if result.nested else [])
            for r in result.blocks]
    count_col = len(tags) + 2
    _, block_total = sheet("Blocks", ["Block", *tags, "Count"] + (["Nested"] if result.nested else []), rows,
                           [None] * (len(tags) + 1) + [INT] * (2 if result.nested else 1),
                           sums=[count_col] + ([count_col + 1] if result.nested else []))

    boq = result.boq
    cur = f" [{boq.currency}]" if boq and boq.currency else ""
    boq_rows = []
    for i, line in enumerate(boq.lines if boq else (), 2):
        boq_rows.append([
            line.code or str(i - 1), line.description, line.net, line.unit, line.waste,
            f"=C{i}*(1+E{i}/100)", line.rate, f'=IF(ISNUMBER(G{i}),F{i}*G{i},"")',
        ])
    ws_boq, boq_total = sheet("BOQ", ["Item", "Description", "Qty", "Unit", "Waste %", "Qty incl. waste",
                                      f"Rate{cur}", f"Amount{cur}"],
                              boq_rows, [None, None, QTY, None, "0.0", QTY, MONEY, MONEY], sums=[8] if boq else ())
    if boq is None:
        ws_boq.append(["No BOQ rules given. Run with --rules takeoff.toml to price the quantities."])
    else:
        for i, line in enumerate(boq.lines, 2):
            if line.quantity == "count":
                ws_boq.cell(i, 3).number_format = INT
                if line.waste == 0:
                    ws_boq.cell(i, 6).number_format = INT
        for letter in "CFH":
            ws_boq.column_dimensions[letter].width = 16
        if boq.not_in_boq:
            ws_boq.cell(boq_total + 2, 1, "Not in the BOQ: " + "; ".join(boq.not_in_boq))

    summary.append(["dxf-takeoff quantity report"])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append([])
    for label, value in [
        ("File", result.file),
        ("Layout", result.layout),
        ("Drawing units", f"{result.drawing_units or 'none'} ($INSUNITS={result.insunits})"),
        ("Report units", f"{lu} / {au}"),
        ("Scale", result.scale),
        ("Generated by", f"dxf-takeoff {__version__}"),
    ]:
        summary.append([label, value])
    summary.append([])
    totals = [
        (f"Total length [{lu}]", f"=Lengths!{get_column_letter(n + 2)}{len_total}", QTY),
        (f"Total area [{au}]", f"=Areas!C{area_total}", QTY),
        ("Block references", f"=Blocks!{get_column_letter(count_col)}{block_total}", INT),
    ]
    if boq is not None:
        totals.append((f"BOQ total{cur}", f"=BOQ!H{boq_total}", MONEY))
    for label, formula, fmt in totals:
        summary.append([label, formula])
        summary.cell(summary.max_row, 1).font = bold
        summary.cell(summary.max_row, 2).number_format = fmt
    if result.notes:
        summary.append([])
        summary.append(["Notes"])
        summary.cell(summary.max_row, 1).font = bold
        for note in result.notes:
            summary.append([note])
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 34

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
