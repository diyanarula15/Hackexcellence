"""Money helpers. All amounts are whole INR integers."""
CURRENCY = "INR"


def amount(price: dict) -> int:
    """Integer amount of a catalog price object {"amount", "currency"}."""
    return int(price["amount"])


def child_unit(rec: dict, adult_key: str) -> int:
    """Child unit price: child_price when present (an explicit 0 stays 0), else the adult price."""
    cp = rec.get("child_price")
    return amount(cp) if cp is not None else amount(rec[adult_key])


def inr(value: int) -> dict:
    return {"amount": int(value), "currency": CURRENCY}
