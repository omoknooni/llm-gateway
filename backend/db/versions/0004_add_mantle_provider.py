"""S1 — model.provider enum 에 BEDROCK_MANTLE 추가

Revision ID: 0004
Revises: '0003'
Create Date: 2026-09-06

Mantle 은 전송 방식(HTTPS + bearer)과 IAM 네임스페이스(`bedrock-mantle:`)가 Bedrock native 와
다른 별도 백엔드입니다. `bedrock:InvokeModel` 만 준 role 로는 호출되지 않으므로, 권한 경계가
다른 것을 같은 provider 값으로 묶으면 IRSA 정책을 모델별로 나눌 수 없습니다.
(backend/docs/09-gateway-contract-response.md S1)

**이 리비전은 값 추가만 합니다.** PostgreSQL 은 `ALTER TYPE ... ADD VALUE` 로 추가한 값을
같은 트랜잭션 안에서 사용하지 못합니다. 그래서 값을 쓰는 CHECK 제약(S2)은 0005 로 분리했고,
env.py 에 `transaction_per_migration=True` 를 켜 두 리비전이 서로 다른 트랜잭션에서 돌게 했습니다.
PostgreSQL 12 이상이 필요합니다.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE model.provider ADD VALUE IF NOT EXISTS 'BEDROCK_MANTLE'")


def downgrade() -> None:
    # enum 값은 삭제하지 않습니다(01 문서 공통 규약). 되돌리려면 타입을 새로 만들어 치환해야 하고,
    # 그 사이 그 값을 쓰는 행이 있으면 데이터를 잃습니다.
    pass
