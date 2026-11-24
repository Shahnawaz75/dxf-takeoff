"""Drawing units ($INSUNITS) and unit conversion."""

from __future__ import annotations

import re

from .errors import TakeoffError

#: Metres per unit for every length unit dxf-takeoff understands.
METERS: dict[str, float] = {
    "angstrom": 1e-10,
    "nm": 1e-9,
    "um": 1e-6,
    "mm": 1e-3,
    "cm": 1e-2,
    "dm": 1e-1,
    "m": 1.0,
    "dam": 10.0,
    "hm": 100.0,
    "km": 1000.0,
    "uin": 2.54e-8,
    "mil": 2.54e-5,
    "in": 0.0254,
    "ft": 0.3048,
    "us-ft": 1200.0 / 3937.0,
    "yd": 0.9144,
    "mi": 1609.344,
}

#: $INSUNITS header code -> unit name. 0 means "unitless"; codes for
#: astronomical units (17-20) are not supported.
INSUNITS: dict[int, str] = {
    1: "in", 2: "ft", 3: "mi", 4: "mm", 5: "cm", 6: "m", 7: "km", 8: "uin",
    9: "mil", 10: "yd", 11: "angstrom", 12: "nm", 13: "um", 14: "dm",
    15: "dam", 16: "hm", 21: "us-ft",
}

#: Units offered in the CLI help (any key of METERS is accepted).
COMMON_UNITS = ("mm", "cm", "m", "km", "in", "ft", "yd", "mi")

_ALIASES = {
    "millimeter": "mm", "millimetre": "mm", "millimeters": "mm", "millimetres": "mm",
    "centimeter": "cm", "centimetre": "cm", "centimeters": "cm", "centimetres": "cm",
    "meter": "m", "metre": "m", "meters": "m", "metres": "m",
    "kilometer": "km", "kilometre": "km", "kilometers": "km", "kilometres": "km",
    "micron": "um", "microns": "um", "µm": "um",
    "inch": "in", "inches": "in", '"': "in",
    "foot": "ft", "feet": "ft", "'": "ft", "survey-ft": "us-ft", "usft": "us-ft",
    "yard": "yd", "yards": "yd", "mile": "mi", "miles": "mi",
}

_AREA_RE = re.compile(r"^(?:sq\.?\s*)?(?P<unit>[a-zµ\-]+?)\s*(?P<pow>2|²|\^2)?$")


def normalize_unit(name: str) -> str:
    """Return the canonical name of a length unit, e.g. ``"Metres"`` -> ``"m"``."""
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    if key not in METERS:
        raise TakeoffError(
            f"unknown length unit {name!r}; use one of: {', '.join(COMMON_UNITS)}"
        )
    return key


def length_factor(src: str, dst: str) -> float:
    """Factor that converts a length in unit `src` to unit `dst`."""
    return METERS[src] / METERS[dst]


def parse_area_unit(name: str) -> str:
    """Return the length unit of an area unit: ``"m2"``, ``"m²"``, ``"sq ft"`` -> ``"m"``/``"ft"``."""
    text = name.strip().lower()
    match = _AREA_RE.match(text)
    if match and (match["pow"] or text.startswith("sq")):
        return normalize_unit(match["unit"])
    raise TakeoffError(f"unknown area unit {name!r}; use e.g. m2, mm2, ft2 or sq ft")


def insunits_name(code: int) -> str | None:
    """Unit name for a $INSUNITS code, or None for unitless/unsupported codes."""
    return INSUNITS.get(int(code))
