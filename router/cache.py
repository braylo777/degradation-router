"""Exact and semantic response caches.

The semantic cache uses hashed character-trigram vectors and cosine similarity. It is a
lexical approximation of an embedding model, chosen so the repo runs offline with no
model download. Swap `embed()` for a real embedding call in production.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from collections import OrderedDict
from typing import Callable

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub("", text.lower())).strip()


class ExactCache:
    def __init__(self, max_items: int = 1000, ttl_s: float = 3600, clock: Callable[[], float] = time.monotonic):
        self.max_items, self.ttl_s, self.clock = max_items, ttl_s, clock
        self._d: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self.hits = self.misses = 0

    @staticmethod
    def key(prompt: str) -> str:
        return hashlib.sha256(normalize(prompt).encode()).hexdigest()

    def get(self, prompt: str) -> str | None:
        k = self.key(prompt)
        item = self._d.get(k)
        if item is None or self.clock() - item[0] > self.ttl_s:
            if item is not None:
                del self._d[k]
            self.misses += 1
            return None
        self._d.move_to_end(k)
        self.hits += 1
        return item[1]

    def put(self, prompt: str, value: str) -> None:
        k = self.key(prompt)
        self._d[k] = (self.clock(), value)
        self._d.move_to_end(k)
        while len(self._d) > self.max_items:
            self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)


DIM = 512


def embed(text: str) -> list[float]:
    t = f"  {normalize(text)}  "
    v = [0.0] * DIM
    for i in range(len(t) - 2):
        h = int.from_bytes(hashlib.blake2b(t[i : i + 3].encode(), digest_size=4).digest(), "little")
        v[h % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class SemanticCache:
    def __init__(self, threshold: float = 0.85, max_items: int = 1000):
        self.threshold, self.max_items = threshold, max_items
        self._items: list[tuple[list[float], str, str]] = []
        self.hits = self.misses = 0

    def get(self, prompt: str) -> tuple[str, float, str] | None:
        """Return (value, similarity, matched_prompt) for the best match >= threshold."""
        q = embed(prompt)
        best, best_s = None, -1.0
        for vec, val, src in self._items:
            s = cosine(q, vec)
            if s > best_s:
                best, best_s = (val, src), s
        if best is not None and best_s >= self.threshold:
            self.hits += 1
            return best[0], round(best_s, 4), best[1]
        self.misses += 1
        return None

    def put(self, prompt: str, value: str) -> None:
        self._items.append((embed(prompt), value, prompt))
        if len(self._items) > self.max_items:
            self._items.pop(0)

    def __len__(self) -> int:
        return len(self._items)
