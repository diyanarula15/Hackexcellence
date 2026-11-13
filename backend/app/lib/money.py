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


def rupees(value: int) -> str:
    """Indian digit grouping for messages: 215544 -> '₹2,15,544', -1200 -> '-₹1,200'."""
    digits = str(abs(int(value)))
    head, tail = digits[:-3], digits[-3:]
    while len(head) > 2:
        head, tail = head[:-2], f"{head[-2:]},{tail}"
    return ("-" if value < 0 else "") + "₹" + (f"{head},{tail}" if head else tail)
