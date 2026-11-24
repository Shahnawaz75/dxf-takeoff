"""Command line interface: ``dxf-takeoff plan.dxf --out-units m --xlsx takeoff.xlsx``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ._version import __version__
from .core import GROUP_BY, takeoff
from .errors import TakeoffError
from .report import format_text, to_json, write_csv
from .units import COMMON_UNITS


def _patterns(values: list[str] | None) -> list[str]:
    """Repeatable options that may also hold comma-separated patterns."""
    return [p.strip() for v in values or [] for p in v.split(",") if p.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dxf-takeoff",
        description="Quantity takeoff from DXF drawings: lengths by layer, areas of closed "
                    "polylines and hatches, block counts by attribute, and a priced BOQ.",
        epilog="Exit codes: 0 success, 2 error. Docs: https://shahnawaz75.github.io/dxf-takeoff/",
    )
    p.add_argument("dxf", help="DXF file to measure (convert DWG files to DXF first)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    q = p.add_argument_group("quantities")
    q.add_argument("--group-by", choices=GROUP_BY, default="layer",
                   help="grouping of the lengths table (default: layer)")
    q.add_argument("--group-by-attrib", metavar="TAGS", action="append",
                   help="split block counts by attribute values, e.g. SIZE or TAG,SIZE")
    q.add_argument("--nested", action="store_true", help="also count block references nested in other blocks")
    q.add_argument("--perimeter", action="store_true", help="show perimeters in the areas table")
    q.add_argument("--no-block-geometry", action="store_true",
                   help="do not measure geometry inside block references (blocks are still counted)")
    q.add_argument("--spline-tolerance", type=float, metavar="D",
                   help="max deviation when flattening splines, in drawing units (default: 1e-6 x spline size)")

    u = p.add_argument_group("units")
    u.add_argument("--units", metavar="UNIT", help=f"drawing units, overrides $INSUNITS ({'|'.join(COMMON_UNITS)})")
    u.add_argument("--out-units", metavar="UNIT", help="report lengths in UNIT and areas in UNIT2, e.g. m")
    u.add_argument("--scale", type=float, default=1.0, help="real size = drawing size x SCALE (default 1)")

    f = p.add_argument_group("filters")
    f.add_argument("--layer", action="append", metavar="PATTERN",
                   help='only these layers, wildcards allowed: "P-*" (repeatable)')
    f.add_argument("--exclude-layer", action="append", metavar="PATTERN", help="skip these layers (repeatable)")
    f.add_argument("--include-hidden", action="store_true", help="include entities on frozen and off layers")
    f.add_argument("--layout", metavar="NAME", help="paperspace layout to measure (default: modelspace)")

    o = p.add_argument_group("BOQ and output")
    o.add_argument("--rules", metavar="TOML", help="BOQ rules file that prices the quantities (takeoff.toml)")
    o.add_argument("--csv", metavar="DIR", help="write lengths.csv, areas.csv, blocks.csv and boq.csv to DIR")
    o.add_argument("--xlsx", metavar="FILE", help="write an Excel workbook (needs dxf-takeoff[xlsx])")
    o.add_argument("--json", metavar="FILE", help="write JSON to FILE ('-' for stdout)")
    o.add_argument("--decimals", type=int, default=3, help="decimals in the terminal table (default 3)")
    o.add_argument("-q", "--quiet", action="store_true", help="do not print the terminal table")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; returns the process exit code (0 ok, 2 error)."""
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # layer names the console cannot encode
    try:
        result = takeoff(
            args.dxf,
            units=args.units,
            out_units=args.out_units,
            scale=args.scale,
            layers=_patterns(args.layer),
            exclude_layers=_patterns(args.exclude_layer),
            include_hidden=args.include_hidden,
            layout=args.layout,
            group_by=args.group_by,
            group_by_attribs=_patterns(args.group_by_attrib),
            nested=args.nested,
            block_geometry=not args.no_block_geometry,
            spline_tolerance=args.spline_tolerance,
            rules=args.rules,
        )
        if args.csv:
            write_csv(result, args.csv)
        if args.xlsx:
            from .excel import write_xlsx

            write_xlsx(result, args.xlsx)
        if args.json == "-":
            sys.stdout.write(to_json(result))
        elif args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                fh.write(to_json(result))
    except TakeoffError as exc:
        print(f"dxf-takeoff: error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"dxf-takeoff: error: {exc}", file=sys.stderr)
        return 2
    if not args.quiet and args.json != "-":
        sys.stdout.write(format_text(result, perimeter=args.perimeter, decimals=max(0, args.decimals)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
