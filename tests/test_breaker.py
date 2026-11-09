from router.breaker import CircuitBreaker, State


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def test_starts_closed_and_allows():
    b = CircuitBreaker(3, 1.0, Clock())
    assert b.state is State.CLOSED and b.allow()


def test_opens_after_threshold_consecutive_failures():
    b = CircuitBreaker(3, 1.0, Clock())
    b.record_failure(); b.record_failure()
    assert b.state is State.CLOSED
    b.record_failure()
    assert b.state is State.OPEN and b.trips == 1 and not b.allow()


def test_success_resets_failure_count():
    b = CircuitBreaker(3, 1.0, Clock())
    b.record_failure(); b.record_failure(); b.record_success(); b.record_failure(); b.record_failure()
    assert b.state is State.CLOSED


def test_half_open_after_cooldown_allows_single_probe():
    c = Clock(); b = CircuitBreaker(1, 1.0, c)
    b.record_failure()
    c.t = 0.5
    assert not b.allow()
    c.t = 1.01
    assert b.allow() and b.state is State.HALF_OPEN
    assert not b.allow()  # second concurrent probe refused
    assert b.short_circuits == 2


def test_half_open_probe_success_closes_failure_reopens():
    c = Clock(); b = CircuitBreaker(1, 1.0, c)
    b.record_failure(); c.t = 2; b.allow(); b.record_success()
    assert b.state is State.CLOSED
    b.record_failure(); c.t = 4; b.allow(); b.record_failure()
    assert b.state is State.OPEN and b.opened_at == 4 and b.trips == 3
