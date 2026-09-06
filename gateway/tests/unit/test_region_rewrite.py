"""리전 접두사 재작성 (docs/04).

호출 리전과 접두사가 다르면 Bedrock 이 ValidationException 을 냅니다. 안전망이지 정상
경로가 아니므로, 모르는 것에는 손대지 않는 방향으로 실패해야 합니다.
"""

from __future__ import annotations

import pytest

from gateway.services.region import rewrite_model_id

MODEL = "anthropic.claude-sonnet-4-5-20250929-v1:0"


@pytest.mark.parametrize(
    ("model_id", "region", "expected"),
    [
        (f"us.{MODEL}", "ap-northeast-2", f"apac.{MODEL}"),
        (f"apac.{MODEL}", "us-east-1", f"us.{MODEL}"),
        (f"us.{MODEL}", "eu-west-1", f"eu.{MODEL}"),
        (f"apac.{MODEL}", "ap-northeast-1", f"apac.{MODEL}"),   # 이미 맞으면 그대로
        (f"global.{MODEL}", "ap-northeast-2", f"global.{MODEL}"),  # 어디서든 해석됨
        (MODEL, "ap-northeast-2", MODEL),                        # profile 이 아닌 모델 id
        (f"us.{MODEL}", "ca-central-1", f"us.{MODEL}"),          # 모르는 리전군 → 무변경
        (f"us.{MODEL}", None, f"us.{MODEL}"),                    # 리전 미지정 → 무변경
        ("meta.llama3-70b-instruct-v1:0", "us-east-1", "meta.llama3-70b-instruct-v1:0"),
    ],
)
def test_rewrite_table(model_id: str, region: str | None, expected: str):
    assert rewrite_model_id(model_id, region) == expected


def test_unknown_prefix_is_left_alone():
    """알려진 접두사가 아니면 모델 id 의 일부일 수 있습니다. 함부로 바꾸지 않습니다."""
    assert rewrite_model_id("cohere.command-r-v1:0", "ap-northeast-2") == "cohere.command-r-v1:0"
