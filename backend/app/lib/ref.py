"""Opaque reservation references. Keep these as text to preserve leading zeroes."""
import secrets


def generate_reference() -> str:
    return f"{secrets.randbelow(10**10):010d}"
