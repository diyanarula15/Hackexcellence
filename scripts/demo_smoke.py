#!/usr/bin/env python3
"""Scripted rehearsal of the 12-minute judge demo against a running backend.

Usage:  python3 scripts/demo_smoke.py [--base-url http://127.0.0.1:8000]

Talks to the backend over HTTP only (standard library). Prints one line per step and exits 0 only
if every step passes. On the first failing step it prints the step, the HTTP status and a body
excerpt, then exits 1.

The rehearsal creates packages and one reservation in the backend it is pointed at, so run it
against a throwaway database (or a fresh one) right before the demo.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MENON = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350000,
}
EXCERPT_CHARS = 400


class Fail(Exception):
    """A failed step: what went wrong, and the response that shows it (when there is one)."""

    def __init__(self, message, resp=None):
        super().__init__(message)
        self.message = message
        self.resp = resp


class Resp:
    def __init__(self, status, headers, text):
        self.status = status
        self.headers = headers
        self.text = text
        try:
            self.json = json.loads(text) if text else None
        except ValueError:
            self.json = None


class Client:
    def __init__(self, base_url, timeout):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def call(self, method, path, body=None, query=None, timeout=None):
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return Resp(r.status, r.headers, r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:  # HTTPError is a URLError, so it must come first
            return Resp(e.code, e.headers, e.read().decode("utf-8", "replace"))
        except OSError as e:  # URLError, refused connection, timeout
            raise Fail(
                f"cannot reach the backend at {self.base} ({e.__class__.__name__}: {e}); start it first"
            ) from None


def expect(resp, *statuses):
    if resp.status not in statuses:
        wanted = " or ".join(str(s) for s in statuses)
        raise Fail(f"HTTP {resp.status}, expected {wanted}", resp)
    return resp.json


def check(condition, message, resp=None):
    if not condition:
        raise Fail(message, resp)


# ------------------------------------------------------------------ formatting


def inr(n):
    """Indian digit grouping: 350000 -> '₹3,50,000'."""
    if n is None:
        return "n/a"
    neg = n < 0
    digits = str(abs(int(n)))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + digits


def signed_inr(n):
    if n is None:
        return "price n/a"
    if n == 0:
        return "no price change"
    return ("+" if n > 0 else "-") + inr(abs(n))


def flights(view):
    return [i for i in view["items"] if i["type"] == "flight"]


def check_export(c, package_id):
    """GET /export, then validate the exported trip with the mode the server reports."""
    r = c.call("GET", f"/api/packages/{package_id}/export")
    trip = expect(r, 200)
    mode = r.headers.get("X-Validation-Mode")
    check(mode in ("INITIAL", "EDITED"), f"export has no usable X-Validation-Mode ({mode!r})", r)
    v = c.call("POST", "/api/validate", body=trip, query={"mode": mode})
    result = expect(v, 200)
    check(result.get("valid") is True, f"export is not valid in mode {mode}: {result.get('violations', [])[:2]}", v)
    return mode, r.headers.get("X-Trip-Valid"), trip


# ------------------------------------------------------------------ steps
# Each step returns (summary, detail lines) or raises Fail. `st` carries ids between steps.


def s_health(c, st):
    body = expect(c.call("GET", "/api/health"), 200)
    check(body and body.get("status") == "ok", "health status is not ok")
    meta = expect(c.call("GET", "/api/meta"), 200)
    st["airports"] = {a["airport"]: a.get("city") for a in meta["departure_airports"]}
    st["countries"] = {x["name"].lower(): x["name"] for x in meta["countries"]}
    details = [
        "departures: " + ", ".join(f"{code} ({city})" for code, city in st["airports"].items()),
        "countries: " + ", ".join(sorted(st["countries"].values())),
    ]
    return f"ok, {len(st['airports'])} departure airports, {len(st['countries'])} countries", details


def s_menon(c, st):
    r = c.call("POST", "/api/packages", MENON)
    body = expect(r, 201)
    check(body["status"] == "FOUND", f"status is {body['status']}, expected FOUND", r)
    view = body["package"]
    st["pkg_id"], st["view"], st["version"] = view["id"], view, view["version"]
    st["total"] = view["total_inr"]
    details = ["city plan:"]
    for s in view["city_plan"]:
        details.append(
            f"  {s['city']}: {s['check_in']} to {s['check_out']} ({s['nights']} nights), {s['hotel_name']}"
        )
    details.append("flights:")
    for f in flights(view):
        details.append(f"  {f['name']}: departs {f['start']}, lands {f['end']}, {inr(f['price_inr'])}")
    mode, trip_valid, _ = check_export(c, view["id"])
    details.append(f"export validates in mode {mode} (X-Trip-Valid {trip_valid})")
    summary = (
        f"FOUND {view['id']}, total {inr(view['total_inr'])} of {inr(view['budget_inr'])} budget "
        f"({inr(view['budget_remaining'])} left)"
    )
    return summary, details


def find_hotel_change(c, st):
    """First stay with a valid replacement hotel that the planner previews as valid."""
    pid, version = st["pkg_id"], st["version"]
    for stay in st["view"]["city_plan"]:
        opts = expect(
            c.call(
                "GET",
                f"/api/packages/{pid}/options",
                query={"kind": "hotel", "stay_id": stay["stay_id"]},
            ),
            200,
        )
        options = [a for a in opts["alternatives"] if a["valid"] and not a["current"] and a.get("command")]
        for alt in options[:5]:
            preview = expect(
                c.call("POST", f"/api/packages/{pid}/preview-change", {**alt["command"], "base_version": version}),
                200,
            )
            if preview.get("valid") and preview.get("preview_token"):
                return stay, alt, preview
    raise Fail("no stay has a valid replacement hotel")


def s_change_hotel(c, st):
    pid = st["pkg_id"]
    stay, alt, preview = find_hotel_change(c, st)
    old_version = st["version"]
    old_name = stay["hotel_name"]
    r = c.call(
        "POST",
        f"/api/packages/{pid}/apply-change",
        {**alt["command"], "base_version": old_version, "preview_token": preview["preview_token"]},
    )
    body = expect(r, 200)
    check(body.get("applied") is True, "apply-change did not report applied", r)
    new_view = body["package"]
    check(new_view["version"] == old_version + 1, f"version {old_version} -> {new_view['version']}, expected +1", r)
    new_stay = next(s for s in new_view["city_plan"] if s["stay_id"] == stay["stay_id"])
    diff = body["change"]["price_difference_inr"]
    st["view"], st["version"], st["total"] = new_view, new_view["version"], new_view["total_inr"]
    mode, _, _ = check_export(c, pid)
    check(mode == "EDITED", f"export mode is {mode} after a change, expected EDITED", r)
    summary = (
        f"{stay['city']}: {old_name} -> {new_stay['hotel_name']}, {signed_inr(diff)}, "
        f"version {old_version} -> {st['version']}"
    )
    details = [
        f"new package total {inr(new_view['total_inr'])}",
        f"export re-validates in mode {mode}",
    ]
    return summary, details


def s_delay(c, st):
    pid = st["pkg_id"]
    r = c.call("POST", f"/api/packages/{pid}/delay-scenarios", {"base_version": st["version"]})
    body = expect(r, 200)
    scenarios = body["scenarios"]
    check(len(scenarios) == 4, f"{len(scenarios)} scenarios, expected 4", r)
    after = expect(c.call("GET", f"/api/packages/{pid}"), 200)
    check(after["package"]["version"] == st["version"], "delay scenarios changed the package version", r)
    details = [
        f"+{s['delay_minutes']} min  {s['outcome']:<11} {signed_inr(s.get('price_difference_inr'))}  "
        f"{(s.get('explanation') or '')[:100]}"
        for s in scenarios
    ]
    summary = "4 simulated delays, nothing saved: " + ", ".join(
        f"+{s['delay_minutes']} {s['outcome']}" for s in scenarios
    )
    return summary, details


def s_confirm(c, st):
    pid, version = st["pkg_id"], st["version"]
    r = c.call("POST", f"/api/packages/{pid}/confirm", {"base_version": version})
    body = expect(r, 200)
    ref = body.get("reference") or ""
    check(re.fullmatch(r"[0-9]{10}", ref) is not None, f"reference {ref!r} is not 10 digits", r)
    check(body.get("total_inr") == st["total"], f"confirmed total {body.get('total_inr')} != {st['total']}", r)

    res = expect(c.call("GET", f"/api/reservations/{ref}"), 200)
    check(res.get("status") == "BOOKED", f"reservation status is {res.get('status')}", r)
    check(res.get("total_inr") == st["total"], "reservation total differs from the package total")

    ex = c.call("GET", f"/api/packages/{pid}/export")
    trip = expect(ex, 200)
    unbooked = [
        i["item_id"]
        for i in trip["items"]
        if i.get("status") != "BOOKED" or (i.get("booking") or {}).get("reference") != ref
    ]
    check(not unbooked, f"items not booked under {ref}: {unbooked}", ex)
    v = expect(c.call("POST", "/api/validate", body=trip, query={"mode": "EDITED"}), 200)
    check(v.get("valid") is True, f"booked export does not validate: {v.get('violations', [])[:2]}", v)

    again = c.call("POST", f"/api/packages/{pid}/confirm", {"base_version": version})
    check(expect(again, 200).get("reference") == ref, "confirming again did not return the same reference", again)

    st["reference"] = ref
    summary = f"reservation {ref}, BOOKED, total {inr(st['total'])}"
    details = [
        f"{len(trip['items'])} items, each BOOKED with booking.reference {ref}",
        f"confirming again returns the same reference {ref}",
    ]
    return summary, details


def s_judge_other(c, st):
    candidates = [
        {"departure": "DEL", "country": "United Arab Emirates", "start_date": "2027-04-10",
         "nights": 5, "adults": 2, "child_ages": [7], "budget": 400000},
        {"departure": "MAA", "country": "Thailand", "start_date": "2027-04-10",
         "nights": 6, "adults": 2, "child_ages": [4], "budget": 300000},
        {"departure": "BOM", "country": "Thailand", "start_date": "2027-04-10",
         "nights": 6, "adults": 2, "child_ages": [4], "budget": 300000},
    ]
    tried = []
    for body in candidates:
        label = f"{body['departure']} -> {body['country']}"
        if body["departure"] not in st["airports"] or body["country"].lower() not in st["countries"]:
            tried.append(f"{label}: not in /api/meta")
            continue
        r = c.call("POST", "/api/packages", body)
        status = r.json.get("status") if isinstance(r.json, dict) else None
        if r.status == 201 and status in ("FOUND", "OVER_BUDGET"):
            view = r.json["package"]
            summary = (
                f"{label}, children {body['child_ages']}: {status}, total {inr(view['total_inr'])} "
                f"of {inr(view['budget_inr'])} budget"
            )
            details = [f"  {s['city']}: {s['nights']} nights, {s['hotel_name']}" for s in view["city_plan"]]
            details += [f"  tried first: {t}" for t in tried]
            return summary, details
        tried.append(f"{label}: HTTP {r.status} {status or ''}".rstrip())
    raise Fail("no candidate request was FOUND or OVER_BUDGET; tried: " + "; ".join(tried))


def s_judge_budget(c, st):
    body = {**MENON, "budget": 20000}
    res = expect(c.call("POST", "/api/packages", body), 201)
    check(res["status"] == "OVER_BUDGET", f"status is {res['status']}, expected OVER_BUDGET")
    cheapest, shortfall = res.get("cheapest_total_inr"), res.get("shortfall_inr")
    check(cheapest and shortfall, "OVER_BUDGET without a cheapest total and shortfall")
    summary = (
        f"OVER_BUDGET: cheapest valid trip {inr(cheapest)}, {inr(shortfall)} over the "
        f"{inr(body['budget'])} budget"
    )
    details = list(res.get("reasons") or [])
    details += res.get("suggestions") or []
    return summary, details


def s_judge_impossible(c, st):
    body = {"departure": "BLR", "country": "Japan", "start_date": "2027-04-01", "nights": 6,
            "adults": 4, "child_ages": [3, 9], "budget": 350000}
    res = expect(c.call("POST", "/api/packages", body), 200)
    check(res["status"] == "INFEASIBLE", f"status is {res['status']}, expected INFEASIBLE")
    reasons = res.get("reasons") or []
    check(reasons, "INFEASIBLE with no reasons")
    alts_resp = c.call("POST", "/api/trip-alternatives", body)
    alts = expect(alts_resp, 200)
    suggestions = alts.get("suggestions") or []
    check(suggestions, "no alternative suggestion found", alts_resp)
    best = suggestions[0]
    priced = inr(best["min_total_inr"]) + ("" if best["within_budget"] else " (over budget)")
    summary = f"INFEASIBLE ({len(reasons)} reason(s)); nearest: {best['label']} at {priced}"
    details = [f"reason: {x}" for x in reasons]
    details.append(f"{len(suggestions)} suggestions, {alts['planner_searches']} planner searches")
    return summary, details


def s_judge_invalid(c, st):
    r = c.call("POST", "/api/packages", {**MENON, "nights": 2})
    res = expect(r, 422)
    field_errors = res.get("field_errors") or {}
    check("nights" in field_errors, f"no field error for nights; fields: {list(field_errors)}", r)
    summary = f"422 INVALID_REQUEST, field errors: {', '.join(field_errors)}"
    details = [f"{field}: {messages[0]}" for field, messages in field_errors.items()]
    return summary, details


def s_date_prices(c, st):
    for _ in range(6):  # 503 CALENDAR_BUSY means retry shortly
        r = c.call("POST", "/api/date-prices", MENON, timeout=900)
        if r.status != 503:
            break
        time.sleep(10)
    res = expect(r, 200)
    check(res.get("lowest_proven_date"), "no date in the month has a proven price", r)
    counts = res["status_counts"]
    within = sum(1 for d in res["dates"] if d.get("within_budget"))
    summary = (
        f"cheapest proven date {res['lowest_proven_date']} at {inr(res['lowest_proven_total_inr'])}; "
        f"{counts['FOUND']} FOUND, {counts['INFEASIBLE']} INFEASIBLE"
        + (f", {counts['SEARCH_INCOMPLETE']} incomplete" if counts.get("SEARCH_INCOMPLETE") else "")
    )
    details = [
        f"range {res['range_start']} to {res['range_end']}, {len(res['dates'])} dates",
        f"{within} dates within the {inr(MENON['budget'])} budget",
    ]
    return summary, details


STEPS = [
    ("1. Health and meta", s_health),
    ("2. Menon request", s_menon),
    ("3. Change a hotel", s_change_hotel),
    ("4. Delay Rescue", s_delay),
    ("5. Confirm and reservation", s_confirm),
    ("6a. Other departure and country", s_judge_other),
    ("6b. Tiny budget", s_judge_budget),
    ("6c. Impossible request", s_judge_impossible),
    ("6d. Invalid request", s_judge_invalid),
    ("7. Flexible dates", s_date_prices),
]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rehearse the holiday demo against a running backend.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds per request (default 120)")
    args = parser.parse_args(argv)

    client = Client(args.base_url, args.timeout)
    state = {}
    print(f"Holiday demo rehearsal against {client.base}")
    for name, step in STEPS:
        try:
            summary, details = step(client, state)
        except Fail as f:
            print(f"✗ {name} - {f.message}")
            if f.resp is not None:
                print(f"    HTTP {f.resp.status}")
                print("    body: " + f.resp.text[:EXCERPT_CHARS].replace("\n", " "))
            print(f"Rehearsal FAILED at step: {name}")
            return 1
        except Exception as e:  # a response shape this script does not expect
            print(f"✗ {name} - unexpected {type(e).__name__}: {e}")
            print(f"Rehearsal FAILED at step: {name}")
            return 1
        print(f"✓ {name} - {summary}")
        for line in details:
            print("    " + line)
    print(f"All {len(STEPS)} steps passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
