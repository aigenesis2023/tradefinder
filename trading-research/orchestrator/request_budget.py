import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal

# Hard limits per run
# LLM raised from 40 → 100: with 15 candidates the pipeline uses ~4 calls each
# (Bull, Bear, 1C, Synthesis); 40 was below the floor and silently disqualified
# late candidates when the supervisor's budget-exhausted default is DISQUALIFIED.
BUDGET = {
    "llm": 100,
    "market_data": 20,
    "firecrawl": 15,
    "sec_edgar": 5,
    "total": 140,
}

RATE_LIMIT_RPM = 5  # requests per minute across all sources

ApiSource = Literal["llm", "market_data", "firecrawl", "sec_edgar"]


@dataclass
class BudgetManager:
    dry_run: bool = False
    _counts: dict = field(default_factory=lambda: {"llm": 0, "market_data": 0, "firecrawl": 0, "sec_edgar": 0})
    _total: int = 0
    _semaphore: asyncio.Semaphore = field(default=None)
    _last_request_times: list = field(default_factory=list)
    _dry_run_estimates: dict = field(default_factory=lambda: {"llm": 0, "market_data": 0, "firecrawl": 0, "sec_edgar": 0})

    def __post_init__(self):
        self._semaphore = asyncio.Semaphore(RATE_LIMIT_RPM)

    def estimate(self, source: ApiSource, count: int = 1):
        """Register an estimated call for dry-run mode."""
        self._dry_run_estimates[source] = self._dry_run_estimates.get(source, 0) + count

    def dry_run_summary(self) -> str:
        total = sum(self._dry_run_estimates.values())
        lines = ["=== DRY RUN â API CALL ESTIMATE ==="]
        for src, count in self._dry_run_estimates.items():
            budget = BUDGET[src]
            status = "OK" if count <= budget else "OVER BUDGET"
            lines.append(f"  {src:15s}: {count:3d} / {budget:3d}  [{status}]")
        lines.append(f"  {'TOTAL':15s}: {total:3d} / {BUDGET['total']:3d}  [{'OK' if total <= BUDGET['total'] else 'OVER BUDGET'}]")
        return "\n".join(lines)

    def can_call(self, source: ApiSource, count: int = 1) -> bool:
        if self._counts[source] + count > BUDGET[source]:
            return False
        if self._total + count > BUDGET["total"]:
            return False
        return True

    def remaining(self, source: ApiSource) -> int:
        return BUDGET[source] - self._counts[source]

    def total_remaining(self) -> int:
        return BUDGET["total"] - self._total

    def _register(self, source: ApiSource, count: int = 1):
        self._counts[source] += count
        self._total += count

    async def _enforce_rate_limit(self):
        """Allow at most RATE_LIMIT_RPM calls per 60-second window."""
        now = time.monotonic()
        self._last_request_times = [t for t in self._last_request_times if now - t < 60]
        if len(self._last_request_times) >= RATE_LIMIT_RPM:
            oldest = self._last_request_times[0]
            wait = 60 - (now - oldest)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request_times.append(time.monotonic())

    async def call(self, source: ApiSource, fn, *args, **kwargs):
        """
        Execute an async or sync callable within budget and rate limits.
        Returns None if budget exhausted.
        Retries once on transient failure without consuming extra budget.
        """
        if self.dry_run:
            self.estimate(source)
            return None

        if not self.can_call(source):
            print(f"[BUDGET] {source} budget exhausted ({self._counts[source]}/{BUDGET[source]})")
            return None

        async with self._semaphore:
            await self._enforce_rate_limit()
            self._register(source)
            try:
                if asyncio.iscoroutinefunction(fn):
                    return await fn(*args, **kwargs)
                else:
                    return fn(*args, **kwargs)
            except Exception as e:
                # Single retry without consuming additional budget
                try:
                    await asyncio.sleep(2)
                    if asyncio.iscoroutinefunction(fn):
                        return await fn(*args, **kwargs)
                    else:
                        return fn(*args, **kwargs)
                except Exception as retry_e:
                    print(f"[BUDGET] {source} call failed after retry: {retry_e}")
                    return None

    def summary(self) -> str:
        lines = ["=== API BUDGET SUMMARY ==="]
        for src, count in self._counts.items():
            budget = BUDGET[src]
            lines.append(f"  {src:15s}: {count:3d} / {budget:3d} used")
        lines.append(f"  {'TOTAL':15s}: {self._total:3d} / {BUDGET['total']:3d} used")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "llm_calls": self._counts["llm"],
            "market_data_calls": self._counts["market_data"],
            "firecrawl_calls": self._counts["firecrawl"],
            "sec_edgar_calls": self._counts["sec_edgar"],
            "total_calls": self._total,
            "budget": BUDGET["total"],
        }
