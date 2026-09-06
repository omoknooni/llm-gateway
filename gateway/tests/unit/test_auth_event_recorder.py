"""정책 거절 기록의 창(window) 규칙 (docs/06 S4)."""

from __future__ import annotations

from gateway.services.auth_event_recorder import AuthEventRecorder


def test_repeated_failures_collapse_into_one_row():
    """실패마다 INSERT 하면 공격 트래픽이 그대로 DB 부하가 됩니다."""
    recorder = AuthEventRecorder(window_seconds=60)
    for i in range(5):
        recorder.observe(
            outcome="INVALID_KEY", request_id=f"r{i}", key_hash_prefix="3f9a1c07", source_ip="10.0.0.1"
        )
    rows = recorder.pop_expired(force=True)
    assert len(rows) == 1
    assert rows[0]["occurrence_count"] == 5


def test_row_points_at_the_first_request_of_the_window():
    """그 요청의 로그 줄이 원인을 담고 있어 조사 진입점이 됩니다."""
    recorder = AuthEventRecorder(window_seconds=60)
    recorder.observe(outcome="INVALID_KEY", request_id="first", key_hash_prefix="aa")
    recorder.observe(outcome="INVALID_KEY", request_id="second", key_hash_prefix="aa")
    assert recorder.pop_expired(force=True)[0]["request_id"] == "first"


def test_different_outcomes_and_sources_are_separate_windows():
    recorder = AuthEventRecorder(window_seconds=60)
    recorder.observe(outcome="INVALID_KEY", request_id="r1", source_ip="10.0.0.1")
    recorder.observe(outcome="REVOKED", request_id="r2", source_ip="10.0.0.1")
    recorder.observe(outcome="INVALID_KEY", request_id="r3", source_ip="10.0.0.2")
    assert len(recorder.pop_expired(force=True)) == 3


def test_open_windows_are_not_flushed_early():
    recorder = AuthEventRecorder(window_seconds=60)
    recorder.observe(outcome="INVALID_KEY", request_id="r1")
    assert recorder.pop_expired() == []
    assert recorder.pop_expired(force=True) != []


def test_window_carries_the_subject_when_the_key_was_identified():
    recorder = AuthEventRecorder(window_seconds=60)
    recorder.observe(
        outcome="MODEL_NOT_ALLOWED",
        request_id="r1",
        virtual_key_id="vk-1",
        team_id="t-1",
        user_id="u-1",
        model_alias="claude-opus",
    )
    row = recorder.pop_expired(force=True)[0]
    assert (row["virtual_key_id"], row["team_id"], row["model_alias"]) == ("vk-1", "t-1", "claude-opus")


async def test_flush_without_database_drops_rather_than_holding_memory():
    """거절 감사는 과금에 영향을 주지 않습니다. 장애 중에 메모리를 붙들 이유가 없습니다."""
    recorder = AuthEventRecorder(window_seconds=60)
    recorder.observe(outcome="INVALID_KEY", request_id="r1")
    assert await recorder.flush(None, force=True) == 0
    assert recorder.pop_expired(force=True) == []
