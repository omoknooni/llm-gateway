# backend/db — 마이그레이션 컴포넌트

Alembic 마이그레이션과 부트스트랩 SQL. **앱 패키지와 분리**된 별도 컴포넌트이고,
배포 시 Job 으로 한 번 실행합니다. 앱이 기동하면서 스키마를 고치지 않습니다.

```text
db/
├── alembic.ini        DB URL 은 환경변수로 주입 (파일에 두지 않음)
├── env.py             Base.metadata 를 대상으로 autogenerate
├── init/              스키마·확장·DB 역할·스키마 권한 (멱등, alembic 이전)
├── versions/          Alembic 리비전
├── grants/            테이블 단위 권한 (alembic 이후)
├── run_migration.sh   init/*.sql → alembic upgrade head → grants/*.sql
└── Dockerfile         마이그레이션 Job 이미지
```

## 실행

```bash
export MIGRATION_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/llm_gateway'
export BACKEND_APP_PASSWORD='...'   # init SQL 의 역할 비밀번호
export GATEWAY_APP_PASSWORD='...'
./run_migration.sh
```

## 규칙

- **Alembic 의 단일 소유자는 `backend/` 입니다.** gateway 는 같은 스키마를 읽되 정의하지 않습니다.
- 마이그레이션은 DDL 권한을 가진 역할로 실행합니다. 런타임 역할(`backend_app`)에는 DDL 권한이 없습니다.
- `init/*.sql` 은 멱등해야 합니다(`IF NOT EXISTS`).
- autogenerate 결과를 그대로 커밋하지 않습니다. 생성된 리비전은 사람이 읽고 다듬습니다.
- 마이그레이션은 앞으로만 갑니다. downgrade 는 작성하되 운영에서 실행하지 않습니다.
