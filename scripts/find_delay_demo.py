#!/usr/bin/env python3
"""Search REAL catalog-generated packages for a good Delay Rescue demonstration.

Read-only: nothing in backend/, data/ or the frontend is modified, nothing is persisted. Every
number printed is computed by the app engine (build_package, simulate_arrival_delay,
exact_absorbed_tolerance, normal_violations, find_arrival_transfers).

Run from the project root:
    /Users/apple/Desktop/HackCellence/.venv/bin/python scripts/find_delay_demo.py
"""
import json
import sys
import time
from dataclasses import fields
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.catalog.load import load_catalog                       # noqa: E402
from app.engine.build import FOUND, OVER_BUDGET, WITHIN_BUDGET, build_package  # noqa: E402
from app.engine.scenario import (ABSORBED, REPAIRED, UNRECOVERABLE, exact_absorbed_tolerance,  # noqa: E402
                                 normal_violations, simulate_arrival_delay)
from app.engine.transfers import find_arrival_transfers         # noqa: E402
from app.models import TripRequest                              # noqa: E402
from app.rules.common import Party                              # noqa: E402

DELAYS = (60, 120, 180, 240)
NIGHTS = (3, 4, 5, 6)
PARTIES = ((2, []), (2, [6]))
BUDGET = 10_000_000
MAX_PACKAGES = 4480          # valid packages built (FOUND / OVER_BUDGET); >= requests, so no cap in practice
TIME_BUDGET_S = 150.0        # wall-clock guard so the run stays under ~3 minutes
EXACT = (ABSORBED, ABSORBED, REPAIRED, UNRECOVERABLE)
SHORT = {ABSORBED: "A", REPAIRED: "R", UNRECOVERABLE: "U"}


def tier_of(shape):
    """0 exact shape, 1 all three outcomes, 2 ABSORBED+REPAIRED, 3 anything else."""
    s = set(shape)
    if shape == EXACT:
        return 0
    if s == {ABSORBED, REPAIRED, UNRECOVERABLE}:
        return 1
    if {ABSORBED, REPAIRED} <= s:
        return 2
    return 3


TIER_NAME = {0: "EXACT shape", 1: "all three outcomes", 2: "ABSORBED+REPAIRED", 3: "other"}


def request_dict(req):
    return {"departure": req.departure_airport, "country": req.destination_country,
            "start_date": req.start_date.isoformat(), "nights": req.nights, "adults": req.adults,
            "child_ages": list(req.children_ages), "budget": req.budget}


def candidate_variants(pkg, cat):
    """(label, package) pairs: the built package itself, plus each real arrival-transfer option that
    passes the normal validator. Each option keeps its own computed pickup (nothing invented)."""
    out = [(None, pkg)]
    party = Party(pkg.adults, tuple(pkg.child_ages))
    options = find_arrival_transfers(pkg.arrival_flight, pkg.hotels[0], party, cat)
    for t in options:
        if t.transfer_id == pkg.arrival_transfer.transfer_id and t.pickup == pkg.arrival_transfer.pickup:
            continue                                    # identical to the saved package
        edited = pkg.with_(arrival_transfer=t)
        if normal_violations(edited, cat) == []:
            out.append((t.transfer_id, edited))
    return out


def evaluate(pkg, cat):
    results = {d: simulate_arrival_delay(pkg, d, cat) for d in DELAYS}
    shape = tuple(results[d].outcome for d in DELAYS)
    return results, shape, exact_absorbed_tolerance(pkg, cat)


def describe_items(items):
    if not items:
        return "none"
    parts = []
    for c in items:
        parts.append(f"{c.component} {c.action} ({c.price_delta:+d} INR)")
    return "; ".join(parts)


