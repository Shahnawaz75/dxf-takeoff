# Contributing to dxf-takeoff

Thanks for helping. People price real jobs with these numbers, so correctness comes first.

## Reporting a wrong quantity

The most useful bug report is a **small DXF file** that reproduces the problem, the command you ran,
what dxf-takeoff reported and what you expected (and how you measured it, e.g. AutoCAD LIST/AREA).
Please remove anything confidential from the drawing first; often a few entities copied into a new
drawing are enough. If you cannot share a file, a short ezdxf script that builds one works too.

## Development setup

```bash
git clone https://github.com/Shahnawaz75/dxf-takeoff
cd dxf-takeoff
python -m venv .venv
.venv/bin/pip install -e ".[test,docs]"        # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest
```

Tip for Windows: if the repository sits in a very deep folder, create the virtual environment in a
short path outside the repository, and run the tests with `python -B -m pytest -p no:cacheprovider`
to avoid writing cache files into the tree.

## Rules for changes

- **Every quantity needs a test with a known answer.** Build the drawing in the test with ezdxf and
  assert against a closed-form value (or a precise numerical reference) with a tight tolerance,
  e.g. `pytest.approx(math.pi * r, rel=1e-14)`. "It looks right" is not enough.
- Round-trip through a saved file (`roundtrip()` in `tests/conftest.py`) when the DXF storage
  format matters, e.g. for hatch edges.
- If an approximation is unavoidable, mark the result as approximate and state the method in the notes.
- Keep dependencies minimal: ezdxf is the only required dependency.
- Type hints and docstrings on public functions; keep functions small and readable.

## Regenerating the example and the screenshot

```bash
python examples/make_example.py      # examples/tank_farm.dxf
python examples/make_outputs.py      # examples/takeoff.xlsx, takeoff.json, csv/, docs/example-output.md
python examples/make_screenshot.py   # docs/screenshot.png (needs matplotlib)
```

`tests/test_example.py` fails if the committed JSON no longer matches the code, so regenerate the
outputs when a change alters the example's numbers, and mention it in the changelog.

## Releasing

Bump the version in `pyproject.toml` and `src/dxf_takeoff/_version.py` (a test checks they match),
update `CHANGELOG.md`, tag `vX.Y.Z`.
