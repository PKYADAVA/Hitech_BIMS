from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def indian_currency(value):
    """Format a number with Indian digit grouping and 2 decimals,
    e.g. 12548200 -> "1,25,48,200.00". Returns the input unchanged if it
    can't be parsed."""
    if value in (None, ""):
        return value
    try:
        value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if value < 0 else ""
    value = abs(value)
    int_part = int(value)
    dec_part = f"{(value - int_part):.2f}".split(".")[1]
    s = str(int_part)
    if len(s) <= 3:
        grouped = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join(parts) + "," + tail
    return f"{sign}{grouped}.{dec_part}"
