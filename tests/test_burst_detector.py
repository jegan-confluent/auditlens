"""Tests for src/product/burst_detector.py — Feature 5 burst alert path."""

from __future__ import annotations

from src.product.burst_detector import BurstDetector


class _FakeNotifier:
    """Captures send_system_alert calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_system_alert(self, title: str, body: str) -> int:
        self.calls.append((title, body))
        return 1


def test_burst_fires_at_threshold():
    """Exactly count_threshold failures in the window should fire one alert."""
    notifier = _FakeNotifier()
    detector = BurstDetector(count_threshold=5, window_seconds=300, notifier=notifier)
    for i in range(5):
        fired = detector.record("User:u-attacker", now=100.0 + i)
        # Only the 5th call should return True
        assert fired == (i == 4), f"unexpected fired={fired} at i={i}"
    assert len(notifier.calls) == 1
    title, body = notifier.calls[0]
    assert title == "Auth failure burst detected"
    assert "User:u-attacker" in body
    assert "5 auth failures" in body
    assert "300s" in body


def test_below_threshold_does_not_fire():
    """4 failures (count_threshold - 1) must NOT fire."""
    notifier = _FakeNotifier()
    detector = BurstDetector(count_threshold=5, window_seconds=300, notifier=notifier)
    for i in range(4):
        fired = detector.record("User:u-attacker", now=100.0 + i)
        assert fired is False
    assert notifier.calls == []
    assert detector.actor_count("User:u-attacker") == 4


def test_failures_outside_window_dont_count():
    """Failures older than window_seconds should be pruned and not contribute."""
    notifier = _FakeNotifier()
    detector = BurstDetector(count_threshold=5, window_seconds=300, notifier=notifier)
    # 4 stale failures, all older than window
    for i in range(4):
        detector.record("User:u-attacker", now=100.0 + i)
    # Jump forward 1000s — the stale window expires, only this 5th failure is current
    fired = detector.record("User:u-attacker", now=1100.0)
    assert fired is False
    assert detector.actor_count("User:u-attacker") == 1
    assert notifier.calls == []


def test_burst_resets_after_firing():
    """After firing the alert, the actor's window resets. The 6th, 7th, …
    failures should NOT fire — only when the count climbs back to threshold."""
    notifier = _FakeNotifier()
    detector = BurstDetector(count_threshold=5, window_seconds=300, notifier=notifier)
    # First burst: 5 failures → fire.
    for i in range(5):
        detector.record("User:u-attacker", now=100.0 + i)
    assert len(notifier.calls) == 1
    # 6th and 7th failures: window is reset, only 1 and 2 in current window.
    fired6 = detector.record("User:u-attacker", now=105.0)
    fired7 = detector.record("User:u-attacker", now=106.0)
    assert fired6 is False
    assert fired7 is False
    assert len(notifier.calls) == 1
    # 5 more failures in a row should fire a second alert (re-armed).
    fired_again = False
    for i in range(3):
        fired = detector.record("User:u-attacker", now=107.0 + i)
        fired_again = fired_again or fired
    assert fired_again is True
    assert len(notifier.calls) == 2


def test_per_actor_isolation():
    """Failures for one actor must not count toward another actor's threshold."""
    notifier = _FakeNotifier()
    detector = BurstDetector(count_threshold=5, window_seconds=300, notifier=notifier)
    for i in range(4):
        detector.record("User:u-a", now=100.0 + i)
        detector.record("User:u-b", now=100.0 + i)
    # Neither has reached 5 yet
    assert notifier.calls == []
    # Tip u-a over the edge
    fired = detector.record("User:u-a", now=104.0)
    assert fired is True
    assert len(notifier.calls) == 1
    assert "User:u-a" in notifier.calls[0][1]
    assert "User:u-b" not in notifier.calls[0][1]


def test_empty_actor_string_is_noop():
    """Defensive: empty actor never fires, never crashes."""
    notifier = _FakeNotifier()
    detector = BurstDetector(count_threshold=2, window_seconds=300, notifier=notifier)
    assert detector.record("", now=100.0) is False
    assert detector.record("", now=101.0) is False
    assert notifier.calls == []


def test_detector_without_notifier_records_but_silent():
    """A detector instantiated without a notifier must still track state
    correctly — useful for dry-run / smoke-test scenarios — but cannot
    dispatch."""
    detector = BurstDetector(count_threshold=3, window_seconds=300, notifier=None)
    for i in range(3):
        fired = detector.record("User:u-x", now=100.0 + i)
    # `fired` is True on the 3rd call even without a notifier — the
    # caller can still observe the burst via the return value.
    assert fired is True
