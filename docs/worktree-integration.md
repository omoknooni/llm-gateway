# Worktree Integration Workflow

## Objective

이 저장소는 세 개의 컴포넌트(`backend/`, `frontend/`, `gateway/`)를 각각 별도의 git worktree와
브랜치에서 개발하고 `main`으로 통합합니다. 이 문서는 그 **통합 절차와 규율**을 고정합니다.

구현 순서와 컴포넌트 경계는 [implementation-plan.md](implementation-plan.md)가 정의하고,
이 문서는 "작업물을 어떻게 커밋하고 어떻게 `main`으로 옮기는가"만 다룹니다.

## Layout

| 컴포넌트 | 브랜치 | worktree 경로 |
|---|---|---|
| admin backend | `feat/admin-backend` | `~/llm-gateway-worktrees/admin-be` |
| admin frontend | `feat/admin-frontend` | `~/llm-gateway-worktrees/admin-fe` |
| gateway | `feat/gateway` | `~/llm-gateway-worktrees/gateway` |
| 공용 파일 / 통합 | `main` | `~/llm-gateway` |

세 브랜치는 **통합 후에도 삭제하지 않는 장기 브랜치**입니다. worktree가 브랜치를 점유하므로
git이 삭제를 거부하기도 하지만, 그 이전에 의도적으로 유지하는 구조입니다.

```bash
# worktree 신규 생성 (브랜치가 이미 있는 경우)
git worktree add ~/llm-gateway-worktrees/<name> <branch>

# 목록 확인 — 네 항목의 커밋 해시가 정렬돼 있는지 보는 것이 기본 점검입니다
git worktree list
```

## Ownership Boundary

경계를 지키는 것이 이 구조에서 병합 충돌이 0인 이유입니다. 경계가 무너지면 worktree를 쓰는
이유도 함께 사라집니다.

| 대상 | 소유 브랜치 |
|---|---|
| `backend/**` | `feat/admin-backend` |
| `frontend/**` | `feat/admin-frontend` |
| `gateway/**` | `feat/gateway` |
| `README.md`, `AGENTS.md`, `docs/**`, `docker-compose.yml`, `infra/**` | `main` |

- 각 컴포넌트 브랜치는 **자기 디렉터리 밖을 수정하지 않습니다.** 루트 `docker-compose.yml`에
  자기 서비스를 추가하는 것도 공용 파일 변경이므로 `main`에서 처리합니다.
- 상위 문서(ADR, `implementation-plan.md`)에 반영이 필요한 결정은 컴포넌트 문서에
  **"ADR 후보"로 표시만** 하고, `main`에서 번호를 받습니다.
- 브랜치 간 직접 병합은 하지 않습니다. 통합 방향은 항상 컴포넌트 브랜치 → `main`,
  전파 방향은 항상 `main` → 컴포넌트 브랜치입니다.

## Commit Discipline

worktree 구조의 가장 큰 실패 모드는 충돌이 아니라 **작업물이 git 밖에 오래 남는 것**입니다.
`main`에서는 각 worktree의 미커밋 파일이 보이지 않기 때문에 방치돼도 티가 나지 않습니다.

- 마일스톤 하나가 끝나면 바로 커밋합니다. 설계 문서도 코드와 같은 규율을 적용합니다.
- 커밋은 **atomic** 하게 — 한 커밋은 되돌릴 수 있는 하나의 변경 단위입니다.
  마이그레이션·ORM·API·문서가 한 계약 변경에 묶여 있으면 그것이 한 커밋입니다.
- 커밋 메시지는 `TYPE : 요약` 형식입니다 (`FEAT`, `DOCS`, `CHORE`, `FIX`).
  마일스톤 식별자가 있으면 괄호로 덧붙입니다 — 예: `FEAT : Bedrock provider adapter (M4)`.

작업 전후로 전체 worktree 상태를 한 번에 봅니다.

```bash
for w in admin-be admin-fe gateway; do
  echo "=== $w ==="
  git -C ~/llm-gateway-worktrees/$w status --short
done
```

## Integration

컴포넌트 브랜치의 작업을 `main`으로 올리는 경로입니다.

