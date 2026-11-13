"""Planner benchmark on the real catalog. Run from backend/:  ../.venv/bin/python scripts/bench_planner.py"""
import sys, time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.catalog.load import load_catalog
from app.engine.build import build_package
from app.export.to_trip import to_trip_json
from app.validate.validate_trip import validate_trip

cat = load_catalog()
d = cat.catalog.destinations
last = date.fromisoformat(d["rules"]["data_window"]["last_departure"])
first = date.fromisoformat(d["rules"]["data_window"]["first_night"])
rows, status, invalid = [], Counter(), 0
for home in [c["airport"] for c in d["departure_cities"]]:
    for co in d["countries"]:
        for nights in (3, 6, 10):
            for start in (first, first + timedelta(days=4), last - timedelta(days=nights)):
                for party in ((2, []), (2, [6]), (4, [3, 9])):
                    for obj in ("WITHIN_BUDGET", "MINIMUM_COST"):
                        req = SimpleNamespace(departure_airport=home, destination_country=co["code"],
                                              start_date=start, nights=nights, adults=party[0],
                                              children_ages=party[1], budget=10_000_000)
                        t = time.perf_counter()
                        r = build_package(req, cat, obj)
                        ms = (time.perf_counter() - t) * 1000
                        status[(obj, r.status)] += 1
                        if r.package and validate_trip(to_trip_json(r.package, cat), cat, "INITIAL"):
                            invalid += 1
                        rows.append((obj, ms, r.stats))
for obj in ("WITHIN_BUDGET", "MINIMUM_COST"):
    ms = sorted(m for o, m, _ in rows if o == obj)
    st = [s for o, _, s in rows if o == obj]
    print(f"{obj}: {len(ms)} searches  median {ms[len(ms)//2]:.1f} ms  p95 {ms[int(len(ms)*.95)]:.1f} ms  "
          f"max {ms[-1]:.1f} ms")
    print(f"   max city plans {max(s.city_plans for s in st)}, max flight triples {max(s.flight_pairs for s in st)}, "
          f"max hotel options {max(s.hotel_options for s in st)}, max combinations evaluated "
          f"{max(s.combinations_evaluated for s in st)}, max branches pruned {max(s.branches_pruned for s in st)}, "
          f"validator rejections {sum(s.validator_rejections for s in st)}")
print("outcomes:", dict(status))
print("returned packages failing the validator:", invalid)
