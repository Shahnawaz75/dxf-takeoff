"""The takeoff engine: read a drawing, measure every entity, aggregate the quantities."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
from ezdxf import recover
from ezdxf.document import Drawing
from ezdxf.layouts import BaseLayout

from .errors import TakeoffError
from .measure import AUTO_SPLINE_TOLERANCE, CURVE_TYPES, FILL_TYPES, UNSUPPORTED_TYPES, Measurer
from .model import (
    AreaRow,
    BlockRow,
    CurveRecord,
    InsertRecord,
    LengthRow,
    ShapeRecord,
    TakeoffResult,
    match_any,
    natural_key,
)
from .units import insunits_name, length_factor, normalize_unit
from .walker import Walker

if TYPE_CHECKING:
    from .rules import RuleSet

#: Ways to group the lengths table.
GROUP_BY = ("layer", "layer+linetype", "layer+color")


def load_drawing(source: str | Path) -> tuple[Drawing, list[str]]:
    """Read a DXF file; a damaged file is recovered when possible (noted in the result)."""
    path = Path(source)
    if not path.is_file():
        raise TakeoffError(f"file not found: {path}")
    with open(path, "rb") as fh:
        if fh.read(4) == b"AC10":
            raise TakeoffError(
                f"{path.name} is a DWG file; dxf-takeoff reads DXF only. "
                "Convert it to DXF first, e.g. with the free ODA File Converter."
            )
    try:
        return ezdxf.readfile(path), []
    except (ezdxf.DXFError, UnicodeDecodeError, ValueError):
        pass
    try:
        doc, auditor = recover.readfile(path)
    except Exception as exc:  # recover raises many types on non-DXF input
        raise TakeoffError(f"{path.name} is not a readable DXF file ({exc})") from exc
    return doc, [f"The file had structure errors and was recovered ({len(auditor.fixes)} fixes)."]


def _select_layout(doc: Drawing, name: str | None) -> BaseLayout:
    if name is None or name.lower() in ("model", "modelspace", "*model_space"):
        return doc.modelspace()
    for layout_name in doc.layouts.names():
        if layout_name.lower() == name.lower():
            return doc.layouts.get(layout_name)
    raise TakeoffError(f"layout {name!r} not found; available: {', '.join(doc.layouts.names())}")


def takeoff(
    source: str | Path | Drawing,
    *,
    units: str | None = None,
    out_units: str | None = None,
    scale: float = 1.0,
    layers: Sequence[str] | None = None,
    exclude_layers: Sequence[str] | None = None,
    include_hidden: bool = False,
    layout: str | None = None,
    group_by: str = "layer",
    group_by_attribs: Sequence[str] | None = None,
    nested: bool = False,
    block_geometry: bool = True,
    spline_tolerance: float | None = None,
    rules: str | Path | RuleSet | None = None,
) -> TakeoffResult:
    """Measure lengths, areas and block counts of one layout of a DXF drawing.

    Args:
        source: path of a DXF file, or an ezdxf ``Drawing``.
        units: drawing units, overriding ``$INSUNITS`` (``"mm"``, ``"m"``, ``"in"``, ``"ft"`` ...).
        out_units: report lengths in this unit and areas in its square.
        scale: real size = drawing size x `scale`, for drawings not drawn 1:1.
        layers: only these layers (wildcards such as ``"P-*"``, case-insensitive).
        exclude_layers: skip these layers (wildcards).
        include_hidden: also measure entities on frozen or off layers.
        layout: name of a paperspace layout; modelspace by default.
        group_by: ``"layer"``, ``"layer+linetype"`` or ``"layer+color"`` for the lengths table.
        group_by_attribs: attribute tags that split block counts, e.g. ``["SIZE"]``.
        nested: also count block references nested inside other blocks.
        block_geometry: measure the geometry inside block references (default True).
        spline_tolerance: maximum deviation of flattened splines, in drawing units.
        rules: BOQ rules file (``takeoff.toml``) or a loaded :class:`~dxf_takeoff.rules.RuleSet`.

    Raises:
        TakeoffError: unreadable file, unknown units or layout, invalid options or rules.
    """
    if group_by not in GROUP_BY:
        raise TakeoffError(f"group_by must be one of {', '.join(GROUP_BY)}")
    if not (math.isfinite(scale) and scale > 0):
        raise TakeoffError("scale must be a positive number")
    if spline_tolerance is not None and not spline_tolerance > 0:
        raise TakeoffError("spline tolerance must be a positive number")
    ruleset = None
    if rules is not None:
        from .rules import RuleSet, apply_rules, load_rules

        ruleset = rules if isinstance(rules, RuleSet) else load_rules(rules)

    if isinstance(source, Drawing):
        doc, notes = source, []
        name = Path(source.filename).name if source.filename else "<drawing>"
    else:
        doc, notes = load_drawing(source)
        name = Path(source).name

    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    drawing_units = normalize_unit(units) if units else insunits_name(insunits)
    unit = drawing_units
    factor = scale
    if out_units:
        unit = normalize_unit(out_units)
        if drawing_units is None:
            raise TakeoffError(
                f"the drawing has no units ($INSUNITS={insunits}); state what one drawing unit is "
                "with --units (Python: units=...), e.g. --units mm"
            )
        factor = scale * length_factor(drawing_units, unit)
    elif drawing_units is None:
        notes.append(f"The drawing has no units ($INSUNITS={insunits}): quantities are in drawing units (du); "
                     "use --units to state them.")

    space = _select_layout(doc, layout)
    include, exclude = list(layers or ()), list(exclude_layers or ())
    tags = tuple(t.strip().upper() for t in group_by_attribs or () if t.strip())

    walker = Walker(doc, include_hidden=include_hidden, descend=block_geometry or nested)
    measurer = Measurer(spline_tolerance)
    curves: dict[tuple[str, str, str, str], list] = {}
    shapes: dict[tuple[str, str], list] = {}
    inserts: Counter[tuple[str, str, tuple[tuple[str, str], ...], bool]] = Counter()
    unsupported: Counter[str] = Counter()
    hidden = flattened = 0

    for entity, props in walker.walk(space):
        kind = entity.dxftype()
        measurable = kind in CURVE_TYPES or kind in FILL_TYPES or kind == "INSERT"
        if (include and not match_any(props.layer, include)) or match_any(props.layer, exclude):
            continue
        if props.hidden and not include_hidden:
            hidden += measurable  # reported in the notes
            continue
        if kind == "INSERT":
            if props.depth == 0 or nested:
                key = (walker.block_name(entity), props.layer, tuple(sorted(walker.attribs(entity).items())),
                       props.depth > 0)
                inserts[key] += entity.mcount
            continue
        if props.depth > 0 and not block_geometry:
            continue
        if kind in UNSUPPORTED_TYPES:
            unsupported[kind] += 1
            continue
        if not measurable:
            continue  # text, dimensions, points ...
        measure = measurer.measure(entity, props.matrix)
        if measure is None:
            unsupported[kind] += 1
            continue
        flattened += measure.approximate
        if measure.length is not None:
            acc = curves.setdefault((props.layer, props.linetype, props.color, kind), [0, 0.0, False])
            acc[0] += 1
            acc[1] += measure.length
            acc[2] |= measure.approximate
        if measure.area is not None:
            acc = shapes.setdefault((props.layer, kind), [0, 0.0, 0.0, False])
            acc[0] += 1
            acc[1] += measure.area
            acc[2] += measure.perimeter
            acc[3] |= measure.approximate

    curve_records = [
        CurveRecord(layer, lt, color, kind, n, length * factor, approx)
        for (layer, lt, color, kind), (n, length, approx) in curves.items()
    ]
    shape_records = [
        ShapeRecord(layer, kind, n, area * factor * factor, perimeter * factor, approx)
        for (layer, kind), (n, area, perimeter, approx) in shapes.items()
    ]
    insert_records = [InsertRecord(block, layer, attrs, is_nested, n)
                      for (block, layer, attrs, is_nested), n in inserts.items()]

    tolerance = (f"{_g(AUTO_SPLINE_TOLERANCE)} x spline size" if spline_tolerance is None
                 else f"{_g(spline_tolerance)} drawing units")
    spline_method = f"flattened, max deviation {tolerance}"
    if flattened:
        notes.append(f"{_entities(flattened)} with splines measured by flattening (max deviation {tolerance}); "
                     "rows marked ~ are approximate.")
    if hidden:
        notes.append(f"{_entities(hidden)} on frozen or off layers skipped (use --include-hidden to include them).")
    if unsupported:
        listed = ", ".join(f"{k} x{n}" for k, n in sorted(unsupported.items()))
        notes.append(f"Not measured (no length/area support): {listed}.")
    notes.extend(sorted(walker.notes))
    blocks = _block_rows(insert_records, tags)
    anonymous = sorted({r.block for r in blocks if r.block.startswith("*")})
    if anonymous:
        notes.append(f"Anonymous blocks not resolved to a dynamic block name: {', '.join(anonymous)}.")

    result = TakeoffResult(
        file=name,
        layout=space.name,
        insunits=insunits,
        drawing_units=drawing_units,
        unit=unit,
        scale=scale,
        group_by=group_by,
        attrib_tags=tags,
        lengths=_length_rows(curve_records, group_by),
        areas=_area_rows(shape_records),
        blocks=blocks,
        curves=curve_records,
        shapes=shape_records,
        inserts=insert_records,
        notes=notes,
        nested=nested,
        spline_method=spline_method if flattened else "",
    )
    if ruleset is not None:
        result.boq = apply_rules(ruleset, result)
    return result


def _g(value: float) -> str:
    """Compact number: 1e-06 -> 1e-6, 0.5 -> 0.5."""
    return f"{value:g}".replace("e-0", "e-").replace("e+0", "e+")


def _entities(n: int) -> str:
    return f"{n} {'entity' if n == 1 else 'entities'}"


def _length_rows(records: list[CurveRecord], group_by: str) -> list[LengthRow]:
    groups: dict[tuple, list] = {}
    for r in records:
        key = (
            r.layer,
            r.linetype if group_by == "layer+linetype" else None,
            r.color if group_by == "layer+color" else None,
        )
        acc = groups.setdefault(key, [0, 0.0, Counter(), False])
        acc[0] += r.count
        acc[1] += r.length
        acc[2][r.dxftype] += r.count
        acc[3] |= r.approximate
    rows = [
        LengthRow(layer, length, n, dict(sorted(types.items())), approx, lt, color)
        for (layer, lt, color), (n, length, types, approx) in groups.items()
    ]
    return sorted(rows, key=lambda r: (natural_key(r.layer), r.linetype or "", natural_key(r.color or "")))


def _area_rows(records: list[ShapeRecord]) -> list[AreaRow]:
    groups: dict[str, list] = {}
    for r in records:
        acc = groups.setdefault(r.layer, [0, 0.0, 0.0, Counter(), False])
        acc[0] += r.count
        acc[1] += r.area
        acc[2] += r.perimeter
        acc[3][r.dxftype] += r.count
        acc[4] |= r.approximate
    rows = [
        AreaRow(layer, area, perimeter, n, dict(sorted(types.items())), approx)
        for layer, (n, area, perimeter, types, approx) in groups.items()
    ]
    return sorted(rows, key=lambda r: natural_key(r.layer))


def _block_rows(records: list[InsertRecord], tags: tuple[str, ...]) -> list[BlockRow]:
    counts: Counter[tuple] = Counter()
    nested: Counter[tuple] = Counter()
    for r in records:
        values = dict(r.attribs)
        key = (r.block, tuple(values.get(t, "") for t in tags))
        counts[key] += r.count
        if r.nested:
            nested[key] += r.count
    rows = [BlockRow(block, n, dict(zip(tags, values)), nested[(block, values)])
            for (block, values), n in counts.items()]
    return sorted(rows, key=lambda r: (natural_key(r.block), [natural_key(v) for v in r.attribs.values()]))
