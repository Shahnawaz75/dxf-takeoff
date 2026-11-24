"""dxf-takeoff: quantity takeoff from DXF drawings.

Lengths by layer, areas of closed shapes and hatches, block counts (optionally
split by attribute values) and a priced BOQ, unit-aware and exact.

>>> from dxf_takeoff import takeoff
>>> result = takeoff("plan.dxf", out_units="m")          # doctest: +SKIP
>>> result.length("P-CW-*"), result.count("GATE-VALVE", SIZE="100")  # doctest: +SKIP
"""

from ._version import __version__
from .core import load_drawing, takeoff
from .errors import TakeoffError
from .model import AreaRow, BlockRow, LengthRow, TakeoffResult
from .rules import Boq, BoqLine, Rule, RuleSet, apply_rules, load_rules

__all__ = [
    "__version__",
    "takeoff",
    "load_drawing",
    "TakeoffError",
    "TakeoffResult",
    "LengthRow",
    "AreaRow",
    "BlockRow",
    "Rule",
    "RuleSet",
    "Boq",
    "BoqLine",
    "load_rules",
    "apply_rules",
]
