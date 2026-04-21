"""BDS smoke-test package.

Public surface:
    run_bds_smoke(mcaddon_path)       async — use inside FastAPI endpoints
    run_bds_smoke_sync(mcaddon_path)  sync  — use from CLI / run_golden_tests
    is_bds_available()                bool  — quick guard before attempting a run
    SmokeResult, SmokeIssue           result types
"""
from backend.smoke.bds_runner import run_bds_smoke, run_bds_smoke_sync, is_bds_available
from backend.smoke.log_parser import SmokeResult, SmokeIssue

__all__ = [
    "run_bds_smoke",
    "run_bds_smoke_sync",
    "is_bds_available",
    "SmokeResult",
    "SmokeIssue",
]
