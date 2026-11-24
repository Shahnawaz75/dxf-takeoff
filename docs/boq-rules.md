---
title: BOQ rules file reference (takeoff.toml)
description: How to map DXF layers and blocks to priced bill of quantities items with dxf-takeoff - quantity types, units, waste factors, unit rates, attribute filters and wildcards.
---

# BOQ rules file (`takeoff.toml`)

A rules file turns the measured quantities into a priced bill of quantities (BOQ) or material
takeoff (MTO). It is a [TOML](https://toml.io) file with an optional `[settings]` table and one
`[[item]]` table per BOQ line.

```bash
dxf-takeoff plan.dxf --out-units m --rules takeoff.toml --xlsx boq.xlsx
```

```python
from dxf_takeoff import takeoff
result = takeoff("plan.dxf", out_units="m", rules="takeoff.toml")
print(result.boq.total)
```

A complete, commented example is [`examples/takeoff.toml`](https://github.com/Shahnawaz75/dxf-takeoff/blob/main/examples/takeoff.toml).

## `[settings]`

| Key | Type | Meaning |
| --- | --- | --- |
| `title` | text | Shown above the BOQ table. |
| `currency` | text | Shown in the rate and amount headers, e.g. `"USD"`, `"EUR"`, `"PKR"`. |

## `[[item]]`

| Key | Required | Applies to | Meaning |
| --- | --- | --- | --- |
| `description` | yes | all | Text of the BOQ line. |
| `quantity` | yes | all | `"length"`, `"area"`, `"perimeter"` or `"count"`. |
| `code` | no | all | Item number, e.g. `"1.01"`. Defaults to the position in the file. |
| `match_layer` | no | all | Layer pattern or list of patterns. Default `"*"` (all layers). |
| `exclude_layer` | no | all | Layer pattern(s) to leave out. |
| `match_block` | no | count | Block name pattern(s), matched against the effective name (dynamic blocks resolved). Default `"*"`. |
| `where` | no | count | Attribute filters, e.g. `where = { SIZE = "100", TYPE = "FL*" }`. All must match. |
| `match_linetype` | no | length | Linetype pattern(s), after BYLAYER/BYBLOCK resolution. |
| `unit` | no | all | Unit of the BOQ line, see below. |
| `waste` | no | all | Waste or allowance in percent; added to the measured quantity. Default 0. |
| `rate` | no | all | Unit rate. Without a rate the line has a quantity but no amount. |
| `factor` | no | all | Plain multiplier applied after unit conversion, e.g. `2` for two coats. Default 1. |

Unknown keys are rejected with an error that names the item, so a typo such as `wastage = 5`
cannot silently drop your waste factor.

### Quantities

- **length**: total length of lines, arcs, circles, polylines, splines and MLINEs on the matching
  layers (including the geometry inside blocks, like the lengths table).
- **area**: total area of closed shapes and hatches on the matching layers.
- **perimeter**: total perimeter of those closed shapes and hatches (hatch perimeters include
  the edges of holes).
- **count**: number of block references (MINSERT arrays count every instance; nested blocks only
  when the takeoff runs with `--nested`).

### Units

- **length / perimeter**: any length unit: `mm`, `cm`, `m`, `km`, `in`, `ft`, `yd`, `mi`.
- **area**: a square unit: `m2`, `m²`, `mm2`, `ft2`, `sq ft`, `sqm` ...
- **count**: any label, e.g. `nr`, `ea`, `pcs`, `set`. Default `nr`.

Quantities are converted from the takeoff units, so a drawing in millimetres can be priced per metre
or per square metre without `--out-units`. If the drawing has no units (`$INSUNITS = 0`), pass
`--units` so dxf-takeoff knows what to convert from. Without a `unit`, the item uses the report units.

### Patterns

Patterns are case-insensitive shell-style wildcards: `*` (anything), `?` (one character) and `[abc]`
(one of the characters). Examples: `"P-CW-*"`, `["P-CW-100", "P-CW-50"]`, `"WALL-??"`.

### Waste, rate and amount

```
quantity incl. waste = measured quantity x factor x (1 + waste / 100)
amount               = quantity incl. waste x rate
```

In the Excel output both columns are formulas, so changing a rate or waste percentage in Excel
updates the line and the total.

## What is not in the BOQ

After the BOQ table dxf-takeoff prints a line such as

```
Not in the BOQ: layers SYMBOL; blocks PUMP x3
```

It lists layers that have lengths or areas but are not matched by any length, area or perimeter
item, and block references that no count item matched (with the number of references). Use it as a
checklist before you send the estimate.

## Example

```toml
[settings]
title = "Office fit-out, level 2"
currency = "EUR"

[[item]]
code = "E.01"
description = "Cable tray 300 mm"
match_layer = "E-TRAY-300"
quantity = "length"
unit = "m"
waste = 10
rate = 38.00

[[item]]
code = "F.01"
description = "Floor finish, carpet tiles"
match_layer = "A-FLOR-*"
exclude_layer = "A-FLOR-WET"
quantity = "area"
unit = "m2"
waste = 7
rate = 29.50

[[item]]
code = "F.02"
description = "Skirting"
match_layer = "A-FLOR-*"
quantity = "perimeter"
unit = "m"
rate = 6.20

[[item]]
code = "M.01"
description = "Fire damper 400 x 400"
match_block = "FD*"
where = { SIZE = "400x400" }
quantity = "count"
unit = "nr"
rate = 310.00
```
