"""The share link staff are given to install the Android app.

One address that survives a release — a link to the APK itself changes name
every build, and the one written on a WhatsApp message does not.

The page is deliberately public: whoever is installing has no session on their
phone's browser yet, and gating the download behind a login they can only reach
through the app is a circle. It must therefore keep working for an anonymous
visitor, which is the thing most likely to be broken by a future middleware.
"""
from django.test import TestCase, override_settings
from django.urls import reverse


class AppDownloadTests(TestCase):
    def url(self):
        return reverse("app_download")

    def test_an_anonymous_visitor_can_open_it(self):
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Hi Tech BIMS")

    @override_settings(APK_DOWNLOAD_URL="https://cdn.example.com/bims-0.3.0.apk",
                       APK_VERSION="0.3.0")
    def test_it_offers_the_configured_build(self):
        resp = self.client.get(self.url())
        self.assertContains(resp, "https://cdn.example.com/bims-0.3.0.apk")
        self.assertContains(resp, "Version 0.3.0")
        self.assertContains(resp, "Download the app")

    @override_settings(APK_DOWNLOAD_URL="", APK_VERSION="")
    def test_with_nothing_published_it_says_so_rather_than_offering_a_dead_button(self):
        """A button that downloads nothing gets reported as "the app is
        broken"; saying the build is not published gets it published."""
        resp = self.client.get(self.url())
        if b"Download the app" in resp.content:
            self.skipTest("an APK is present in static/app on this machine")
        self.assertContains(resp, "No build published yet")

    @override_settings(APK_DOWNLOAD_URL="https://cdn.example.com/bims.apk")
    def test_it_names_the_server_the_app_will_talk_to(self):
        """Staff install this from more than one deployment; the page has to
        say which one they are about to point their phone at."""
        resp = self.client.get(self.url())
        self.assertContains(resp, "testserver")

    @override_settings(APK_DOWNLOAD_URL="https://cdn.example.com/bims.apk")
    def test_it_tells_them_what_android_will_ask(self):
        """The install fails silently for anyone who does not know to allow
        unknown sources, and they report it as a broken download."""
        resp = self.client.get(self.url())
        self.assertContains(resp, "allow installing from this browser")

    def test_it_stands_alone_rather_than_extending_the_signed_in_chrome(self):
        """No navbar full of pages an anonymous visitor cannot reach."""
        resp = self.client.get(self.url())
        self.assertNotContains(resp, "main_top_navbar")
        self.assertNotContains(resp, "Logout")

    @override_settings(APK_DOWNLOAD_URL="http://insecure.example.com/bims.apk")
    def test_an_http_build_on_an_https_page_is_called_out(self):
        """Browsers refuse a download that leaves HTTPS for HTTP, in a strip
        people miss — and report as "the download does nothing"."""
        resp = self.client.get(self.url(), secure=True)
        self.assertContains(resp, "This download will be blocked")

    @override_settings(APK_DOWNLOAD_URL="https://secure.example.com/bims.apk")
    def test_an_https_build_is_not_called_out(self):
        resp = self.client.get(self.url(), secure=True)
        self.assertNotContains(resp, "This download will be blocked")

    @override_settings(APK_DOWNLOAD_URL="http://insecure.example.com/bims.apk")
    def test_plain_http_serving_is_left_alone(self):
        """On a development server there is no mixed content to warn about."""
        resp = self.client.get(self.url())
        self.assertNotContains(resp, "This download will be blocked")
