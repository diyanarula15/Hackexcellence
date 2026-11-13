"""Content identity of the read-only source catalog, independent of its filesystem path."""
import hashlib
import json
from dataclasses import asdict


def catalog_fingerprint(catalog) -> str:
    payload = json.dumps(asdict(catalog.catalog), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()
