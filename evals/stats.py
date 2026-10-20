"""The few statistics a pass count needs, with no dependencies.

A count of passes is an estimate. "3 of 3" shows only that the per-trial success rate is at least 0.37 at 95% confidence; showing at least
0.90 takes 29 trials with no failure. These helpers put that in the report so a number is never read as more than it is."""
from __future__ import annotations

import math


def wilson(x: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for x successes in n trials (95% by default)."""
    if n <= 0:
        return (0.0, 1.0)
    p = x / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def lower_bound(successes: int, n: int, alpha: float = 0.05) -> float:
    """One-sided exact (Clopper-Pearson) lower bound on the per-trial success rate: with this much confidence it is at least this."""
    if n <= 0 or successes <= 0:
        return 0.0
    if successes >= n:
        return alpha ** (1 / n)
    lo, hi = 0.0, 1.0
    for _ in range(60):  # P(X >= successes | p) = alpha, solved by bisection
        mid = (lo + hi) / 2
        if 1 - _binom_cdf(successes - 1, n, mid) > alpha:
            hi = mid
        else:
            lo = mid
    return hi


def trials_for(p0: float, alpha: float = 0.05) -> int:
    """Trials with no failure needed to show the success rate is at least p0."""
    return math.ceil(math.log(alpha) / math.log(p0))


def pass_hat_k(c: int, n: int, k: int) -> float:
    """Chance that k trials drawn without replacement from n (c passed) all pass: C(c,k)/C(n,k)."""
    return math.comb(c, k) / math.comb(n, k) if n >= k else float("nan")


def claim(successes: int, n: int) -> str:
    """The sentence a pass count supports."""
    if n == 0:
        return "no trials"
    lb = lower_bound(successes, n)
    if successes == n:
        return f"no failure in {n}: per-trial success rate at least {lb:.2f} (95%)"
    return f"{n - successes} of {n} failed: per-trial success rate at least {lb:.2f} (95%)"
