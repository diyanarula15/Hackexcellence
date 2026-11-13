"""DatePriceCache (Phase 7A): keys, reuse, invalidation, settled-only storage, immutability, LRU bound.

Planners are mocked; catalogs are tiny synth worlds. Every test uses its own fresh cache.
"""

import copy
import dataclasses
from datetime import date
from types import SimpleNamespace

import pytest

from app.engine.build import FOUND as PLAN_FOUND, SEARCH_INCOMPLETE as PLAN_INCOMPLETE
from app.services.date_price_cache import (PLANNER_VERSION, DatePriceCache, cache_key,
                                           catalog_fingerprint, is_cacheable, requirements_key)
from app.services.date_prices import (FOUND, SEARCH_INCOMPLETE, SEARCH_LIMIT, DatePriceResult,
                                      calculate_date_price)
from synth import INR, request, simple_world

D = date(2027, 4, 10)


def planned(total, *, complete=True, status=PLAN_FOUND):
    return SimpleNamespace(status=status, package=SimpleNamespace(total=total), cheapest_total=total,
                           budget_remaining=None, shortfall=None, reasons=[], search_complete=complete,
                           reason_codes=[], stats=SimpleNamespace(combinations_evaluated=1))


class FakePlanner:
    def __init__(self, fn=None):
        self.fn = fn or (lambda req: planned(1500))
        self.calls = []

    def __call__(self, req, catalog, objective):
        self.calls.append(req)
        return self.fn(req)


def settled(d, total, fp="fp", reqs=("HOM", "ZZ", 3, 2, ())):
    return DatePriceResult(d, FOUND, total, True, fp, reqs)


def lookup(req, d, cat, cache, planner):
    return calculate_date_price(req, d, cat, cache=cache, planner=planner)


@pytest.fixture
def cat():
    return simple_world().loaded()


# ------------------------------------------------------------------ reuse and keys

def test_identical_request_is_a_cache_hit_and_planner_runs_once(cat):
    cache, fake = DatePriceCache(), FakePlanner()
    first = lookup(request(), D, cat, cache, fake)
    second = lookup(request(), D, cat, cache, fake)
    assert len(fake.calls) == 1
    assert second is first
    assert cache.stats.hits == 1 and cache.stats.misses == 1


def test_budget_is_not_part_of_the_key(cat):
    cache, fake = DatePriceCache(), FakePlanner()
    lookup(request(budget=5000), D, cat, cache, fake)
    again = lookup(request(budget=10 ** 9), D, cat, cache, fake)
    assert len(fake.calls) == 1
    assert again.status == FOUND


def test_different_adults_gives_different_key(cat):
    cache, fake = DatePriceCache(), FakePlanner()
    lookup(request(adults=2), D, cat, cache, fake)
    lookup(request(adults=3), D, cat, cache, fake)
    assert len(fake.calls) == 2
    assert len(cache) == 2


def test_child_ages_are_order_insensitive_but_content_sensitive(cat):
    assert requirements_key("HOM", "ZZ", 3, 2, (10, 5)) == requirements_key("HOM", "ZZ", 3, 2, (5, 10))
    assert requirements_key("HOM", "ZZ", 3, 2, (5, 10)) != requirements_key("HOM", "ZZ", 3, 2, (5,))

    cache, fake = DatePriceCache(), FakePlanner()
    lookup(request(children=(10, 5)), D, cat, cache, fake)
    lookup(request(children=(5, 10)), D, cat, cache, fake)
    assert len(fake.calls) == 1
    lookup(request(children=(5,)), D, cat, cache, fake)
    assert len(fake.calls) == 2


def test_different_date_gives_different_key(cat):
    cache, fake = DatePriceCache(), FakePlanner()
    lookup(request(), date(2027, 4, 10), cat, cache, fake)
    lookup(request(), date(2027, 4, 11), cat, cache, fake)
    assert len(fake.calls) == 2
    assert cache_key("fp", ("HOM", "ZZ", 3, 2, ()), date(2027, 4, 10)) != \
        cache_key("fp", ("HOM", "ZZ", 3, 2, ()), date(2027, 4, 11))


