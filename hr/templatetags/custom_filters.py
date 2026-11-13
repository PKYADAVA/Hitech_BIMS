"""Template filters for HR screens."""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

_ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
         "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
         "Sixteen", "Seventeen", "Eighteen", "Nineteen")
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
         "Eighty", "Ninety")


def _under_hundred(n):
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _under_thousand(n):
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_under_hundred(rest))
    return " ".join(parts)


def _indian_words(n):
    """Whole number to words on the Indian scale — crore, lakh, thousand.

    A payslip is read by the person it pays, so it groups the way they
    count: 1,25,000 reads "One Lakh Twenty Five Thousand", not "One
    Hundred Twenty Five Thousand".
    """
    if n == 0:
        return "Zero"
    parts = []
    for divisor, label in ((10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand")):
        chunk, n = divmod(n, divisor)
        if chunk:
            parts.append(f"{_under_thousand(chunk)} {label}")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(p for p in parts if p)


@register.filter
def rupees_in_words(value):
    """``1234.50`` -> "Rupees One Thousand Two Hundred Thirty Four and Fifty Paise Only".

    Returns an empty string for anything that is not a number, so a blank
    field on a payslip stays blank rather than printing an error.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if amount < 0:
        return ""
    amount = amount.quantize(Decimal("0.01"))
    whole = int(amount)
    paise = int((amount - whole) * 100)
    words = f"Rupees {_indian_words(whole)}"
    if paise:
        words += f" and {_under_hundred(paise)} Paise"
    return words + " Only"
