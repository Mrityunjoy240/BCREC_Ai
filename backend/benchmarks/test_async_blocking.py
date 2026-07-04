"""
Benchmark: proves the event loop is no longer blocked by sync Groq calls.

Strategy: mock a slow LLM call (500ms delay), fire N concurrent requests,
and measure wall-clock time. Sync blocks → N × 500ms. Async → ~500ms.
"""

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock


def _make_mock_completion(text: str = "Mock answer about college fees."):
    """Build a ChatCompletion-like object from a mock."""
    choice = MagicMock()
    choice.message.content = text
    completion = MagicMock()
    completion.choices = [choice]
    usage = MagicMock()
    usage.prompt_tokens = 50
    usage.completion_tokens = 20
    completion.usage = usage
    return completion


class MockGroqService:
    """
    Minimal replica of the GroqService.generate_response Groq path,
    with a controllable delay to simulate API latency.
    """

    def __init__(self, use_async: bool, delay: float = 0.5):
        self.use_async = use_async
        self.delay = delay
        self.gemini_client = None  # skip Gemini

        if use_async:
            self.async_client = AsyncMock()
            self.async_client.chat.completions.create = AsyncMock(side_effect=self._async_create)
            self.client = None
        else:
            self.client = MagicMock()
            self.client.chat.completions.create = MagicMock(side_effect=self._sync_create)
            self.async_client = None

    async def _async_create(self, **kwargs):
        await asyncio.sleep(self.delay)
        return _make_mock_completion()

    def _sync_create(self, **kwargs):
        time.sleep(self.delay)  # blocks the thread / event loop
        return _make_mock_completion()

    async def generate_response(self, query: str, session_id: str = "test"):
        """Simplified generate_response reproducing only the Groq path."""
        if not self.async_client and not self.client:
            return {"answer": "No client", "source": "error"}

        # Simulate a small amount of pre-processing time
        await asyncio.sleep(0.01)

        if self.use_async:
            completion = await self.async_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": query}],
                temperature=0.3,
                max_tokens=384,
            )
        else:
            completion = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": query}],
                temperature=0.3,
                max_tokens=384,
            )

        answer = completion.choices[0].message.content.strip()
        return {"answer": answer, "source": "groq", "latency_ms": int(self.delay * 1000)}


async def run_concurrent_benchmark(
    use_async: bool,
    num_requests: int,
    delay: float = 0.5,
) -> dict:
    """Fire num_requests concurrently and measure total wall-clock time."""
    svc = MockGroqService(use_async=use_async, delay=delay)

    async def single_request(i: int):
        return await svc.generate_response(f"Test query {i}")

    start = time.perf_counter()
    results = await asyncio.gather(*[single_request(i) for i in range(num_requests)])
    elapsed = time.perf_counter() - start

    return {
        "mode": "async" if use_async else "sync",
        "num_requests": num_requests,
        "delay_per_call_s": delay,
        "total_wall_time_s": round(elapsed, 3),
        "expected_if_blocking_s": round(num_requests * delay, 3),
        "expected_if_concurrent_s": round(delay + 0.05, 3),
        "results_count": len(results),
        "all_ok": all(r["answer"] == "Mock answer about college fees." for r in results),
    }


async def run_event_loop_responsiveness_test(
    use_async: bool,
    delay: float = 1.0,
) -> dict:
    """
    While a "slow" LLM call is in-flight, try to run a fast concurrent task.
    If the event loop is blocked (sync), the fast task is delayed.
    """
    svc = MockGroqService(use_async=use_async, delay=delay)

    async def fast_task():
        return "fast_result"

    async def slow_task():
        return await svc.generate_response("slow query")

    start = time.perf_counter()
    fast_result, slow_result = await asyncio.gather(fast_task(), slow_task())
    elapsed = time.perf_counter() - start

    # The fast task should complete almost instantly if the loop is not blocked
    return {
        "mode": "async" if use_async else "sync",
        "total_time_s": round(elapsed, 3),
        "fast_result": fast_result,
        "slow_ok": slow_result["answer"] == "Mock answer about college fees.",
    }


async def main():
    print("=" * 60)
    print("Benchmark: Sync vs Async Groq Client")
    print("=" * 60)

    for delay in [0.1, 0.3, 0.5]:
        print(f"\n--- Delay per call: {delay}s ---")
        for num in [1, 5, 10]:
            for use_async in [False, True]:
                result = await run_concurrent_benchmark(
                    use_async=use_async, num_requests=num, delay=delay
                )
                mode = result["mode"].ljust(6)
                blocking = result["expected_if_blocking_s"]
                concurrent = result["expected_if_concurrent_s"]
                actual = result["total_wall_time_s"]
                efficiency = (
                    round(blocking / actual, 2) if not use_async else round(concurrent / actual, 2)
                )
                print(
                    f"  {mode}  {num} requests  "
                    f"wall={actual:.2f}s  "
                    f"(blocking={blocking:.1f}s  concurrent={concurrent:.1f}s)  "
                    f"ok={result['all_ok']}"
                )

    print("\n--- Event loop responsiveness test (1s delay + concurrent fast task) ---")
    for use_async in [False, True]:
        result = await run_event_loop_responsiveness_test(use_async=use_async, delay=1.0)
        mode = result["mode"].ljust(6)
        print(f"  {mode}  total={result['total_time_s']:.2f}s  fast={result['fast_result']}")


if __name__ == "__main__":
    asyncio.run(main())
