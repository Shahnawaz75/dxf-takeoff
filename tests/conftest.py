"""Shared helpers: drawings built with ezdxf whose quantities are known exactly."""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf
import pytest


def new_doc(insunits: int = 4):
    """New R2018 drawing; $INSUNITS 4 = millimetres."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
    return doc


def roundtrip(doc, tmp_path: Path, name: str = "drawing.dxf") -> Path:
    """Save to disk so tests read the DXF exactly as stored."""
    path = tmp_path / name
    doc.saveas(path)
    return path


def ellipse_perimeter(a: float, b: float) -> float:
    """Gauss-Kummer series, converged to machine precision (exact reference)."""
    h = ((a - b) / (a + b)) ** 2
    total, coeff, n = 1.0, 1.0, 0
    while True:
        n += 1
        coeff *= (0.5 - (n - 1)) / n  # binomial(1/2, n)
        term = coeff * coeff * h**n
        total += term
        if term < 1e-18 * total:
            return math.pi * (a + b) * total


def ramanujan2(a: float, b: float) -> float:
    """Ramanujan's second approximation of an ellipse perimeter."""
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


@pytest.fixture
def doc():
    return new_doc()
