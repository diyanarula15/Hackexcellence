"""Batch attraction changes: ADD_ATTRACTIONS (1..8) and REMOVE_ATTRACTIONS (1..10), one preview and one
atomic apply each.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_batch_attractions.py
Each test gets a fresh temporary database and the real catalog (Menon package). Addable attractions are
read from GET /api/packages/{id}/options, never hardcoded, so the tests follow the catalog.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.engine.schedule import open_on
from app.main import app

MENON = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}
CAT = load_catalog()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def package(client):
    r = client.post("/api/packages", json=MENON)
    assert r.status_code == 201, r.text
    return r.json()["package"]


def _get(client, pid):
    r = client.get(f"/api/packages/{pid}")
    assert r.status_code == 200
    return r.json()["package"]


def _options(client, pid, day):
    r = client.get(f"/api/packages/{pid}/options", params={"kind": "attraction", "date": day})
    assert r.status_code == 200, r.text
    return r.json()["alternatives"]


def _visits(pkg):
    return [i for i in pkg["items"] if i["item_id"].startswith("visit:")]


def _visit_ids(pkg):
    return sorted(v["item_id"] for v in _visits(pkg))


def _no_overlaps(pkg):
    spans = sorted((v["start"], v["end"]) for v in _visits(pkg))
    for (_, end_a), (start_b, _) in zip(spans, spans[1:]):
        assert end_a <= start_b, f"visits overlap: {spans}"


def _city_of(package, day):
    return next(d["city"] for d in package["days"] if d["date"] == day)


def _pick_batch(client, pid, package):
    """Three valid additions on at least two days. Paid attractions first, then free ones, at most two
    per day. Returns [(alternative, day)]."""
    days = [d["date"] for d in package["days"][:-1]]  # the departure day takes no attractions
    candidates = []
    for day in days:
        city = _city_of(package, day)
        for alt in _options(client, pid, day):
            if alt["valid"] and not alt["current"] and alt["details"]["city"] == city:
                candidates.append((alt, day))
    candidates.sort(key=lambda pair: (pair[0]["item_price_inr"] == 0, pair[1]))
    picks, per_day = [], {}
    for alt, day in candidates:
        if per_day.get(day, 0) >= 2 or alt["catalog_id"] in {a["catalog_id"] for a, _ in picks}:
            continue
        picks.append((alt, day))
        per_day[day] = per_day.get(day, 0) + 1
        if len(picks) == 3:
            break
    assert len(picks) == 3 and len({d for _, d in picks}) >= 2, picks
    return picks


def _additions(picks):
    return [{"attraction_id": alt["catalog_id"], "date": day} for alt, day in picks]


def _body(pkg, kind, **fields):
    return {"kind": kind, "base_version": pkg["version"], **fields}


def _preview(client, pid, body):
    return client.post(f"/api/packages/{pid}/preview-change", json=body)


def _apply(client, pid, body, token=None):
    payload = {**body, **({"preview_token": token} if token else {})}
    return client.post(f"/api/packages/{pid}/apply-change", json=payload)


# ------------------------------------------------------------------ three additions, one preview, one apply


def test_three_additions_across_two_days_preview_then_one_atomic_apply(client, package):
    pid = package["id"]
    picks = _pick_batch(client, pid, package)
    before = _get(client, pid)
    expected_diff = sum(alt["item_price_inr"] for alt, _ in picks)
    new_ids = {f"visit:{alt['catalog_id']}" for alt, _ in picks}

    body = _body(package, "ADD_ATTRACTIONS", additions=_additions(picks))
    r = _preview(client, pid, body)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["valid"] is True, preview["violations"]
    assert preview["kind"] == "ADD_ATTRACTIONS"
    assert preview["message"].startswith("Adding 3 attractions.")
    proposed = preview["proposed_package"]
    assert set(_visit_ids(proposed)) == set(_visit_ids(before)) | new_ids
    _no_overlaps(proposed)
    assert preview["price_difference_inr"] == expected_diff
    assert preview["new_total_inr"] - preview["old_total_inr"] == expected_diff
    added = [c for c in preview["changed_items"] if c["item_id"] in new_ids]
    assert len(added) == 3 and all(c["action"] == "ADDED" for c in added)
    assert all(c["start"] and c["end"] for c in added)
    assert preview["preview_token"]

    # the preview saved nothing
    after_preview = _get(client, pid)
    assert after_preview["version"] == package["version"]
    assert _visit_ids(after_preview) == _visit_ids(before)

    # one atomic apply: one version bump, all three saved
    applied = _apply(client, pid, body, preview["preview_token"])
    assert applied.status_code == 200, applied.text
    saved = _get(client, pid)
    assert saved["version"] == package["version"] + 1
    assert new_ids <= set(_visit_ids(saved))
    assert applied.json()["change"]["price_difference_inr"] == expected_diff


# ------------------------------------------------------------------ rejected batches save nothing


def _closed_pair(package):
    """(attraction id, day) for an attraction in the day's city that is closed on that day."""
    for day_info in package["days"][:-1]:
        for rec in CAT.indexes.attractions_by_city.get(day_info["city"], []):
            if not open_on(rec, date.fromisoformat(day_info["date"])):
                return rec["attraction_id"], day_info["date"]
    raise AssertionError("no closed attraction found in the Menon cities")


