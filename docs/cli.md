---
title: dxf-takeoff command line reference
description: All options of the dxf-takeoff command - grouping, attribute counts, units, scale, layer filters, BOQ rules and Excel, CSV and JSON output.
---

# Command line reference

```
dxf-takeoff [options] DXF
```

```text
usage: dxf-takeoff [-h] [--version] [--group-by {layer,layer+linetype,layer+color}]
                   [--group-by-attrib TAGS] [--nested] [--perimeter] [--no-block-geometry]
                   [--spline-tolerance D] [--units UNIT] [--out-units UNIT] [--scale SCALE]
                   [--layer PATTERN] [--exclude-layer PATTERN] [--include-hidden] [--layout NAME]
                   [--rules TOML] [--csv DIR] [--xlsx FILE] [--json FILE] [--decimals DECIMALS]
                   [-q]
                   dxf

Quantity takeoff from DXF drawings: lengths by layer, areas of closed polylines and hatches, block
counts by attribute, and a priced BOQ.

positional arguments:
  dxf                   DXF file to measure (convert DWG files to DXF first)

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit

quantities:
  --group-by {layer,layer+linetype,layer+color}
                        grouping of the lengths table (default: layer)
  --group-by-attrib TAGS
                        split block counts by attribute values, e.g. SIZE or TAG,SIZE
  --nested              also count block references nested in other blocks
  --perimeter           show perimeters in the areas table
  --no-block-geometry   do not measure geometry inside block references (blocks are still counted)
  --spline-tolerance D  max deviation when flattening splines, in drawing units (default: 1e-6 x
                        spline size)

units:
  --units UNIT          drawing units, overrides $INSUNITS (mm|cm|m|km|in|ft|yd|mi)
  --out-units UNIT      report lengths in UNIT and areas in UNIT2, e.g. m
  --scale SCALE         real size = drawing size x SCALE (default 1)

filters:
  --layer PATTERN       only these layers, wildcards allowed: "P-*" (repeatable)
  --exclude-layer PATTERN
                        skip these layers (repeatable)
  --include-hidden      include entities on frozen and off layers
  --layout NAME         paperspace layout to measure (default: modelspace)

BOQ and output:
  --rules TOML          BOQ rules file that prices the quantities (takeoff.toml)
  --csv DIR             write lengths.csv, areas.csv, blocks.csv and boq.csv to DIR
  --xlsx FILE           write an Excel workbook (needs dxf-takeoff[xlsx])
  --json FILE           write JSON to FILE ('-' for stdout)
  --decimals DECIMALS   decimals in the terminal table (default 3)
  -q, --quiet           do not print the terminal table

Exit codes: 0 success, 2 error. Docs: https://shahnawaz75.github.io/dxf-takeoff/
```

## Notes on the options

- `--layer` and `--exclude-layer` can be repeated and also accept comma-separated patterns:
  `--layer "P-CW-*,P-FW-*"`. Matching is case-insensitive.
- Layer filters apply to the *effective* layer: an entity on layer `0` inside a block counts on the
  block reference's layer.
- Entities on frozen or off layers are skipped and counted in the notes; `--include-hidden` measures
  them. A block reference on a frozen layer hides its whole content; one on an off layer hides only
  its layer-0 content (the way AutoCAD displays it).
- `--group-by-attrib` takes attribute tags (case-insensitive). References without the attribute are
  shown with `-`.
- `--scale` multiplies lengths by the factor and areas by its square, before unit conversion.
- `--json -` prints only JSON, so the output can be piped into other tools.
- Errors (missing file, DWG instead of DXF, unknown unit or layout, invalid rules) print a message
  to stderr and exit with code 2.

## Python equivalent

Every option has a keyword argument in `dxf_takeoff.takeoff()`:

| CLI | Python |
| --- | --- |
| `--group-by` | `group_by="layer+linetype"` |
| `--group-by-attrib SIZE` | `group_by_attribs=["SIZE"]` |
| `--nested` | `nested=True` |
| `--no-block-geometry` | `block_geometry=False` |
| `--spline-tolerance 0.5` | `spline_tolerance=0.5` |
| `--units mm` / `--out-units m` / `--scale 50` | `units="mm"`, `out_units="m"`, `scale=50` |
| `--layer` / `--exclude-layer` | `layers=[...]`, `exclude_layers=[...]` |
| `--include-hidden` / `--layout NAME` | `include_hidden=True`, `layout="NAME"` |
| `--rules takeoff.toml` | `rules="takeoff.toml"` |
| `--csv` / `--json` | `dxf_takeoff.report.write_csv(result, dir)`, `result.to_dict()` |
| `--xlsx` | `dxf_takeoff.excel.write_xlsx(result, path)` |
