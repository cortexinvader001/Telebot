"""Round-robin API key pool with per-key cooldowns (429) and permanent disabling (401/403)."""
import threading
import time


class AllKeysUnavailable(RuntimeError):
    def __init__(self, wait: float | None):
        self.wait = wait
        super().__init__("All API keys are rate limited right now." if wait else "All API keys were rejected (invalid/expired).")


class KeyPool:
    def __init__(self, keys: list[str], name: str = "api"):
        if not keys:
            raise RuntimeError(f"No {name} API keys configured")
        self.keys, self.name = list(keys), name
        self._cool = [0.0] * len(keys)      # monotonic time until usable
        self._dead = [False] * len(keys)
        self._next = 0
        self._lock = threading.Lock()

    def acquire(self) -> tuple[int, str]:
        """Next usable key (round-robin so load and 429s are spread). Raises AllKeysUnavailable."""
        with self._lock:
            now = time.monotonic()
            n = len(self.keys)
            for step in range(n):
                i = (self._next + step) % n
                if not self._dead[i] and self._cool[i] <= now:
                    self._next = (i + 1) % n
                    return i, self.keys[i]
            waits = [self._cool[i] - now for i in range(n) if not self._dead[i]]
            raise AllKeysUnavailable(min(waits) if waits else None)

    def cooldown(self, index: int, seconds: float):
        with self._lock:
            self._cool[index] = max(self._cool[index], time.monotonic() + seconds)
        print(f"[{self.name}] key #{index + 1} cooling down for {seconds:.0f}s")

    def disable(self, index: int):
        with self._lock:
            self._dead[index] = True
        print(f"[{self.name}] key #{index + 1} disabled (rejected as invalid/forbidden)")

    def status(self) -> str:
        now = time.monotonic()
        return ", ".join(
            f"#{i + 1}:" + ("dead" if self._dead[i] else f"cool {self._cool[i] - now:.0f}s" if self._cool[i] > now else "ok")
            for i in range(len(self.keys)))
