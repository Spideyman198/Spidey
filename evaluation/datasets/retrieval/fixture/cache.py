"""A small in-memory cache used by the retrieval eval fixture."""

from collections import OrderedDict


class LRUCache:
    """Fixed-capacity cache that discards the least recently used entry."""

    def __init__(self, capacity):
        self._capacity = capacity
        self._entries = OrderedDict()

    def get(self, key):
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key, value):
        self._entries[key] = value
        self._entries.move_to_end(key)
        self.evict()

    def evict(self):
        """Drop the oldest entries until the cache is back within capacity."""
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
