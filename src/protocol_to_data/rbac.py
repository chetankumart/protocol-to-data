"""RBAC injection points — STUB ONLY, not enforced (hackathon scope).

protocol-to-data has two natural production roles:

  • Clinical Data Manager — WRITE: trigger runs, generate/snapshot datasets, inject anomalies.
  • Statistician          — READ-ONLY: browse generated data, load previous runs, view scorecards.

In production an auth middleware (SSO / OIDC → JWT) would resolve the caller's identity to a
`Role`, and every write/read data-access and UI action would be gated by the `require_*`
functions below. For the demo these are intentional no-ops so the app runs unauthenticated —
they mark exactly where authorization would be injected, without building it.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    CLINICAL_DATA_MANAGER = "clinical_data_manager"   # read + write
    STATISTICIAN = "statistician"                     # read-only


def current_role() -> Role:
    """STUB: resolve the authenticated caller's role.

    Production: read the identity from the request/session (JWT claim, header, SSO context).
    Demo: everyone is a Clinical Data Manager (full access).
    """
    return Role.CLINICAL_DATA_MANAGER


def require_write(role: Role | None = None) -> None:
    """STUB: gate a write op (run / generate / snapshot / inject).

    Production: raise PermissionError unless `role` (or `current_role()`) may write —
    i.e. is a Clinical Data Manager. Demo: no-op.
    """
    return None


def require_read(role: Role | None = None) -> None:
    """STUB: gate a read op (browse data / restore a previous run / view scorecard).

    Production: raise PermissionError unless `role` (or `current_role()`) may read.
    Both roles may read. Demo: no-op.
    """
    return None
