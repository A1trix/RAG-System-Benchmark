from __future__ import annotations

import math
import random
import statistics
from typing import Optional

def mean_sd(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    xs = [float(x) for x in values if x is not None and not math.isnan(float(x))]
    if not xs:
        return None, None
    if len(xs) == 1:
        return xs[0], 0.0
    return statistics.fmean(xs), statistics.stdev(xs)

def bootstrap_mean_ci(values: list[float], iters: int, seed: int, alpha: float = 0.05) -> tuple[Optional[float], Optional[float]]:
    xs = [float(x) for x in values if x is not None and not math.isnan(float(x))]
    if not xs:
        return None, None
    if len(xs) == 1 or iters <= 0:
        return xs[0], xs[0]
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(iters):
        sample = [xs[rng.randrange(n)] for __ in range(n)]
        means.append(statistics.fmean(sample))
    means.sort()
    lo_i = int(math.floor((alpha / 2.0) * (len(means) - 1)))
    hi_i = int(math.ceil((1.0 - alpha / 2.0) * (len(means) - 1)))
    return means[lo_i], means[hi_i]

def linear_fit(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """Return (intercept, slope, sse) for y = a + b x."""
    n = len(x)
    if n == 0:
        return 0.0, 0.0, 0.0
    if n == 1:
        return float(y[0]), 0.0, 0.0
    xbar = statistics.fmean(x)
    ybar = statistics.fmean(y)
    sxx = sum((xi - xbar) ** 2 for xi in x)
    if sxx <= 0:
        b = 0.0
    else:
        sxy = sum((xi - xbar) * (yi - ybar) for xi, yi in zip(x, y))
        b = sxy / sxx
    a = ybar - b * xbar
    sse = sum((yi - (a + b * xi)) ** 2 for xi, yi in zip(x, y))
    return a, b, sse
