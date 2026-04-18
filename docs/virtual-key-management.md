# Virtual Key Management

## Objective

실제 AWS Bedrock 자격 증명을 사용자나 내부 애플리케이션에 직접 배포하지 않고, 사내 Gateway 전용 Virtual Key를 발급해 인증, 추적, 회수, 로테이션을 가능하게 합니다.

## Key Principles

- Virtual Key는 Bedrock 자격 증명의 대체 식별자입니다.
- 키는 팀 또는 사용자에 귀속되어야 합니다.
- 키 상태 변화는 모두 추적 가능해야 합니다.
- 키는 허용 모델, 만료 정책, 상태를 가져야 합니다.

## Lifecycle

1. 발급
   팀 또는 사용자에 연결된 새 키를 생성합니다.
2. 활성화
   허용 모델과 정책이 적용된 상태로 Gateway 인증에 사용됩니다.
3. 로테이션
   기존 키를 대체하는 신규 키를 발급하고 점진 전환합니다.
4. 폐기
   분실, 퇴사, 정책 위반, 사고 대응 시 즉시 비활성화합니다.
5. 감사
   발급, 사용, 실패, 로테이션, 폐기 이력을 조회합니다.

## Suggested Data Model

- `team`
- `user`
- `virtual_key`
- `virtual_key_audit_log`
- `access_policy`

`virtual_key`는 최소한 아래 속성을 가집니다.

- key identifier
- masked display value
- owner type: team or user
- owner reference
- allowed model aliases
- status: active, rotated, revoked, expired
- created at / created by
- expires at
- last used at

## Access Control Expectations

- 기본 권한 원천은 사내 SSO/IdP입니다.
- 팀 기본 정책 위에 사용자 예외 정책을 둘 수 있어야 합니다.
- 키별로 허용 모델 범위를 더 좁힐 수 있어야 합니다.
- 필요 시 팀별 quota 또는 rate limit과 연계할 수 있어야 합니다.

## Audit Requirements

- 성공/실패 인증 이벤트를 남깁니다.
- 어떤 키가 어떤 모델을 언제 호출했는지 추적 가능해야 합니다.
- 키 로테이션의 전후 관계를 연결할 수 있어야 합니다.
- 폐기 사유와 수행 주체를 감사 로그에 남깁니다.

## Operational Guidance

- 키 원문은 최소 노출을 원칙으로 합니다.
- 사용자 UI에는 마스킹된 값만 기본 표시합니다.
- 폐기된 키는 즉시 인증 거부되어야 합니다.
- 장기 미사용 키 탐지와 주기적 로테이션 정책을 고려합니다.
