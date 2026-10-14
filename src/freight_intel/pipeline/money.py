"""Turn printed text such as 'EUR 1.234,56' into integers and dates.

The LLM only COPIES text off the page ("2.190,00"). Everything numeric happens
here, in plain code, so a number can't be hallucinated into existence and the
rules are testable ("LLM reads, software decides").
"""
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "PKR", "AED", "CNY", "SGD", "JPY", "INR", "CHF"}
_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

# Deliberately NO slash formats: 05/10/2026 could be 5 Oct or May 10, and a
# wrong guess is worse than flagging the document for a human.
_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d.%m.%Y", "%B %d, %Y", "%b %d, %Y")


def parse_money(text: str | None) -> int | None:
    """'EUR 1.234,56' | '$1,234.56' | '1 234.56' | '2960' -> minor units (cents).

    Returns None when no amount can be read; it never guesses a zero.
    """
    if text is None:
        return None
    s = str(text).strip()
    negative = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    # Keep only digits and separators. Letters, currency symbols and spaces
    # (used as thousands separators: "1 234.56") all disappear.
    cleaned = re.sub(r"[^\d,.]", "", s)
    if not re.search(r"\d", cleaned):
        return None

    has_comma, has_dot = "," in cleaned, "." in cleaned
    if has_comma and has_dot:
        # The separator that appears LAST is the decimal point: 1.234,56 or 1,234.56
        decimal_sep = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        cleaned = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        parts = cleaned.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            # 1,234,567 or 1.234 -> separators group thousands
            cleaned = "".join(parts)
        else:
            cleaned = parts[0] + "." + parts[1]  # 1234,56 -> decimal comma

    try:
        minor = int((Decimal(cleaned) * 100).to_integral_value(ROUND_HALF_UP))
    except InvalidOperation:
        return None
    return -minor if negative else minor


def format_minor(minor: int) -> str:
    """The inverse of parse_money: 504000 -> '5,040.00'.

    Assumes 2 decimal places, like parse_money (a few currencies, e.g. JPY or KWD, differ).
    """
    return f"{minor / 100:,.2f}"


def parse_date(text: str | None) -> date | None:
    """'05.10.2026' | '10 Aug 2026' | 'August 10, 2026' | '2026-08-10' -> date."""
    if not text:
        return None
    s = " ".join(str(text).split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_currency(text: str | None) -> str | None:
    """'usd' | '$' | 'EUR' -> 'USD' | 'USD' | 'EUR'. None if unknown."""
    if not text:
        return None
    s = str(text).strip()
    if s in _SYMBOLS:
        return _SYMBOLS[s]
    code = s.upper()
    return code if code in KNOWN_CURRENCIES else None
