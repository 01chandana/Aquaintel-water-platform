"""Create the first administrator of a fresh installation (QA audit AQ-001: controlled admin creation).

There is no public sign-up: accounts are created by an administrator in Admin > Users. This command
bootstraps that first administrator from a shell on the server, so nobody needs the demo seed (and its
published demo password) in production.

    python scripts/create_admin.py --email ops.lead@utility.example --name "Ops Lead"
    # prompts for the password twice (not echoed); or set AQUAINTEL_ADMIN_PASSWORD for automation

It is idempotent for roles (creates or refreshes the role/permission matrix of Table 17.1) and refuses to
touch an existing account. The creation is written to the audit log.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.permissions import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.core.permissions import Role as RoleName
from app.core.security import hash_password
from app.db.session import init_engine, session_scope
from app.models.user import Role, User
from app.schemas.user import UserCreate
from app.services.audit_service import AuditService


def _password() -> str:
    if pw := os.environ.get("AQUAINTEL_ADMIN_PASSWORD"):
        return pw
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    return first


async def main(email: str, name: str, role: str) -> None:
    password = _password()
    try:  # same rules as the API: e-mail format, password policy, lengths
        data = UserCreate(email=email, display_name=name, password=password, role=role)
    except ValidationError as exc:
        sys.exit("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))

    init_engine()
    async with session_scope() as session:
        roles: dict[str, Role] = {}
        for rname, perms in ROLE_PERMISSIONS.items():
            r = (await session.execute(select(Role).where(Role.name == rname))).scalar_one_or_none()
            if r is None:
                r = Role(name=rname)
                session.add(r)
            r.permissions, r.description = sorted(perms), ROLE_DESCRIPTIONS[rname]
            roles[rname] = r
        await session.flush()

        exists = (await session.execute(select(User).where(func.lower(User.email) == data.email.lower()))).unique()
        if exists.scalar_one_or_none() is not None:
            sys.exit(f"{data.email} already exists; reset its password from Admin > Users instead")
        user = User(email=data.email.lower(), display_name=data.display_name, password_hash=hash_password(password),
                    role_id=roles[role].id, asset_scopes=[])
        session.add(user)
        await session.flush()
        await AuditService(session).record("user.bootstrap", "user", user.id,
                                           details={"email": user.email, "role": role, "via": "create_admin.py"})
        await session.commit()
    print(f"Created {role} {data.email}. Sign in and enable MFA under Profile.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True, help="display name")
    p.add_argument("--role", default=RoleName.SUPER_ADMIN.value,
                   choices=[RoleName.SUPER_ADMIN.value, RoleName.ADMIN.value])
    a = p.parse_args()
    asyncio.run(main(a.email, a.name, a.role))