def test_key_contains_planner_version_and_catalog_fingerprint():
    key = cache_key("fp", ("HOM", "ZZ", 3, 2, ()), D)
    assert key[0] == "fp" and key[1] == PLANNER_VERSION


# ------------------------------------------------------------------ catalog fingerprint and invalidation

def test_different_catalog_contents_give_different_fingerprint():
    w1 = simple_world()
    w2 = simple_world()
    w2.rooms[0]["price_per_night"] = INR(999)           # one price changed
    fp1, fp2 = catalog_fingerprint(w1.loaded()), catalog_fingerprint(w2.loaded())
    assert fp1 != fp2


def test_switching_fingerprint_drops_old_entries():
    cat1 = simple_world().loaded()
    w2 = simple_world()
    w2.rooms[0]["price_per_night"] = INR(999)
    cat2 = w2.loaded()
    cache, fake = DatePriceCache(), FakePlanner()

    lookup(request(), D, cat1, cache, fake)
    lookup(request(), date(2027, 4, 11), cat1, cache, fake)
    assert len(cache) == 2

    fp2 = catalog_fingerprint(cat2)
    assert cache.get(cache_key(fp2, ("HOM", "ZZ", 3, 2, ()), D)) is None
    assert len(cache) == 0
    assert cache.stats.invalidations >= 2

    lookup(request(), D, cat2, cache, fake)
    assert len(fake.calls) == 3          # the new catalog was searched again, not served from the old one


def test_fingerprint_is_stable_for_same_object_and_equal_for_two_loads():
    w = simple_world()
    loaded = w.loaded()
    assert catalog_fingerprint(loaded) == catalog_fingerprint(loaded)
    assert catalog_fingerprint(w.loaded()) == catalog_fingerprint(loaded)


# ------------------------------------------------------------------ settled-only storage

def test_search_incomplete_is_not_stored(cat):
    cache = DatePriceCache()
    incomplete = DatePriceResult(D, SEARCH_INCOMPLETE, None, False, "fp", ("HOM", "ZZ", 3, 2, ()),
                                 SEARCH_LIMIT)
    assert cache.put(cache_key("fp", ("HOM", "ZZ", 3, 2, ()), D), incomplete) is False
    assert len(cache) == 0
    assert cache.stats.skipped_incomplete == 1


def test_repeat_of_incomplete_search_calls_planner_again(cat):
    cache = DatePriceCache()
    fake = FakePlanner(lambda req: planned(None, complete=False, status=PLAN_INCOMPLETE))
    first = lookup(request(), D, cat, cache, fake)
    second = lookup(request(), D, cat, cache, fake)
    assert first.status == SEARCH_INCOMPLETE and second.status == SEARCH_INCOMPLETE
    assert len(fake.calls) == 2
    assert len(cache) == 0


def test_found_without_proof_is_not_cacheable():
    unproven = SimpleNamespace(status=FOUND, proven_minimum=False, min_total_inr=1500)
    assert is_cacheable(unproven) is False
    assert is_cacheable(settled(D, 1500)) is True


# ------------------------------------------------------------------ immutability and bound

def test_cache_operations_do_not_mutate_the_request(cat):
    req = request(children=(5, 10))
    before = copy.deepcopy(vars(req))
    cache, fake = DatePriceCache(), FakePlanner()
    lookup(req, D, cat, cache, fake)
    lookup(req, D, cat, cache, fake)
    assert vars(req) == before


def test_cached_result_is_frozen(cat):
    result = lookup(request(), D, cat, DatePriceCache(), FakePlanner())
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.min_total_inr = 1


def test_lru_keeps_only_the_most_recent_entries():
    cache = DatePriceCache(max_entries=3)
    reqs = ("HOM", "ZZ", 3, 2, ())
    keys = [cache_key("fp", reqs, date(2027, 4, d)) for d in (1, 2, 3, 4)]
    for k, d in zip(keys, (1, 2, 3, 4)):
        assert cache.put(k, settled(date(2027, 4, d), 1000 + d)) is True
    assert len(cache) == 3
    assert cache.get(keys[0]) is None
    assert all(cache.get(k) is not None for k in keys[1:])
    assert cache.stats.evictions == 1
