"""
One clock for the whole project - seeds and detectors alike.

The matrix a judge sees has to match the matrix in the demo video, and
D1 is inherently wall-clock dependent ("is this dataset stale *now*?").
That only holds if seeding and assessment agree on what "now" means, so
both sides read it from here rather than each calling
`datetime.now()` independently.

`DEADRECKON_NOW` (ISO 8601) overrides the wall clock everywhere at once.
It exists so the determinism claim is testable: shift it, re-seed,
re-run, and the matrix has to come out identical. Unset in normal use.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

NOW_ENV_VAR = "DEADRECKON_NOW"


def parse_anchor(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def now(override: str | None = None) -> datetime:
    """Current time, honouring an explicit override then the env var.

    Precedence is deliberate: an explicit `--anchor`/`--as-of` argument
    beats the environment, which beats the wall clock.
    """
    if override:
        return parse_anchor(override)
    env_value = os.environ.get(NOW_ENV_VAR)
    if env_value:
        return parse_anchor(env_value)
    return datetime.now(timezone.utc)


def is_overridden() -> bool:
    return bool(os.environ.get(NOW_ENV_VAR))