def main():
    t0 = time.perf_counter()
    cat = load_catalog()
    dest = cat.catalog.destinations
    rules = dest["rules"]
    first = date.fromisoformat(rules["data_window"]["first_night"])
    last = date.fromisoformat(rules["data_window"]["last_departure"])
    airports = sorted({d["airport"] for d in dest["departure_cities"]})
    countries = [c["code"] for c in dest["countries"]]
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]

    requests = []
    for airport in airports:
        for country in countries:
            for d in days:
                for n in NIGHTS:
                    for adults, children in PARTIES:
                        requests.append((airport, country, d, n, adults, children))
    print(f"Catalog window {first} .. {last}; {len(requests)} requests enumerated "
          f"({len(airports)} airports x {len(countries)} countries x {len(days)} dates x "
          f"{len(NIGHTS)} nights x {len(PARTIES)} parties)", flush=True)

    built = invalid = not_found = 0
    candidates = []          # dicts, in request order
    for idx, (airport, country, d, n, adults, children) in enumerate(requests):
        if built >= MAX_PACKAGES or time.perf_counter() - t0 > TIME_BUDGET_S:
            print(f"Stopping early at request {idx}/{len(requests)}: "
                  f"{'package cap' if built >= MAX_PACKAGES else 'time budget'} reached.", flush=True)
            break
        try:
            req = TripRequest(departure_airport=airport, destination_country=country, start_date=d,
                              nights=n, adults=adults, children_ages=list(children), budget=BUDGET)
        except ValueError:
            invalid += 1
            continue
        res = build_package(req, cat, objective=WITHIN_BUDGET)
        if res.status not in (FOUND, OVER_BUDGET) or res.package is None:
            not_found += 1
            continue
        built += 1
        if built % 100 == 0:
            print(f"  progress: {built} packages built, {idx + 1}/{len(requests)} requests, "
                  f"{len(candidates)} candidates, {time.perf_counter() - t0:.0f}s", flush=True)
        for label, pkg in candidate_variants(res.package, cat):
            results, shape, tol = evaluate(pkg, cat)
            candidates.append({"order": len(candidates), "req": request_dict(req), "edited": label,
                               "pkg": pkg, "results": results, "shape": shape,
                               "tier": tier_of(shape), "nights": n, "tol": tol})

    elapsed = time.perf_counter() - t0
    print(f"Built {built} packages ({invalid} invalid requests, {not_found} with no package); "
          f"{len(candidates)} candidates (including edited variants) in {elapsed:.1f}s", flush=True)

    tiers = {}
    for c in candidates:
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    for t in sorted(tiers):
        print(f"  tier {t} ({TIER_NAME[t]}): {tiers[t]} candidates")

    candidates.sort(key=lambda c: (c["tier"], c["nights"], c["order"]))
    top = candidates[:5]

    print("\n=== TOP CANDIDATES ===")
    for rank, c in enumerate(top, 1):
        pkg, req = c["pkg"], c["req"]
        first_res = c["results"][DELAYS[0]]
        print(f"\n#{rank}  [{TIER_NAME[c['tier']]}]  shape {'/'.join(SHORT[o] for o in c['shape'])}")
        print(f"  request: {json.dumps(req)}")
        if c["edited"]:
            print(f"  edited: arrival transfer {c['edited']} (CHANGE_AIRPORT_TRANSFER, item leg:arrival)")
        else:
            print("  edited: no (package exactly as the app builds it)")
        print(f"  package total: INR {pkg.total} (budget {pkg.budget})")
        print(f"  scheduled landing: {first_res.scheduled_landing}   current pickup: {first_res.original_pickup}")
        print(f"  arrival transfer: {pkg.arrival_transfer.transfer_id}   "
              f"exact_absorbed_tolerance: {c['tol'] if c['tol'] is not None else 'null'} min")
        for d in DELAYS:
            r = c["results"][d]
            print(f"  delay {d:>3} min: {r.outcome}  simulated landing {r.simulated_landing}  "
                  f"proposed pickup {r.proposed_pickup or '-'}  "
                  f"price difference {r.price_difference_inr if r.price_difference_inr is not None else '-'} INR")
            print(f"      changed items: {describe_items(r.changed_items)}")
            print(f"      removed activities: {describe_items(r.removed_activities)}")
            print(f"      explanation: {r.explanation[:160]}")

    print()
    if top and top[0]["tier"] == 0:
        best = top[0]
        print("Exact shape (ABSORBED, ABSORBED, REPAIRED, UNRECOVERABLE) found.")
    elif top:
        best = top[0]
        print("NO exact shape (ABSORBED, ABSORBED, REPAIRED, UNRECOVERABLE) exists in the searched space; "
              "closest genuine candidate shown above.")
    else:
        print("No candidates at all.")
        print("BEST: none")
        return 1
    cmd = ""
    if best["edited"]:
        cmd = (' then CHANGE_AIRPORT_TRANSFER ' + json.dumps(
            {"kind": "CHANGE_AIRPORT_TRANSFER", "item_id": "leg:arrival", "transfer_id": best["edited"]}))
    print(f"BEST: tier={TIER_NAME[best['tier']]} shape={'/'.join(SHORT[o] for o in best['shape'])} "
          f"request={json.dumps(best['req'])}"
          + (f" edited=arrival transfer {best['edited']}" if best["edited"] else " edited=no") + cmd)
    print(f"Total runtime: {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