def _wrong_city_pair(package):
    first = package["days"][0]
    for rec in CAT.indexes.attractions_by_id.values():
        if rec["city"] != first["city"]:
            return rec["attraction_id"], first["date"]
    raise AssertionError("no attraction outside the first city")


@pytest.mark.parametrize("reason", ["closed", "wrong_city", "duplicate"])
def test_batch_with_one_bad_addition_is_refused_whole_and_saves_nothing(client, package, reason):
    pid = package["id"]
    picks = _pick_batch(client, pid, package)
    good = _additions(picks[:2])
    if reason == "closed":
        bad_id, bad_day = _closed_pair(package)
        needles = ("closed", "not open on")
    elif reason == "wrong_city":
        bad_id, bad_day = _wrong_city_pair(package)
        needles = ("but on",)
    else:
        planned = _visits(package)[0]
        bad_id, bad_day = planned["item_id"].removeprefix("visit:"), planned["start"][:10]
        needles = ("already in this holiday",)
    body = _body(package, "ADD_ATTRACTIONS", additions=good + [{"attraction_id": bad_id, "date": bad_day}])

    r = _preview(client, pid, body)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["valid"] is False
    assert preview["preview_token"] is None
    messages = " ".join(v["message"] for v in preview["violations"])
    assert any(n in messages for n in needles), messages
    assert CAT.indexes.attractions_by_id[bad_id]["name"] in messages

    before = _get(client, pid)
    applied = _apply(client, pid, body)
    assert applied.status_code == 422, applied.text
    assert applied.json()["error"] == "CHANGE_INVALID"
    after = _get(client, pid)
    assert after["version"] == before["version"] == package["version"]
    assert _visit_ids(after) == _visit_ids(before)


def test_batch_with_a_duplicate_id_inside_the_batch_is_invalid_input(client, package):
    body = _body(package, "ADD_ATTRACTIONS", additions=[
        {"attraction_id": "ATT-TYO-009", "date": "2027-04-10"},
        {"attraction_id": "ATT-TYO-009", "date": "2027-04-11"},
    ])
    r = _preview(client, package["id"], body)
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_CHANGE_REQUEST"
    assert "additions" in r.json()["field_errors"]


def test_batch_size_limits_are_enforced(client, package):
    pid = package["id"]
    nine = [{"attraction_id": f"ATT-X-{i}", "date": "2027-04-10"} for i in range(9)]
    assert _preview(client, pid, _body(package, "ADD_ATTRACTIONS", additions=nine)).status_code == 422
    assert _preview(client, pid, _body(package, "ADD_ATTRACTIONS", additions=[])).status_code == 422
    eleven = [f"visit:ATT-X-{i}" for i in range(11)]
    assert _preview(client, pid, _body(package, "REMOVE_ATTRACTIONS", item_ids=eleven)).status_code == 422


# ------------------------------------------------------------------ versions and booking


