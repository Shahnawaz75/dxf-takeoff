# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [0.1.0] - 2026-11-24

First release.

### Added

- `dxf-takeoff` command and `dxf_takeoff.takeoff()` Python API.
- Lengths by layer, or by layer + linetype / colour, for LINE, ARC, CIRCLE, ELLIPSE, LWPOLYLINE and
  2D POLYLINE (exact bulge arcs), 3D POLYLINE, SPLINE (flattened, with a tolerance option) and MLINE.
- Areas and perimeters of closed polylines, circles, ellipses, closed splines, HATCH and MPOLYGON,
  with holes and islands following the hatch style.
- Block references expanded recursively with the full transformation, including non-uniform
  scaling and mirroring; MINSERT arrays; layer-0 / BYBLOCK inheritance; frozen/off layer handling.
- Block counts by effective name (dynamic `*U` blocks resolved), split by attribute values, with
  optional nested counts.
- Units from `$INSUNITS`, `--units` override, `--out-units` conversion and `--scale`.
- Layer include/exclude wildcards, `--include-hidden`, `--layout` for paper space.
- BOQ rules file (`takeoff.toml`) with waste factors, unit rates, attribute filters and a
  "not in the BOQ" check.
- Terminal table, CSV, JSON and Excel output (Summary, Lengths, Areas, Blocks and BOQ sheets with
  SUM and rate formulas).
- Tank-farm piping example with generator script, rules file and committed outputs.

[0.1.0]: https://github.com/Shahnawaz75/dxf-takeoff/releases/tag/v0.1.0
