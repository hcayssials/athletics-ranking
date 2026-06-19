"""World Athletics ranking 'what-if' modelling tool.

Public API:
    from wa_ranking import what_if, load_championship
"""
from .whatif import what_if
from .config import load_championship, load_event

__all__ = ["what_if", "load_championship", "load_event"]