```bash
# 1. 컴포넌트 worktree — 커밋과 push
cd ~/llm-gateway-worktrees/<name>
git status --short          # 미커밋이 남아 있지 않은지 확인
git push -u origin <branch>

# 2. MR/PR 생성 후 main 으로 머지 (원격에서)
gh pr create --base main --head <branch>

# 3. main worktree — 원격 상태를 로컬로 내림
cd ~/llm-gateway
git fetch --all --prune
git merge --ff-only origin/main
```

- **머지 커밋을 남깁니다.** 원격 PR 머지는 기본적으로 머지 커밋을 만들고, 로컬에서 직접
  통합할 때도 `git merge --no-ff <branch>`를 씁니다. fast-forward가 가능하더라도 통합 지점이
  히스토리에 보여야 다음 전파의 기준선이 됩니다.
- squash 머지는 쓰지 않습니다. 컴포넌트 브랜치가 살아남는 구조에서 squash는 브랜치와 `main`의
  공통 조상을 지워, 이후 전파가 매번 이미 반영된 변경을 다시 들고 옵니다.

### 통합 순서

컴포넌트 브랜치들은 파일 경계가 겹치지 않아 충돌 관점에서는 순서가 자유롭습니다. 순서를
강제하는 것은 **문서 상호 참조와 계약 의존성**입니다.

1. **`feat/admin-backend`** — DB 스키마와 [공유 계약](../backend/docs/08-shared-contracts.md)의
   소유자입니다. 나머지 둘의 전제이므로 먼저 들어갑니다.
2. **`feat/gateway`** — backend 스키마를 읽습니다. 문서가 `backend/docs/`를 상대경로로
   링크하므로 backend 병합 후에야 링크가 해석됩니다.
3. **`feat/admin-frontend`** — backend가 생성하는 OpenAPI가 계약 원천입니다.

2와 3은 서로 독립이라 순서를 바꿔도 됩니다. 1은 항상 먼저입니다.

### 통합 후 `main` 작업

컴포넌트 브랜치가 "상위 문서에 반영해야 할 것"으로 남긴 항목을 `main`에서 처리합니다.
이것을 미루면 컴포넌트 문서와 상위 문서의 전제가 갈라집니다.

- 확정된 ADR 후보를 `docs/adr-000X`로 승격
- [implementation-plan.md](implementation-plan.md)의 Open Decisions 갱신
- `README.md`의 Current Status 표 갱신
- 루트 `docker-compose.yml`에 앱 서비스 추가

## Propagation

`main`이 갱신되면 세 worktree 전부에 내려보냅니다. 통합과 전파는 한 세트이며, 전파를 빠뜨리면
컴포넌트 브랜치가 낡은 공용 문서 위에서 작업하게 됩니다.

```bash
for w in admin-be admin-fe gateway; do
  echo "=== $w ==="
  git -C ~/llm-gateway-worktrees/$w merge --ff-only main || echo "!! MANUAL: $w"
done
git worktree list      # 네 항목의 해시가 같으면 정렬 완료
```

- 컴포넌트 브랜치에 새 커밋이 없으면 `--ff-only`가 그대로 통과합니다.
- 새 커밋이 있어 fast-forward가 안 되면 `--ff-only`를 뺀 `git merge main`으로 머지 커밋을
  만듭니다. 실패를 조용히 넘기지 않기 위해 기본은 `--ff-only`로 두고 실패를 드러냅니다.

### rebase를 쓰지 않는 이유

전파에 `git rebase main`을 쓰지 않습니다.

브랜치가 이미 `main`에 병합된 뒤 rebase하면, `main`에 있는 커밋이 새 해시로 복제되고
공통 조상이 어긋납니다. 그 결과 다음 통합에서 같은 변경이 두 번 들어오거나 없는 충돌이 생깁니다.
장기 브랜치를 유지하는 이 구조에서는 **첫 통합 이후 rebase가 항상 틀립니다.**

## Contract Change Protocol

두 plane은 코드를 공유하지 않으므로([AGENTS.md](../AGENTS.md)) 계약 변경이 컴파일 에러로
드러나지 않습니다. 대신 **문서 왕복**으로 처리하고, 그 왕복을 커밋으로 남깁니다.

