"""Exceptions raised by dxf-takeoff."""

from __future__ import annotations


class TakeoffError(Exception):
    """A problem with the input (file, units, options or rules) that the user can fix.

    The CLI prints the message and exits with code 2.
    """
