"""Dates that arrive in a query string, and cannot be trusted.

Supplier Ledger answered a 500. So did Customer Ledger, the Lifting report,
Chicks Placement and seventeen other pages — any of them reached with a date
that is shaped like a date but is not one. "2026-02-30" and "2026-13-45" pass
the YYYY-MM-DD pattern and then fail on the calendar, which Django reports two
different ways depending on where the string was going:

  * ``parse_date`` raises ValueError — it returns None only for something that
    was never a date at all.
  * handed straight to a queryset, the field's own validation raises
    ValidationError.

Both escape a view as a 500 on a report page, where the person was only trying
to look something up.

A date nobody could have meant is treated as one nobody typed, because that is
what every one of these reports already does with an empty box.
"""
import datetime

from django.test import SimpleTestCase

from Hitech_BIMS.entry_dates import date_from_query


class ReadingADateTests(SimpleTestCase):

    def test_a_real_date_is_read(self):
        self.assertEqual(date_from_query("2026-07-15"), datetime.date(2026, 7, 15))

    def test_a_date_that_cannot_exist_is_no_date_at_all(self):
        """The crash. Both of these match the pattern and fail the calendar."""
        self.assertIsNone(date_from_query("2026-02-30"))
        self.assertIsNone(date_from_query("2026-13-45"))

    def test_something_that_was_never_a_date_is_no_date_either(self):
        self.assertIsNone(date_from_query("notadate"))
        self.assertIsNone(date_from_query("../../etc/passwd"))

    def test_an_empty_box_is_no_filter(self):
        for blank in ("", "   ", None):
            self.assertIsNone(date_from_query(blank), repr(blank))

    def test_surrounding_space_does_not_stop_it_being_read(self):
        self.assertEqual(date_from_query("  2026-01-02  "), datetime.date(2026, 1, 2))

    def test_a_date_object_is_taken_as_it_is(self):
        """Some callers default the range to real dates before filtering. A
        helper used in eighty places has to take what it is given rather than
        assume every caller holds a string — assuming otherwise turned one
        report into a 500 the moment this was rolled out."""
        day = datetime.date(2026, 7, 15)
        self.assertEqual(date_from_query(day), day)

    def test_a_timestamp_is_narrowed_to_its_day(self):
        self.assertEqual(date_from_query(datetime.datetime(2026, 7, 15, 10, 30)),
                         datetime.date(2026, 7, 15))

    def test_it_never_raises_whatever_it_is_handed(self):
        """The whole contract. Anything that reaches a view's query string can
        reach this, and the one thing it must not do is what it used to."""
        for value in ("2026-99-99", "0000-00-00", "2026-02-30T10:00:00",
                      "9999999999-01-01", [], {}, 0, 12345, object()):
            try:
                date_from_query(value)
            except Exception as error:      # noqa: BLE001 - that is the point
                self.fail("%r raised %s" % (value, type(error).__name__))