```text
backend/docs/08-shared-contracts.md   계약 제시 (C1~C6)
              ↓
gateway/docs/06-contract-response.md  회신 + 스키마 변경 요청 (S1~S4)
              ↓
backend/docs/09-gateway-contract-response.md  수용 판단 + 되묻기 (Q1~Q5)
              ↓
gateway/docs/06-contract-response.md  Q1~Q5 확정
              ↓
backend  마이그레이션 0004·0005, ORM·API·캐시 키 반영
```

- 계약 문서는 **한쪽이 단독으로 바꿀 수 없습니다.** 변경은 상대 브랜치의 회신 문서로 응답을 받고
  나서 반영합니다.
- 스키마 변경 요청은 요청자가 아니라 **소유자**(`backend/`)가 구현합니다.
- 되묻기(Q)는 답이 올 때까지 요청자 쪽 마일스톤을 막을 수 있습니다. 어느 마일스톤의 선행 조건인지
  회신 문서에 명시해, 무엇이 막히고 무엇이 안 막히는지 드러냅니다.
- 상대 브랜치의 문서를 링크할 때 상대경로(`../../backend/docs/08-shared-contracts.md`)를 쓰면
  전파 전까지 링크가 깨져 있습니다. **정상 상태이며**, 전파 후 해석됩니다.

## Checklist

**통합 전**

- [ ] 세 worktree 모두 `git status --short`가 비어 있음
- [ ] 컴포넌트 브랜치가 자기 디렉터리 밖을 수정하지 않음 —
      `git diff --name-only main...<branch>` 확인
- [ ] 상위 문서 반영 항목이 컴포넌트 문서에 목록으로 남아 있음
- [ ] lint / 테스트 통과 (`ruff check`, `pytest`, `npm run typecheck`, `npm test`)

**통합 후**

- [ ] `git worktree list`의 네 항목이 같은 해시
- [ ] `main`의 ADR·`implementation-plan.md`·`README.md` 갱신 완료
- [ ] 컴포넌트 문서의 상호 참조 링크가 해석됨

## Trade-offs

이 구조를 유지하는 이유와 그 대가를 남겨 둡니다. 대가 쪽이 커지면 구조를 재검토할 근거가 됩니다.

**얻는 것**

- 컴포넌트별 툴체인 격리. `backend/.venv`와 `frontend/node_modules`가 브랜치 전환마다
  무효화되지 않습니다.
- 세 앱 동시 실행. compose로 PostgreSQL·Redis를 한 번 띄우고 backend와 gateway를 함께 구동해
  스키마·Redis 키 계약을 실제로 맞춰볼 수 있습니다.
- 디렉터리 경계 = 소유권 경계 = 브랜치 경계의 일치. 병합 충돌이 구조적으로 발생하지 않습니다.
- plane 분리 원칙이 git 구조에 강제됩니다. gateway가 backend 코드를 import하는 일이
  물리적으로 일어나지 않습니다.
- 컴포넌트별 독립 작업 공간. 병렬 작업이나 에이전트 분리에 그대로 쓰입니다.

**치르는 대가**

- **계약 변경의 왕복 지연.** 한 브랜치였다면 한 커밋일 일이 문서 왕복이 됩니다.
  위 Contract Change Protocol이 이 비용을 관리 가능한 형태로 고정한 것이지 없앤 것은 아닙니다.
- **미커밋 작업의 가시성 제로.** `main`에서 다른 worktree의 상태가 보이지 않습니다.
  Commit Discipline의 일괄 status 확인이 유일한 방어선입니다.
- **통합 전까지 end-to-end 검증 불가.** 계약 일치를 문서로만 확인하게 됩니다.
- 전파를 빠뜨리면 낡은 공용 문서 위에서 작업하게 됩니다.
- 디스크와 에디터 인덱싱이 컴포넌트 수만큼 늘어납니다.

## References

- [AGENTS.md](../AGENTS.md) — Branch Discipline
- [implementation-plan.md](implementation-plan.md) — 구현 순서와 컴포넌트 경계
- [backend/docs/08-shared-contracts.md](../backend/docs/08-shared-contracts.md) — 공유 계약 원본
