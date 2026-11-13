"""Attraction detail drawer API: catalog data, photo credit, image endpoint, map link.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_attraction_details.py
Reads the real data/ and images/ files; never modifies them.
"""
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.main import app

client = TestClient(app)


def _get(attraction_id: str):
    return client.get(f"/api/attractions/{attraction_id}")


def test_japan_attraction_has_image_credit_and_serves_jpeg():
    body = _get("ATT-KYO-001").json()
    assert body["country"] == "Japan"
    assert body["image_url"] == "/api/attractions/ATT-KYO-001/image"
    assert body["image_credit"] and "Martin Falbisoner" in body["image_credit"]
    assert "CC BY-SA 4.0" in body["image_credit"]

    res = client.get(body["image_url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content[:2] == b"\xff\xd8"  # JPEG start-of-image marker


def test_expanded_country_attraction_without_image_has_null_image_fields():
    body = _get("ATT-BKK-001").json()
    assert body["country"] == "Thailand"
    assert body["image_url"] is None
    assert body["image_credit"] is None
    assert client.get("/api/attractions/ATT-BKK-001/image").status_code == 404


def test_maps_url_decodes_to_name_city_country():
    body = _get("ATT-KYO-001").json()
    parts = urlsplit(body["maps_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://www.google.com/maps/search/"
    assert parse_qs(parts.query) == {"api": ["1"], "query": ["Kiyomizu-dera, Kyoto, Japan"]}


def test_child_price_null_when_absent_and_zero_kept():
    assert _get("ATT-KYO-002").json()["child_price_inr"] is None
    zero = _get("ATT-BKK-001").json()
    assert zero["child_price_inr"] == 0
    assert zero["price_per_person_inr"] == 1300


def test_unknown_id_is_404_with_error_code():
    res = _get("ATT-NOPE-999")
    assert res.status_code == 404
    assert res.json()["error"] == "ATTRACTION_NOT_FOUND"
    assert "message" in res.json()


@pytest.mark.parametrize("attempt", ["..%2F..%2Fetc%2Fpasswd", "..%2F..%2F..%2Fbackend%2Fapp%2Fconfig.py"])
def test_traversal_attempt_is_404(attempt):
    assert client.get(f"/api/attractions/{attempt}").status_code == 404
    assert client.get(f"/api/attractions/{attempt}/image").status_code == 404


def test_catalog_path_outside_images_is_never_served(monkeypatch):
    """Even if a catalog record pointed outside images/, the image endpoint must refuse it."""
    indexes = load_catalog().indexes
    record = dict(indexes.attractions_by_id["ATT-KYO-001"], image="backend/app/config.py")
    monkeypatch.setitem(indexes.attractions_by_id, "ATT-KYO-001", record)
    assert _get("ATT-KYO-001").json()["image_url"] is None
    assert client.get("/api/attractions/ATT-KYO-001/image").status_code == 404
