"""fxkit.lint: the fxlint implementation package.

See engine.py for orchestration, report.py for the rule catalogue and output
formatting, and rules_perf.py/rules_sec.py/rules_style.py for the P0xx/S0xx/
C0xx checks themselves.
"""
from . import engine, report  # noqa: F401
