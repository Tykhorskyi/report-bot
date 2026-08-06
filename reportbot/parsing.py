"""Parsing of the free-form message people actually type.

Real users type "12.50 lunch with client", "€8 coffee", "1 200,50 rent" or
"12,5 taxi". All of those should work; garbage should fail with a message a
human can act on.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "₴": "UAH", "zł": "PLN"}

CURRENCY_CODES = {"EUR", "USD", "GBP", "UAH", "PLN"}

# amount, optional currency symbol/code, then the rest of the line.
# Only known currency codes are matched, so "15 gas station" keeps "gas"
# as the category instead of reading it as a currency.
_AMOUNT = re.compile(
    r"""^\s*
    (?P<symbol>[€$£₴])?\s*
    (?P<amount>\d[\d  .,]*)
    \s*(?:(?P<code>eur|usd|gbp|uah|pln|zł)\b)?
    \s*(?P<rest>.*)$""",
    re.VERBOSE | re.IGNORECASE,
)


class ParseError(ValueError):
    """Raised when a message cannot be understood."""


@dataclass(frozen=True)
class ParsedExpense:
    amount_cents: int
    currency: str
    category: str
    note: str


def normalise_number(raw: str) -> str:
    """Turn a human-written number into something float() accepts.

    Handles "1 200,50", "1,200.50", "1,500" (thousands) and "12,5" (decimal).
    The rule: the last separator is a decimal point only when it is followed
    by one or two digits and is the only one of its kind.
    """
    cleaned = raw.strip().rstrip(",.")
    for space in (" ", "\u00a0", "\u202f"):
        cleaned = cleaned.replace(space, "")

    if "," in cleaned and "." in cleaned:
        decimal_sep = "," if cleaned.rindex(",") > cleaned.rindex(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        cleaned = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
        return cleaned

    for separator in (",", "."):
        if separator in cleaned:
            head, _, tail = cleaned.rpartition(separator)
            if cleaned.count(separator) == 1 and 1 <= len(tail) <= 2:
                return f"{head}.{tail}"            # decimal
            return cleaned.replace(separator, "")  # thousands

    return cleaned


def parse_amount(text: str) -> tuple[int, str, str]:
    """Return (cents, currency, remaining text)."""
    match = _AMOUNT.match(text)
    if not match:
        raise ParseError("I could not find an amount in that message")

    raw = normalise_number(match.group("amount"))

    try:
        value = round(float(raw) * 100)
    except ValueError as exc:  # pragma: no cover - regex already constrains this
        raise ParseError(f"{raw!r} is not a number") from exc

    if value <= 0:
        raise ParseError("the amount must be greater than zero")

    currency = "EUR"
    if match.group("symbol"):
        currency = CURRENCY_SYMBOLS[match.group("symbol")]
    rest = match.group("rest").strip()

    code = match.group("code")
    if code:
        currency = "PLN" if code.lower() == "zł" else code.upper()

    return value, currency, rest


def parse_expense(text: str) -> ParsedExpense:
    """Parse '12.50 lunch with client' into structured data."""
    if not text or not text.strip():
        raise ParseError("the message is empty")

    amount_cents, currency, rest = parse_amount(text)

    if not rest:
        raise ParseError("tell me what the money went on, e.g. '12.50 lunch'")

    words = rest.split()
    category = words[0].lower().strip(".,:;")
    note = " ".join(words[1:]).strip()

    return ParsedExpense(amount_cents=amount_cents, currency=currency,
                         category=category, note=note)


def period_bounds(period: str, today: date | None = None) -> tuple[str, str]:
    """Resolve 'today' / 'week' / 'month' / 'YYYY-MM' into an inclusive range."""
    today = today or date.today()
    period = (period or "month").lower().strip()

    if period in {"today", "day"}:
        return today.isoformat(), today.isoformat()

    if period == "yesterday":
        day = today - timedelta(days=1)
        return day.isoformat(), day.isoformat()

    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()

    if period == "month":
        return today.replace(day=1).isoformat(), today.isoformat()

    if re.fullmatch(r"\d{4}-\d{2}", period):
        year, month = (int(part) for part in period.split("-"))
        if not 1 <= month <= 12:
            raise ParseError(f"{period!r} is not a valid month")
        last_day = monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"

    raise ParseError(
        f"I don't know the period {period!r}. Try: today, week, month or 2026-07"
    )


def format_money(cents: int, currency: str = "EUR") -> str:
    symbol = {"EUR": "€", "USD": "$", "GBP": "£", "UAH": "₴", "PLN": "zł"}.get(currency, "")
    amount = f"{cents / 100:,.2f}"
    return f"{symbol}{amount}" if symbol and currency != "PLN" else f"{amount} {symbol or currency}"
