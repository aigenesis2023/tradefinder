"""
download_pool.py — Parallel Download Architecture with Rate Limiting
====================================================================

Provides a thread-safe download pool with token-bucket rate limiting
for parallel data acquisition from SEC EDGAR, Yahoo Finance, and other
data sources.

SEC allows 10 requests/second per IP. Yahoo Finance has no documented
limit but benefits from parallelization for multi-ticker downloads.

Usage:
    pool = DownloadPool(max_workers=8, rate_limit=10.0)
    results = pool.map(fetch_func, items)
    # results is a list of (item, result_or_exception) tuples
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Tokens refill at `rate` tokens per second, up to `capacity` tokens.
    Each acquire() call consumes one token, blocking if none are available.
    """

    def __init__(self, rate: float = 10.0, capacity: Optional[float] = None):
        self.rate = rate
        self.capacity = capacity or rate
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Acquire one token, blocking if necessary.

        Returns the wait time in seconds (0 if token was immediately available).
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0

            # Not enough tokens — compute wait time
            wait = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
            return wait


@dataclass
class PoolResult:
    """Result from a download pool operation."""
    item: Any
    result: Optional[Any] = None
    error: Optional[Exception] = None

    @property
    def success(self) -> bool:
        return self.error is None


class DownloadPool:
    """Thread pool executor with rate-limited parallel downloads.

    Args:
        max_workers: Maximum number of concurrent download threads.
        rate_limit: Maximum requests per second (aggregate across all threads).
        retries: Number of retries for failed items.
        retry_delay: Base delay between retries (exponential backoff).
    """

    def __init__(
        self,
        max_workers: int = 8,
        rate_limit: float = 10.0,
        retries: int = 2,
        retry_delay: float = 1.0,
    ):
        self.max_workers = max_workers
        self.rate_limiter = TokenBucket(rate=rate_limit)
        self.retries = retries
        self.retry_delay = retry_delay
        self._executor: Optional[ThreadPoolExecutor] = None

    def __enter__(self):
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self

    def __exit__(self, *args):
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None

    def map(
        self,
        func: Callable[[T], R],
        items: List[T],
        desc: str = "downloads",
    ) -> List[PoolResult]:
        """Execute func(item) for each item in parallel with rate limiting.

        Args:
            func: Function to apply to each item. Receives a single item.
            items: List of items to process.
            desc: Description for log messages.

        Returns:
            List of PoolResult, one per input item (preserves order).
        """
        if not items:
            return []

        if self._executor is None:
            raise RuntimeError("DownloadPool must be used as a context manager")

        n = len(items)
        logger.info(f"Starting {n} parallel {desc} ({self.max_workers} workers, "
                     f"{self.rate_limiter.rate:.0f} req/s limit)")

        # Submit all tasks
        futures: Dict[Future, int] = {}
        for idx, item in enumerate(items):
            future = self._executor.submit(self._execute_with_retry, func, item)
            futures[future] = idx

        # Collect results in order
        results: List[Optional[PoolResult]] = [None] * n
        completed = 0
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = PoolResult(item=items[idx], error=e)
            completed += 1
            if completed % max(1, n // 10) == 0:
                logger.info(f"  {completed}/{n} {desc} completed")

        # Log summary
        success_count = sum(1 for r in results if r and r.success)
        error_count = n - success_count
        if error_count > 0:
            logger.warning(f"  {desc}: {success_count}/{n} succeeded, {error_count} failed")
        else:
            logger.info(f"  {desc}: all {n} succeeded")

        # Ensure we return exactly one result per input item.
        # If any position is still None (should not happen), create an error result.
        final_results = []
        for i, r in enumerate(results):
            if r is not None:
                final_results.append(r)
            else:
                final_results.append(PoolResult(
                    item=items[i],
                    error=RuntimeError(f"Result for item {i} was not set")
                ))
        return final_results

    def _execute_with_retry(self, func: Callable[[T], R], item: T) -> PoolResult:
        """Execute func with rate limiting and retry on failure."""
        last_error = None
        for attempt in range(self.retries + 1):
            # Rate limit before each attempt
            wait = self.rate_limiter.acquire()
            if wait > 0:
                time.sleep(wait)

            try:
                result = func(item)
                return PoolResult(item=item, result=result)
            except Exception as e:
                last_error = e
                if attempt < self.retries:
                    backoff = self.retry_delay * (2 ** attempt)
                    logger.debug(f"Retry {attempt + 1}/{self.retries} for {item} "
                                 f"after {backoff:.1f}s: {e}")
                    time.sleep(backoff)

        return PoolResult(item=item, error=last_error)
