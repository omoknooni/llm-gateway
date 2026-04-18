# Gateway Notes

`gateway/`는 LiteLLM Proxy 설정과 개발용 연동 기준을 담습니다. 실제 정책과 Virtual Key의 source of truth는 backend에 있고, LiteLLM은 OpenAI 호환 요청 집행 계층으로 사용합니다. 컨테이너 시작 시 `start.sh`가 환경변수를 실제 LiteLLM config로 렌더링합니다.

## Credential Strategy

- 운영 환경에서는 ECS/EKS/EC2 role 같은 컨테이너 런타임 역할 자격증명을 사용합니다.
- 로컬 개발에서는 AWS SSO 또는 임시 세션 기반 profile을 사용합니다.
- 장기 AWS access key는 사용하지 않는 것을 기본 정책으로 합니다.
- 현재 v1 스캐폴드는 LiteLLM 재동기화를 위해 backend DB에 key material을 보관합니다. 운영 전환 시에는 KMS 또는 동등한 암호화 저장 계층으로 교체하는 것을 전제로 합니다.

## Supported Client Shape

- Codex CLI: OpenAI 호환 `base_url`과 발급된 Virtual Key를 사용하도록 구성합니다.
- Claude Code: OpenAI 호환 endpoint 또는 proxy endpoint를 사용하도록 맞춥니다.
- 우선 지원 범위는 `chat/completions`, `responses`, `streaming`입니다.

## Example Integration

```bash
export OPENAI_API_KEY="vk_your_virtual_key"
export OPENAI_BASE_URL="http://localhost:4000"
```

클라이언트에서는 실제 Bedrock 모델 ID 대신 `claude-sonnet`, `claude-haiku` 같은 alias를 사용합니다.
