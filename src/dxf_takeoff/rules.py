"""BOQ rules: turn measured quantities into priced bill-of-quantities items.

A rules file (usually ``takeoff.toml``) has an optional ``[settings]`` table and
one ``[[item]]`` table per BOQ line::

    [settings]
    title = "Tank farm piping"
    currency = "USD"

    [[item]]
    code = "P-01"
    description = "Chilled water pipe DN100"
    match_layer = "P-CHW-100"     # wildcard or list of wildcards
    quantity = "length"           # length | area | perimeter | count
    unit = "m"
    waste = 5                     # percent
    rate = 12.5                   # per unit

See ``docs/boq-rules.md`` for the full reference.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import TakeoffError
from .model import match_any, natural_key
from .units import length_factor, normalize_unit, parse_area_unit

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

if TYPE_CHECKING:
    from .model import TakeoffResult

QUANTITIES = ("length", "area", "perimeter", "count")
_ITEM_KEYS = {
    "code", "description", "quantity", "match_layer", "exclude_layer", "match_block",
    "match_linetype", "where", "unit", "waste", "rate", "factor",
}
_SETTINGS_KEYS = {"title", "currency"}


@dataclass(frozen=True)
class Rule:
    """One BOQ item: which quantities it collects and how it is priced."""

    description: str
    quantity: str
    match_layer: tuple[str, ...] = ("*",)
    exclude_layer: tuple[str, ...] = ()
    match_block: tuple[str, ...] = ("*",)
    match_linetype: tuple[str, ...] = ("*",)
    where: tuple[tuple[str, tuple[str, ...]], ...] = ()
    unit: str | None = None
    waste: float = 0.0
    rate: float | None = None
    factor: float = 1.0
    code: str = ""

    def selects_layer(self, layer: str) -> bool:
        return match_any(layer, self.match_layer) and not match_any(layer, self.exclude_layer)

    def selects_block(self, block: str, layer: str, attribs: Mapping[str, str]) -> bool:
        return (
            self.selects_layer(layer)
            and match_any(block, self.match_block)
            and all(match_any(attribs.get(tag, ""), patterns) for tag, patterns in self.where)
        )


@dataclass(frozen=True)
class RuleSet:
    """All items of a rules file."""

    items: tuple[Rule, ...]
    title: str = ""
    currency: str = ""


@dataclass(frozen=True)
class BoqLine:
    """One priced line of the BOQ."""

    code: str
    description: str
    quantity: str
    net: float  # measured quantity x factor, in `unit`
    unit: str
    waste: float  # percent
    gross: float  # net quantity incl. waste
    rate: float | None
    amount: float | None
    matched: int  # number of entities / block references that matched


@dataclass(frozen=True)
class Boq:
    """Priced bill of quantities."""

    lines: tuple[BoqLine, ...]
    title: str = ""
    currency: str = ""
    not_in_boq: tuple[str, ...] = ()

    @property
    def total(self) -> float:
        return math.fsum(line.amount for line in self.lines if line.amount is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "currency": self.currency,
            "items": [asdict(line) for line in self.lines],
            "total": self.total,
            "not_in_boq": list(self.not_in_boq),
        }


def load_rules(source: str | Path | Mapping[str, Any]) -> RuleSet:
    """Load and validate a rules file (or an already parsed TOML mapping)."""
    if isinstance(source, Mapping):
        return parse_rules(source, "rules")
    path = Path(source)
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise TakeoffError(f"rules file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise TakeoffError(f"{path.name}: invalid TOML: {exc}") from None
    return parse_rules(data, path.name)


def parse_rules(data: Mapping[str, Any], origin: str = "rules") -> RuleSet:
    """Validate parsed TOML data; every mistake raises a :class:`TakeoffError` naming the item."""
    unknown = set(data) - {"settings", "item"}
    if unknown:
        raise TakeoffError(f"{origin}: unknown table(s) {', '.join(sorted(unknown))}; use [settings] and [[item]]")
    settings = data.get("settings", {})
    if not isinstance(settings, Mapping) or set(settings) - _SETTINGS_KEYS:
        raise TakeoffError(f"{origin}: [settings] may only contain {', '.join(sorted(_SETTINGS_KEYS))}")
    items = data.get("item", [])
    if not isinstance(items, list) or not items:
        raise TakeoffError(f"{origin}: no BOQ items; add [[item]] tables")
    rules = tuple(_parse_item(raw, f"{origin}: item {i}") for i, raw in enumerate(items, 1))
    return RuleSet(rules, str(settings.get("title", "")), str(settings.get("currency", "")))


def _patterns(raw: Mapping[str, Any], key: str, where: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = raw.get(key)
    if value is None:
        return default
    values = [value] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else value
    if not isinstance(values, list) or not values or not all(isinstance(v, (str, int, float)) for v in values):
        raise TakeoffError(f"{where}: {key} must be a pattern or a list of patterns")
    return tuple(str(v) for v in values)


def _number(raw: Mapping[str, Any], key: str, where: str, default: float | None) -> float | None:
    value = raw.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise TakeoffError(f"{where}: {key} must be a non-negative number, got {value!r}")
    return float(value)


def _parse_item(raw: Any, where: str) -> Rule:
    if not isinstance(raw, Mapping):
        raise TakeoffError(f"{where}: must be a table")
    unknown = set(raw) - _ITEM_KEYS
    if unknown:
        raise TakeoffError(
            f"{where}: unknown key(s) {', '.join(sorted(unknown))}; allowed: {', '.join(sorted(_ITEM_KEYS))}"
        )
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise TakeoffError(f"{where}: description is required")
    where = f"{where} ({description})"
    quantity = raw.get("quantity")
    if quantity not in QUANTITIES:
        raise TakeoffError(f"{where}: quantity must be one of {', '.join(QUANTITIES)}")
    if quantity != "count" and ("match_block" in raw or "where" in raw):
        raise TakeoffError(f"{where}: match_block and where only apply to quantity = \"count\"")
    if quantity != "length" and "match_linetype" in raw:
        raise TakeoffError(f"{where}: match_linetype only applies to quantity = \"length\"")
    conditions = raw.get("where", {})
    if not isinstance(conditions, Mapping):
        raise TakeoffError(f"{where}: where must be a table, e.g. where = {{ SIZE = \"100\" }}")
    unit = raw.get("unit")
    if unit is not None:
        if not isinstance(unit, str) or not unit.strip():
            raise TakeoffError(f"{where}: unit must be text")
        if quantity == "area":
            parse_area_unit(unit)
        elif quantity != "count":
            normalize_unit(unit)
    factor = _number(raw, "factor", where, 1.0)
    return Rule(
        description=description.strip(),
        quantity=quantity,
        match_layer=_patterns(raw, "match_layer", where, ("*",)),
        exclude_layer=_patterns(raw, "exclude_layer", where, ()),
        match_block=_patterns(raw, "match_block", where, ("*",)),
        match_linetype=_patterns(raw, "match_linetype", where, ("*",)),
        where=tuple((str(tag).upper(), _patterns(conditions, tag, where, ())) for tag in conditions),
        unit=unit.strip() if unit else None,
        waste=_number(raw, "waste", where, 0.0) or 0.0,
        rate=_number(raw, "rate", where, None),
        factor=1.0 if factor is None else factor,
        code=str(raw.get("code", "")),
    )


def _unit_factor(rule: Rule, result: TakeoffResult) -> tuple[str, float]:
    """Unit label of a BOQ line and the factor from the result units to it."""
    if rule.quantity == "count":
        return rule.unit or "nr", 1.0
    if rule.unit is None:
        return (result.area_unit if rule.quantity == "area" else result.length_unit), 1.0
    target = parse_area_unit(rule.unit) if rule.quantity == "area" else normalize_unit(rule.unit)
    if result.unit is None:
        raise TakeoffError(
            f"BOQ item {rule.description!r} is in {rule.unit}, but the drawing has no units; pass --units"
        )
    power = 2 if rule.quantity == "area" else 1
    return rule.unit, length_factor(result.unit, target) ** power


def evaluate(rule: Rule, result: TakeoffResult) -> BoqLine:
    """Collect the quantity of one rule from a takeoff result and price it."""
    if rule.quantity == "length":
        records = [r for r in result.curves
                   if rule.selects_layer(r.layer) and match_any(r.linetype, rule.match_linetype)]
        raw, matched = math.fsum(r.length for r in records), sum(r.count for r in records)
    elif rule.quantity in ("area", "perimeter"):
        shapes = [r for r in result.shapes if rule.selects_layer(r.layer)]
        raw = math.fsum(r.area if rule.quantity == "area" else r.perimeter for r in shapes)
        matched = sum(r.count for r in shapes)
    else:
        matched = sum(r.count for r in result.inserts if rule.selects_block(r.block, r.layer, dict(r.attribs)))
        raw = float(matched)
    unit, factor = _unit_factor(rule, result)
    net = raw * factor * rule.factor
    gross = net * (1.0 + rule.waste / 100.0)
    amount = None if rule.rate is None else gross * rule.rate
    return BoqLine(rule.code, rule.description, rule.quantity, net, unit, rule.waste, gross, rule.rate, amount, matched)


def apply_rules(rules: RuleSet, result: TakeoffResult) -> Boq:
    """Evaluate every rule and list what the rules did not pick up."""
    lines = tuple(evaluate(rule, result) for rule in rules.items)
    measure_rules = [r for r in rules.items if r.quantity != "count"]
    count_rules = [r for r in rules.items if r.quantity == "count"]
    layers = {r.layer for r in result.curves if r.length > 0} | {r.layer for r in result.shapes if r.area > 0}
    missing_layers = sorted((la for la in layers if not any(r.selects_layer(la) for r in measure_rules)),
                            key=natural_key)
    missing_blocks: dict[str, int] = {}
    for ins in result.inserts:
        if not any(r.selects_block(ins.block, ins.layer, dict(ins.attribs)) for r in count_rules):
            missing_blocks[ins.block] = missing_blocks.get(ins.block, 0) + ins.count
    not_in_boq = []
    if missing_layers:
        not_in_boq.append("layers " + ", ".join(missing_layers))
    if missing_blocks:
        ordered = sorted(missing_blocks.items(), key=lambda kv: natural_key(kv[0]))
        not_in_boq.append("blocks " + ", ".join(f"{b} x{n}" for b, n in ordered))
    return Boq(lines, rules.title, rules.currency, tuple(not_in_boq))
