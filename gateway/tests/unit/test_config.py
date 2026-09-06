from gateway.config import CLIENT_OTHER, Settings


def test_registered_clients_always_include_other():
    """'other' 는 예약어입니다. 설정으로 지울 수 없어야 합니다."""
    s = Settings(registered_clients="claude-code")
    assert s.registered_client_set == frozenset({"claude-code", CLIENT_OTHER})


def test_registered_clients_trims_and_drops_blanks():
    s = Settings(registered_clients=" claude-code , , codex ")
    assert s.registered_client_set == frozenset({"claude-code", "codex", CLIENT_OTHER})


def test_log_format_is_validated():
    import pytest

    with pytest.raises(ValueError):
        Settings(log_format="xml")
