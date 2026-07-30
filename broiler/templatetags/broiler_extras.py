from django import template

register = template.Library()


@register.filter
def slot_files(files_by_slot, code):
    """The attachments held in one capture slot.

    Django templates cannot index a dict by a loop variable, and the capture
    form needs exactly that to show each slot's file under its own upload
    input. Returns an empty list for a slot with nothing in it.
    """
    if not files_by_slot:
        return []
    return files_by_slot.get(code) or []
