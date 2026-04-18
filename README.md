# LiteLLM-based Internal LLM Gateway

사내 공통 LLM Gateway와 중앙 비용 관제 플랫폼을 구축하기 위한 프로젝트입니다. 이 저장소는 LiteLLM을 기반으로 AWS Bedrock 모델 호출을 표준화하고, 팀/개인 단위의 접근 제어, Virtual Key 발급, 사용량 집계, 비용 추정, 리더보드 시각화를 일관된 구조로 제공하는 것을 목표로 합니다.

## Why This Project Exists

여러 팀이 개별적으로 Bedrock을 호출하면 다음 문제가 빠르게 발생합니다.

- 모델 호출 인터페이스가 팀별로 달라 운영 복잡도가 높아집니다.
- 실제 AWS 자격 증명이 분산 노출되어 보안 통제가 어려워집니다.
- 누가 어떤 모델을 얼마나 사용했고 비용이 얼마나 발생했는지 중앙에서 보기 어렵습니다.
- 고정형 구독 모델과 종량제 모델의 비용 효과를 데이터로 비교하기 어렵습니다.

이 프로젝트는 이러한 문제를 해결하기 위해 다음을 제공합니다.

- OpenAI 호환 호출 경험을 유지하는 공통 Gateway
- Claude를 포함한 Bedrock 모델의 표준화된 호출 인터페이스
- 실제 Bedrock 자격 증명을 감춘 Virtual Key 발급 체계
- 팀/사용자/키/모델 단위 사용량 및 추정 비용 집계
- 운영 관제 대시보드와 리더보드 기반 가시성
- 모델별 품질, 속도, 비용 비교를 위한 실험 환경

## Goals

- 팀/개인별 사용량을 중앙에서 통제할 수 있는 사내 LLM Gateway 플랫폼 설계 및 구현
- Bedrock 모델을 동일 인터페이스로 호출할 수 있도록 표준화
- Virtual Key 기반 인증 체계로 실제 클라우드 자격 증명 비노출
- 키 로테이션, 폐기, 사용 이력 추적 및 팀/개인 단위 접근 제어
- 팀, 사용자, Virtual Key, 모델 기준의 사용량/비용 관제
- 누적 호출량, 토큰 사용량, 추정 비용 기준 리더보드 제공
- 종량제 전환 효과를 검증할 수 있는 비용 분석 기반 마련

## Platform Overview

플랫폼은 크게 4개 계층으로 구성됩니다.

1. Gateway Plane
   LiteLLM Gateway가 외부 요청을 OpenAI 호환 인터페이스로 받고, 내부 모델 카탈로그를 통해 Bedrock 모델로 라우팅합니다.
2. Control Plane
   FastAPI 기반 관리 API가 팀, 사용자, Virtual Key, 정책, 허용 모델, 집계 기준을 관리합니다.
3. Data Plane
   Postgres는 운영 데이터와 집계 결과를 저장하고, Redis는 캐시, rate limiting, 짧은 TTL 세션/쿼터 보조 저장소 역할을 담당합니다.
4. Observability Plane
   Next.js 대시보드와 로그/메트릭 파이프라인이 사용량, 비용, 리더보드, 키 이력, 모델 비교 결과를 시각화합니다.

## Reference Architecture

```text
Client App / Internal Service
        |
        v
  Virtual Key Authentication
        |
        v
 LiteLLM Gateway (OpenAI-compatible)
        |
        +--> Policy / Model Catalog / Access Control
        |
        +--> Usage Event Pipeline
        |
        v
 AWS Bedrock (Claude and other models)

Control API (FastAPI)
        |
        +--> Team / User / Key / Policy Management
        +--> Aggregation / Cost Estimation Jobs
        |
        v
 Postgres <--> Redis
        |
        v
 Next.js Operations Dashboard
```

## Core Capabilities

### 1. Standardized Model Access

- Claude를 포함한 여러 Bedrock 모델을 단일 인터페이스로 호출
- 모델별 세부 파라미터 차이를 Gateway 내부에서 흡수
- 운영자는 모델 카탈로그 기준으로 허용 모델과 기본 라우팅 정책 관리

### 2. Virtual Key Management

- 실제 Bedrock 자격 증명 대신 내부 발급 Virtual Key 사용
- 키별 소속 팀/사용자, 허용 모델, 상태, 발급 시점, 만료 정책 추적
- 키 로테이션, 폐기, 사용 이력 확인 가능

### 3. Team/User Access Control

