"""seed bootstrap — 기본 팀과 최초 관리자

Revision ID: 0003
Revises: '0002'
Create Date: 2026-09-06

빈 DB 에는 사용자 행이 하나도 없습니다. OIDC 로그인은 `idp_subject` 또는 이메일로 기존
사용자를 찾으므로(JIT 프로비저닝은 그룹→팀 매핑 확정 전까지 끄기로 했습니다), 최초 관리자
행이 없으면 아무도 로그인할 수 없습니다.

`BOOTSTRAP_ADMIN_EMAIL` 이 설정된 경우에만 관리자 행을 만듭니다. 설정하지 않으면 팀만
만들고 넘어갑니다(로컬 개발은 DEV_LOGIN_ENABLED 경로로 들어옵니다).

역할 부여는 여기서 끝나지 않습니다. 로그인 시 `ADMIN_EMAILS`/`ADMIN_GROUPS` 부트스트랩이
다시 판정하므로, 운영에서는 두 설정을 함께 맞춰야 합니다.
"""

from __future__ import annotations

import os
import uuid

from alembic import op
from sqlalchemy import text

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_NAMESPACE = uuid.UUID("6f5c1f6a-6b6f-5c1a-9f3a-000000000000")


def _deterministic_id(name: str) -> uuid.UUID:
    """재실행해도 같은 id 가 나오도록 이름에서 유도합니다(멱등)."""
    return uuid.uuid5(_NAMESPACE, f"llm-gateway:bootstrap:{name}")


def upgrade() -> None:
    bind = op.get_bind()

    team_name = os.getenv("BOOTSTRAP_TEAM_NAME", "platform")
    team_id = _deterministic_id(f"team:{team_name}")
    bind.execute(
        text(
            "INSERT INTO auth.teams (id, name, description, is_active) "
            "VALUES (:id, :name, :description, true) ON CONFLICT (name) DO NOTHING"
        ),
        {"id": team_id, "name": team_name, "description": "부트스트랩 기본 팀"},
    )

    admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    if not admin_email:
        return

    bind.execute(
        text(
            "INSERT INTO auth.users (id, email, display_name, role, team_id, provider, is_active) "
            "VALUES (:id, :email, :display_name, 'ADMIN', "
            "        (SELECT id FROM auth.teams WHERE name = :team_name), 'bootstrap', true) "
            "ON CONFLICT (email) DO NOTHING"
        ),
        {
            "id": _deterministic_id(f"user:{admin_email.lower()}"),
            "email": admin_email,
            "display_name": os.getenv("BOOTSTRAP_ADMIN_NAME", admin_email.split("@")[0]),
            "team_name": team_name,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    if admin_email:
        bind.execute(
            text("DELETE FROM auth.users WHERE email = :email AND provider = 'bootstrap'"),
            {"email": admin_email},
        )
    bind.execute(
        text("DELETE FROM auth.teams WHERE name = :name"),
        {"name": os.getenv("BOOTSTRAP_TEAM_NAME", "platform")},
    )
