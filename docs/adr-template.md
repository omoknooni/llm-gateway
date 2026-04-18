# ADR-XXX: Short Decision Title

- Status: Proposed | Accepted | Superseded | Rejected
- Date: YYYY-MM-DD
- Decision Makers: team or owner name

## Context

이 ADR이 필요한 문제 상황과 결정 배경을 작성합니다.

- 현재 어떤 상황인지
- 어떤 제약이나 요구사항이 있는지
- 왜 지금 이 결정을 내려야 하는지
- 이 결정을 통해 해소하려는 핵심 문제가 무엇인지

가능하면 제목만 보고도 내용을 유추할 수 있게 하고, Context를 읽으면 왜 이 ADR이 생겼는지 바로 이해할 수 있어야 합니다.

## Decision

이 ADR에서 최종적으로 채택한 결정을 명확하게 작성합니다.

- 무엇을 선택했는지
- 어디에 적용되는지
- 어떤 원칙이나 운영 방식으로 가져갈 것인지

결정 문장은 모호하지 않게 쓰고, 구현자나 운영자가 바로 해석할 수 있어야 합니다.

## Consequences

### Positive

이 결정을 적용했을 때 기대되는 긍정적 결과를 작성합니다.

- 운영상 장점
- 구조적 일관성
- 보안, 성능, 개발 생산성 측면의 이점

### Negative

이 결정으로 인해 생기는 비용이나 제약을 작성합니다.

- 복잡도 증가
- 비용 증가
- 특정 선택지를 포기함으로써 생기는 불이익

### Follow-up Implications

이 결정을 실제로 유지하기 위해 후속으로 필요한 작업이나 추가 결정을 작성합니다.

- 추후 보완이 필요한 부분
- 운영 환경에서 반드시 추가해야 하는 것
- 관련 팀이나 시스템에 미치는 영향

## Options

최종 결정을 포함해 검토했던 option들을 나열합니다.

각 option은 아래 형식을 따릅니다.

### 1. Option Name

이 option이 어떤 방식인지 간단히 설명합니다.

- 장점
  - 이 option을 선택했을 때의 이점
- 단점
  - 이 option의 한계나 비용
- 선택하지 않은 이유
  - 최종 Decision으로 채택되지 않은 이유

필요하다면 최종 채택안에는 아래처럼 표시합니다.

- 최종 선택 여부: Accepted

## References

이 ADR과 관련된 문서, 이슈, 외부 공식 문서, 다른 ADR을 나열합니다.

- 관련 repo 문서 경로
- 외부 공식 문서 링크
- 참고한 설계 문서 또는 이전 ADR

## Writing Notes

- 문서 제목은 간결하고 내용 파악이 가능하도록 작성합니다.
- `Context`, `Decision`, `Consequences`, `Options`, `References` 순서를 유지합니다.
- `Consequences`는 `Positive`, `Negative`, `Follow-up Implications`로 나눕니다.
- `Options`의 각 후보에는 장점, 단점, 선택하지 않은 이유가 포함되어야 합니다.
- 이미 존재하는 ADR 문체와 구조를 가능한 한 일관되게 유지합니다.
