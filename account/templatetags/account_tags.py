from django import template

register = template.Library()


@register.simple_tag
def financial_years():
    """The financial years defined in Account > Financial Year, newest first:
    the Year a list page's filter offers, so it runs over the books' years
    rather than calendar ones."""
    from account.models import FinancialYear

    return FinancialYear.objects.order_by("-start_date")