- 사내 SSO/IdP 기반 팀/사용자 엔터티를 기준으로 권한 부여
- 팀 단위 기본 정책 + 사용자 단위 예외 정책 확장 가능
- 특정 모델 접근 제한, 쿼터, rate limit, key scope 관리 기반 마련

### 4. Usage and Cost Observability

- 호출 건수, 입력/출력 토큰, 오류율, 지연시간, 추정 비용 집계
- 팀, 사용자, Virtual Key, 모델 기준으로 drill-down 가능한 관제 구조
- Bedrock 온디맨드 단가 기준 추정 비용 계산

### 5. Leaderboards and Dashboard

- 팀별/사용자별 누적 호출량, 토큰 사용량, 추정 비용 리더보드
- 사용량 상위 팀/사용자와 모델 사용 패턴을 시각화
- 운영 관점의 이상 징후, 비용 집중 구간, 사용 추세를 빠르게 확인

### 6. Model Evaluation Playground

- 동일 프롬프트를 여러 Bedrock 모델에 비교 실행
- 품질, 응답속도, 추정 비용을 나란히 비교
- 운영 환경과 분리된 실험 공간에서 모델 선택 기준 수립

## Primary User Flows

### Team Onboarding

1. 관리자가 SSO/IdP 기반 팀과 사용자를 동기화합니다.
2. 팀 기본 정책과 허용 모델 범위를 설정합니다.
3. 팀 또는 사용자 단위 Virtual Key를 발급합니다.

### Secure Model Consumption

1. 내부 서비스가 Virtual Key로 Gateway를 호출합니다.
2. Gateway가 키 상태, 소속, 정책, 허용 모델을 검증합니다.
3. LiteLLM이 표준 요청을 Bedrock 모델 호출로 변환합니다.
4. 사용량 이벤트와 비용 추정 데이터가 저장됩니다.

### Cost and Usage Governance

1. 운영자는 대시보드에서 팀/사용자/모델 단위 사용량을 확인합니다.
2. 이상 사용 패턴이나 과도한 비용 증가를 탐지합니다.
3. 필요 시 키 폐기, 로테이션, 접근 모델 제한, quota 조정 등을 수행합니다.

### Model Experimentation

1. 운영자 또는 플랫폼 사용자가 비교용 프롬프트를 제출합니다.
2. 여러 Bedrock 모델에서 동일 조건으로 실행합니다.
3. 품질/속도/비용 결과를 비교해 운영 기본 모델 정책을 조정합니다.

## Technology Stack

- Gateway: LiteLLM
- Management API: Python + FastAPI
- Model Provider: AWS Bedrock
- Database: PostgreSQL
- Cache / Rate Limiting: Redis
- Dashboard: Next.js + TypeScript
- Identity Source: Corporate SSO / IdP
- Cost Basis: Bedrock on-demand pricing
- Observability: application logs, metrics, audit trail, aggregation jobs

## Documentation Map

세부 기능별 구현 지침은 아래 문서를 참조합니다.

- [Gateway architecture](docs/gateway-architecture.md)
- [Virtual key management](docs/virtual-key-management.md)
- [Usage and cost observability](docs/usage-and-cost-observability.md)
- [Model evaluation playground](docs/model-evaluation-playground.md)
- [Leaderboard and dashboard](docs/leaderboard-and-dashboard.md)
- [Deployment and operations](docs/deployment-and-operations.md)
- [Frontend hosting options](docs/frontend-hosting-options.md)

## Initial Delivery Scope

초기 단계에서는 다음을 기준선으로 정의합니다.

- LiteLLM 기반 Gateway 표준 인터페이스 정립
- Bedrock 모델 카탈로그와 라우팅 규칙 수립
- 팀/사용자/Virtual Key 관리용 control plane 설계
- 사용량 이벤트 저장 및 비용 추정 집계 파이프라인 정의
- 내부 운영 대시보드와 리더보드 요구사항 정리
- 운영/보안/배포 원칙 문서화

## Non-Goals for the First Iteration

- 모든 모델 제공자에 대한 즉시 지원
- 사내 정산 단가와 외부 원가의 동시 회계 처리
- 고급 자동 예산 제어와 완전한 chargeback 워크플로
- 사용자 셀프서비스 포털의 완성형 UX

## Status

현재 저장소는 문서 우선 단계이며, 본 문서는 구현 착수 전에 아키텍처 방향과 공통 용어를 맞추기 위한 기준 문서입니다.
