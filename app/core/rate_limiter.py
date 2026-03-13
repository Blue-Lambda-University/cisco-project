"""Token bucket rate limiter for per-connection WebSocket message throttling."""

import time


class TokenBucket:
    """
    Token bucket algorithm for rate limiting.

    Tokens are added at a steady rate. Each call to consume() uses one token.
    Burst is allowed up to bucket capacity, then throttled to the refill rate.
    """

    def __init__(self, rate_per_second: float, burst_size: int) -> None:
        self._rate = rate_per_second
        self._burst_size = burst_size
        self._tokens = float(burst_size)
        self._last_refill = time.monotonic()

    def consume(self) -> tuple[bool, float]:
        """
        Try to consume 1 token.

        Returns:
            (allowed, wait_seconds)
            - allowed: True if the message should be processed
            - wait_seconds: seconds until a token is available (0.0 if allowed)
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst_size, self._tokens + elapsed * self._rate)
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True, 0.0

        wait = (1.0 - self._tokens) / self._rate
        return False, wait
