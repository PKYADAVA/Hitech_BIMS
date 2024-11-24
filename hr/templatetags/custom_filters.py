"""
adding custom filter parameters to th
"""
from django import template

register = template.Library()

@register.filter
def add_class(value, arg):
    """
    Adds a CSS class to a field.
    Usage: {{ form.field_name|add_class:"css_class_name" }}
    """
    return value.as_widget(attrs={'class': arg})
