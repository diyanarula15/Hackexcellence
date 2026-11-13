"""In-memory, catalog-aware cache for proven per-date minimum prices (Price Landscape, Phase 7A).

Key = (catalog fingerprint, planner version, departure, country code, nights, adults,
       sorted child ages, start date).  The traveler's budget is NOT part of the key: the cheapest
possible holiday does not depend on how much the traveler wants to spend.

* Only settled answers are cached: FOUND with a proven minimum and INFEASIBLE with a completed
  search. SEARCH_INCOMPLETE is never stored, so the next request tries again.
* Values are frozen dataclasses, so a cached result cannot be mutated by a caller.
* The cache is bounded (LRU). When a different catalog fingerprint is seen, every entry made
  under another fingerprint is dropped, so an expanded or edited catalog never serves stale prices.
* Thread-safe: FastAPI runs the sync route in a worker thread.
"""

import hashlib
import json
import threading
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field, fields, is_dataclass

PLANNER_VERSION = "phase3-minimum-cost-v1"   # bump when the planner's pricing semantics change
DEFAULT_MAX_ENTRIES = 5000

_fp_lock = threading.Lock()
_fingerprints: dict[int, tuple] = {}   # id(loaded) -> (weakref to it, fingerprint); Loaded is unhashable


def _forget(key: int) -> None:
    with _fp_lock:
        _fingerprints.pop(key, None)


def catalog_fingerprint(loaded) -> str:
    """Stable SHA-256 of the catalog CONTENTS (all 8 datasets), memoized per loaded catalog object.

    Content, not a path: the same directory can hold a different (e.g. expanded) catalog between
    runs. The catalog is treated as read-only while loaded; a new load gives a new object and so a
    freshly computed fingerprint.
    """
    with _fp_lock:
        entry = _fingerprints.get(id(loaded))
        if entry is not None and entry[0]() is loaded:
            return entry[1]
    raw = loaded.catalog
    payload = {f.name: getattr(raw, f.name) for f in fields(raw)} if is_dataclass(raw) else dict(vars(raw))
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    with _fp_lock:
        _fingerprints[id(loaded)] = (weakref.ref(loaded), digest)
    weakref.finalize(loaded, _forget, id(loaded))
    return digest


def requirements_key(departure: str, country_code: str, nights: int, adults: int,
                     child_ages) -> tuple:
    """Everything about the traveler that can change the price - and nothing else (no budget)."""
    return (departure.strip().upper(), country_code.strip().upper(), int(nights), int(adults),
            tuple(sorted(int(a) for a in child_ages)))


def cache_key(fingerprint: str, requirements: tuple, start_date) -> tuple:
    return (fingerprint, PLANNER_VERSION, requirements, start_date.isoformat())


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stores: int = 0
    skipped_incomplete: int = 0
    evictions: int = 0
    invalidations: int = 0


@dataclass
class DatePriceCache:
    max_entries: int = DEFAULT_MAX_ENTRIES
    _data: OrderedDict = field(default_factory=OrderedDict)
    _fingerprint: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    stats: CacheStats = field(default_factory=CacheStats)

    def _switch_catalog(self, fingerprint: str) -> None:
        """Drop everything computed under another catalog (caller holds the lock)."""
        if self._fingerprint != fingerprint:
            if self._data:
                self.stats.invalidations += len(self._data)
                self._data.clear()
            self._fingerprint = fingerprint

    def get(self, key: tuple):
        with self._lock:
            self._switch_catalog(key[0])
            value = self._data.get(key)
            if value is None:
                self.stats.misses += 1
                return None
            self._data.move_to_end(key)
            self.stats.hits += 1
            return value

    def put(self, key: tuple, result) -> bool:
        """Store a settled result. Returns False (and stores nothing) for an unsettled one."""
        if not is_cacheable(result):
            with self._lock:
                self.stats.skipped_incomplete += 1
            return False
        with self._lock:
            self._switch_catalog(key[0])
            self._data[key] = result
            self._data.move_to_end(key)
            self.stats.stores += 1
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
                self.stats.evictions += 1
        return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._fingerprint = None

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


def is_cacheable(result) -> bool:
    status = getattr(result, "status", None)
    if status == "FOUND":
        return bool(getattr(result, "proven_minimum", False)) and isinstance(result.min_total_inr, int)
    return status == "INFEASIBLE"


# the process-wide cache used by the API
CACHE = DatePriceCache()
