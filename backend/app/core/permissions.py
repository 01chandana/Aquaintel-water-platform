"""RBAC permission matrix (spec Table 17.1) and ABAC asset-scope helpers (Ch. 17.3.2).

Permissions are ``<resource>:<action>`` strings embedded in the JWT ``permissions`` claim
(Listing 17.1). Roles are cumulative where the spec's "Operator+" notation implies it.
"""

from __future__ import annotations

import fnmatch
from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    TECHNICIAN = "technician"
    ENGINEER = "engineer"
    DATA_SCIENTIST = "data_scientist"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


VIEWER = {
    "dashboards:read", "dashboards:write", "alerts:read", "assets:read", "kpis:read",
}
OPERATOR = VIEWER | {
    "telemetry:read", "alerts:acknowledge", "alerts:resolve", "reports:read", "reports:generate",
    "work_orders:read", "work_orders:write", "ml:predict",
}
TECHNICIAN = OPERATOR | {"work_orders:complete", "assets:maintenance"}
ENGINEER = TECHNICIAN | {
    "assets:write", "telemetry:write", "kpis:write", "alerts:rules", "alerts:escalate",
    "reports:schedule", "compliance:read", "work_orders:assign", "ml:read", "optimization:run",
}
DATA_SCIENTIST = OPERATOR | {
    "ml:read", "ml:register", "ml:deploy", "ml:performance", "data:export", "compliance:read",
    "telemetry:write",
}
ADMIN = ENGINEER | DATA_SCIENTIST | {
    "users:manage", "system:config", "audit:read", "assets:delete", "alerts:rules:delete",
    "admin:read", "api_keys:manage",
}
SUPER_ADMIN = ADMIN | {"roles:manage", "tenant:config"}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.VIEWER: VIEWER,
    Role.OPERATOR: OPERATOR,
    Role.TECHNICIAN: TECHNICIAN,
    Role.ENGINEER: ENGINEER,
    Role.DATA_SCIENTIST: DATA_SCIENTIST,
    Role.ADMIN: ADMIN,
    Role.SUPER_ADMIN: SUPER_ADMIN,
}

ROLE_DESCRIPTIONS = {
    Role.VIEWER: "Read dashboards, view alerts (external stakeholders)",
    Role.OPERATOR: "Read telemetry, acknowledge alerts, view KPIs (shift operators)",
    Role.TECHNICIAN: "Work order CRUD, asset maintenance status (field technicians)",
    Role.ENGINEER: "Asset config, KPI definitions, rule creation (process engineers)",
    Role.DATA_SCIENTIST: "Model training, deployment, data export (analytics team)",
    Role.ADMIN: "User management, system config, audit logs (IT administrators)",
    Role.SUPER_ADMIN: "All permissions, role definition, tenant config",
}

# Roles that must enrol in MFA (Ch. 17.2.2)
MFA_REQUIRED_ROLES = {Role.ADMIN, Role.SUPER_ADMIN}

# API-key-only scope for machine-to-machine ingestion (endpoint #31 "Integration")
INTEGRATION_PERMISSIONS = {"telemetry:ingest", "telemetry:read", "assets:read"}
ALL_PERMISSIONS = sorted(SUPER_ADMIN | INTEGRATION_PERMISSIONS)


def asset_in_scope(asset_path: str | None, scopes: list[str] | None) -> bool:
    """ABAC asset-scope check. ``scopes`` are glob patterns such as ``plant_a/*``.

    An empty/None scope list means unrestricted (global roles).
    """
    if not scopes:
        return True
    if not asset_path:
        return False
    return any(fnmatch.fnmatch(asset_path, pattern) or asset_path == pattern.rstrip("/*")
               for pattern in scopes)
