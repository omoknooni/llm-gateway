from gateway.services.last_used import LastUsedTracker


def test_first_call_writes_then_throttles():
    """매 요청 UPDATE 하면 인기 키 하나가 초당 수백 번의 row lock 을 만듭니다."""
    tracker = LastUsedTracker(throttle_seconds=60)
    assert tracker.should_write("vk-1") is True
    assert tracker.should_write("vk-1") is False


def test_throttle_is_per_key():
    tracker = LastUsedTracker(throttle_seconds=60)
    assert tracker.should_write("vk-1") is True
    assert tracker.should_write("vk-2") is True


def test_zero_throttle_always_writes():
    tracker = LastUsedTracker(throttle_seconds=0)
    assert tracker.should_write("vk-1") is True
    assert tracker.should_write("vk-1") is True