def test_stale_base_version_is_a_conflict_for_preview_and_apply(client, package):
    pid = package["id"]
    picks = _pick_batch(client, pid, package)
    body = {"kind": "ADD_ATTRACTIONS", "base_version": package["version"] + 5, "additions": _additions(picks)}
    r = _preview(client, pid, body)
    assert r.status_code == 409 and r.json()["error"] == "PACKAGE_VERSION_CONFLICT"
    r = _apply(client, pid, body)
    assert r.status_code == 409 and r.json()["error"] == "PACKAGE_VERSION_CONFLICT"
    assert _get(client, pid)["version"] == package["version"]


def test_booked_package_refuses_a_batch_with_409(client, package):
    pid = package["id"]
    picks = _pick_batch(client, pid, package)
    c = client.post(f"/api/packages/{pid}/confirm", json={"base_version": package["version"]})
    assert c.status_code in (200, 201), c.text
    body = _body(package, "ADD_ATTRACTIONS", additions=_additions(picks))
    r = _preview(client, pid, body)
    assert r.status_code == 409 and r.json()["error"] == "PACKAGE_ALREADY_BOOKED"
    r = _apply(client, pid, body)
    assert r.status_code == 409 and r.json()["error"] == "PACKAGE_ALREADY_BOOKED"


# ------------------------------------------------------------------ preferred start and single add


def test_explicit_preferred_start_is_honoured_when_it_fits(client, package):
    pid = package["id"]
    alt, day = _pick_batch(client, pid, package)[0]
    start_hhmm = alt["command"]["preferred_start"]  # the time the engine found free for it
    additions = [{"attraction_id": alt["catalog_id"], "date": day, "preferred_start": start_hhmm}]
    r = _preview(client, pid, _body(package, "ADD_ATTRACTIONS", additions=additions))
    assert r.status_code == 200 and r.json()["valid"] is True, r.text
    visit = next(c for c in r.json()["changed_items"] if c["item_id"] == f"visit:{alt['catalog_id']}")
    assert visit["start"] == f"{day}T{start_hhmm}:00"


def test_single_add_attraction_still_works(client, package):
    pid = package["id"]
    alt, _ = _pick_batch(client, pid, package)[0]
    body = {"base_version": package["version"], **alt["command"]}
    assert body["kind"] == "ADD_ATTRACTION"
    r = _preview(client, pid, body)
    assert r.status_code == 200 and r.json()["valid"] is True, r.text
    assert r.json()["message"].startswith("This change")  # the single-change headline is unchanged
    applied = _apply(client, pid, body, r.json()["preview_token"])
    assert applied.status_code == 200, applied.text
    assert f"visit:{alt['catalog_id']}" in _visit_ids(_get(client, pid))


# ------------------------------------------------------------------ batch removal


def test_remove_two_visits_in_one_change_validates_and_applies_once(client, package):
    pid = package["id"]
    paid = sorted(_visits(package), key=lambda v: v["price_inr"], reverse=True)
    pair = [v["item_id"] for v in paid[:2]]
    removed_total = sum(v["price_inr"] for v in paid[:2])
    assert removed_total > 0
    body = _body(package, "REMOVE_ATTRACTIONS", item_ids=pair)

    r = _preview(client, pid, body)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["valid"] is True, preview["violations"]
    assert preview["price_difference_inr"] == -removed_total
    assert not (set(pair) & set(_visit_ids(preview["proposed_package"])))
    assert {c["item_id"] for c in preview["changed_items"]} == set(pair)
    assert all(c["action"] == "REMOVED" for c in preview["changed_items"])
    assert _get(client, pid)["version"] == package["version"]

    applied = _apply(client, pid, body, preview["preview_token"])
    assert applied.status_code == 200, applied.text
    saved = _get(client, pid)
    assert saved["version"] == package["version"] + 1
    assert not (set(pair) & set(_visit_ids(saved)))


def test_remove_batch_naming_an_unplanned_visit_is_refused(client, package):
    pid = package["id"]
    planned = _visits(package)[0]["item_id"]
    body = _body(package, "REMOVE_ATTRACTIONS", item_ids=[planned, "visit:ATT-NOT-PLANNED"])
    r = _preview(client, pid, body)
    assert r.status_code == 200
    assert r.json()["valid"] is False
    assert any("ATT-NOT-PLANNED" in v["message"] for v in r.json()["violations"])
    assert _get(client, pid)["version"] == package["version"]
