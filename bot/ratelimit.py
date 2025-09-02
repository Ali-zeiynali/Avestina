# bot_friend/ratelimit.py
import time
from collections import defaultdict, deque

class RateLimiter:
    def __init__(self, window_seconds: int, limit: int):
        self.window = window_seconds
        self.limit = limit
        self._times: dict[int, deque] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.time()
        q = self._times[user_id]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
