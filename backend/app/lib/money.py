"""Money helpers. All amounts are whole INR."""
CURRENCY = "INR"


def amount(price: dict) -> int:
    """Extract the integer amount from a catalog price object {"amount", "currency"}."""
    return int(price["amount"])


def inr(value: int) -> dict:
    return {"amount": int(value), "currency": CURRENCY}
