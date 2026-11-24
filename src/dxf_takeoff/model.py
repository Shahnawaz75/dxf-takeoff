"""Result data model of a takeoff."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any

from ._version import __version__

if TYPE_CHECKING:
    from .rules import Boq


def match_any(name: str, patterns: Iterable[str]) -> bool:
    """Case-insensitive shell-style wildcard match (``*``, ``?``, ``[abc]``) against any pattern."""
    upper = name.upper()
    return any(fnmatchcase(upper, p.upper()) for p in patterns)


def natural_key(text: str) -> list:
    """Sort key that orders "P-CW-50" before "P-CW-100"."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", text)]


@dataclass(frozen=True)
class LengthRow:
    """Total length of the linear entities in one group (layer, or layer + linetype/colour)."""

    layer: str
    length: float
    entities: int
    types: dict[str, int]
    approximate: bool = False
    linetype: str | None = None
    color: str | None = None


@dataclass(frozen=True)
class AreaRow:
    """Total area (and perimeter) of the closed shapes and hatches on one layer."""

    layer: str
    area: float
    perimeter: float
    shapes: int
    types: dict[str, int]
    approximate: bool = False


@dataclass(frozen=True)
class BlockRow:
    """Number of references of one block (and attribute-value combination)."""

    block: str
    count: int
    attribs: dict[str, str] = field(default_factory=dict)
    nested: int = 0


@dataclass(frozen=True)
class CurveRecord:
    """Length of the entities sharing layer, linetype, colour and type (input for BOQ rules)."""

    layer: str
    linetype: str
    color: str
    dxftype: str
    count: int
    length: float
    approximate: bool


@dataclass(frozen=True)
class ShapeRecord:
    """Area and perimeter of the closed shapes sharing layer and type."""

    layer: str
    dxftype: str
    count: int
    area: float
    perimeter: float
    approximate: bool


@dataclass(frozen=True)
class InsertRecord:
    """References of one block with identical layer and attribute values."""

    block: str
    layer: str
    attribs: tuple[tuple[str, str], ...]
    nested: bool
    count: int


@dataclass
class TakeoffResult:
    """Quantities of one drawing layout, already converted to the report units.

    `unit` is the length unit of all quantities (``None`` when the drawing has
    no units); areas are in `unit` squared.
    """

    file: str
    layout: str
    insunits: int
    drawing_units: str | None
    unit: str | None
    scale: float
    group_by: str
    attrib_tags: tuple[str, ...]
    lengths: list[LengthRow]
    areas: list[AreaRow]
    blocks: list[BlockRow]
    curves: list[CurveRecord]
    shapes: list[ShapeRecord]
    inserts: list[InsertRecord]
    notes: list[str]
    nested: bool = False
    spline_method: str = ""
    boq: Boq | None = None

    @property
    def length_unit(self) -> str:
        """Label of the length unit; ``"du"`` (drawing units) when unknown."""
        return self.unit or "du"

    @property
    def area_unit(self) -> str:
        return f"{self.length_unit}2"

    @property
    def total_length(self) -> float:
        return math.fsum(r.length for r in self.lengths)

    @property
    def total_area(self) -> float:
        return math.fsum(r.area for r in self.areas)

    @property
    def total_blocks(self) -> int:
        return sum(r.count for r in self.blocks)

    def length(self, layer: str = "*") -> float:
        """Total length on the layers matching a wildcard pattern."""
        return math.fsum(r.length for r in self.curves if match_any(r.layer, [layer]))

    def area(self, layer: str = "*") -> float:
        """Total area on the layers matching a wildcard pattern."""
        return math.fsum(r.area for r in self.shapes if match_any(r.layer, [layer]))

    def perimeter(self, layer: str = "*") -> float:
        """Total perimeter of the closed shapes on the matching layers."""
        return math.fsum(r.perimeter for r in self.shapes if match_any(r.layer, [layer]))

    def count(self, block: str = "*", layer: str = "*", **attribs: str) -> int:
        """Number of block references; attribute filters are wildcards, e.g. ``SIZE="100"``."""
        total = 0
        for r in self.inserts:
            values = dict(r.attribs)
            if match_any(r.block, [block]) and match_any(r.layer, [layer]) and all(
                match_any(values.get(tag.upper(), ""), [str(pattern)]) for tag, pattern in attribs.items()
            ):
                total += r.count
        return total

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready representation (what ``--json`` writes)."""
        lengths = []
        for r in self.lengths:
            row: dict[str, Any] = {"layer": r.layer}
            if r.linetype is not None:
                row["linetype"] = r.linetype
            if r.color is not None:
                row["color"] = r.color
            row.update(entities=r.entities, length=r.length, approximate=r.approximate, types=r.types)
            lengths.append(row)
        return {
            "tool": "dxf-takeoff",
            "version": __version__,
            "file": self.file,
            "layout": self.layout,
            "units": {
                "insunits": self.insunits,
                "drawing": self.drawing_units,
                "length": self.length_unit,
                "area": self.area_unit,
                "scale": self.scale,
            },
            "group_by": self.group_by,
            "lengths": lengths,
            "areas": [
                {"layer": r.layer, "shapes": r.shapes, "area": r.area, "perimeter": r.perimeter,
                 "approximate": r.approximate, "types": r.types}
                for r in self.areas
            ],
            "blocks": [
                {"block": r.block, "attribs": r.attribs, "count": r.count, "nested": r.nested}
                for r in self.blocks
            ],
            "totals": {"length": self.total_length, "area": self.total_area, "blocks": self.total_blocks},
            "boq": self.boq.to_dict() if self.boq else None,
            "notes": self.notes,
        }
