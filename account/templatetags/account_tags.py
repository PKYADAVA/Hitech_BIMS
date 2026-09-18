from django import template

register = template.Library()


@register.simple_tag
def financial_years():
    """The calendar years covered by the financial years defined in Account >
    Financial Year, newest first: FY 2025-2026 and FY 2026-2027 give 2027,
    2026 and 2025. The Year a list page's filter offers, so it runs over the
    years the books do rather than an arbitrary span."""
    from account.models import FinancialYear

    years = set()
    for start, end in FinancialYear.objects.values_list("start_date", "end_date"):
        years.update(range(start.year, end.year + 1))
    return sorted(years, reverse=True)
