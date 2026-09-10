"""Initials for the navbar avatar.

The account pill carries no username any more, so the two letters on it are the
whole of what says whose session this is. They have to be right for accounts
that carry a full name and for the many that carry only a login.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase

from user.templatetags.user_extras import display_name, initials


class InitialsTests(TestCase):
    def user(self, **fields):
        return get_user_model()(**fields)

    def test_a_first_and_last_name_give_one_letter_each(self):
        self.assertEqual(initials(self.user(username="akash", first_name="Akash",
                                            last_name="Jaiswal")), "AJ")

    def test_a_first_name_alone_gives_two_of_its_letters(self):
        """One letter reads as an error rather than as a name."""
        self.assertEqual(initials(self.user(username="akash", first_name="Akash")), "AK")

    def test_a_login_only_account_falls_back_to_the_username(self):
        """Most accounts here have no name filled in, so this is the common
        case rather than the edge one."""
        self.assertEqual(initials(self.user(username="admin")), "AD")

    def test_a_username_written_as_two_words_is_read_as_a_name(self):
        for username, expected in (("ram.prasad", "RP"),
                                   ("ram_prasad", "RP"),
                                   ("ram prasad", "RP")):
            self.assertEqual(initials(self.user(username=username)), expected, username)

    def test_a_single_letter_username_does_not_crash(self):
        self.assertEqual(initials(self.user(username="a")), "A")

    def test_the_result_is_always_upper_case(self):
        self.assertEqual(initials(self.user(username="akash", first_name="akash",
                                            last_name="jaiswal")), "AJ")

    def test_whitespace_around_a_name_is_not_an_initial(self):
        self.assertEqual(initials(self.user(username="x", first_name="  Akash  ",
                                            last_name="  Jaiswal ")), "AJ")


class NoUserTests(SimpleTestCase):
    def test_an_anonymous_visitor_gets_a_placeholder_not_a_blank_disc(self):
        """The navbar renders before anyone signs in. An empty circle looks
        like a page that failed to load; a question mark looks deliberate."""
        self.assertEqual(initials(AnonymousUser()), "?")
        self.assertEqual(initials(None), "?")

    def test_display_name_is_empty_rather_than_a_placeholder(self):
        """It heads the menu and fills a tooltip, where a stray '?' would read
        as the name of the account."""
        self.assertEqual(display_name(AnonymousUser()), "")
        self.assertEqual(display_name(None), "")


class DisplayNameTests(TestCase):
    def test_the_full_name_wins(self):
        u = get_user_model()(username="akash", first_name="Akash", last_name="Jaiswal")
        self.assertEqual(display_name(u), "Akash Jaiswal")

    def test_the_username_stands_in_when_there_is_no_name(self):
        self.assertEqual(display_name(get_user_model()(username="admin")), "admin")

    def test_a_half_filled_name_does_not_leave_a_dangling_space(self):
        u = get_user_model()(username="akash", first_name="Akash")
        self.assertEqual(display_name(u), "Akash")
