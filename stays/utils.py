from datetime import datetime
from decimal import Decimal, InvalidOperation


def parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_int(value, default=0, minimum=None, maximum=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n


def parse_decimal(value, default=None):
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        return default
