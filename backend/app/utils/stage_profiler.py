import time
import logging

logger = logging.getLogger(__name__)


class StageProfiler:
    def __init__(self):
        self._marks: list[tuple[str, float]] = []
        self._start: float | None = None

    def start(self):
        self._marks = [("request_received", time.perf_counter())]

    def mark(self, name: str):
        self._marks.append((name, time.perf_counter()))

    def report(self) -> str:
        if len(self._marks) < 2:
            return ""
        lines = []
        prev_ts = self._marks[0][1]
        for name, ts in self._marks[1:]:
            delta = (ts - prev_ts) * 1000
            unit = "ms" if delta < 1000 else "s"
            val = delta if delta < 1000 else delta / 1000
            lines.append(f"  {name:25s} {val:>9.1f} {unit}")
            prev_ts = ts
        total = (self._marks[-1][1] - self._marks[0][1]) * 1000
        if total >= 1000:
            lines.append(f"  {'TOTAL':25s} {total / 1000:>9.2f} s")
        else:
            lines.append(f"  {'TOTAL':25s} {total:>9.0f} ms")
        return "\n".join(lines)
