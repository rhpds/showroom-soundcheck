"""Showroom Soundcheck — session-based health check tool for showroom environments."""

from .check_service import (
    TargetCheckResult,
    check_single_target,
    check_targets,
)

__all__ = [
    "TargetCheckResult",
    "check_single_target",
    "check_targets",
]

try:
    from .models import CheckResult, CheckSession, SessionTarget
    __all__ += ["CheckResult", "CheckSession", "SessionTarget"]
except ImportError:
    pass
