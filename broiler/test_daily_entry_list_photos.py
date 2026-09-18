"""Daily Entry register: each entry carries its photos for the thumbnails.

The per-category DailyEntryPhoto rows are the full set; an entry saved before
they existed has its pictures only in mort_image / cull_image / feed_image. A
row's first photo is mirrored into its field under the same file name, so it
must not be listed twice.
"""
import shutil
import tempfile
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry, DailyEntryPhoto,
                            Farmer, Region, Supervisor)

MEDIA = tempfile.mkdtemp()


def png(name):
    return SimpleUploadedFile(name, b"\x89PNG\r\n\x1a\n", content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class DailyEntryListPhotoTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=Farmer.objects.create(farmer_name="S. Yadav"),
            region="East", line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.today = date(2026, 7, 23)
        batch = BroilerBatch.objects.create(broiler_farm=farm, start_date=self.today - timedelta(days=5))
        self.entry = DailyEntry.objects.create(farm=farm, batch=batch, supervisor=supervisor,
                                               date=self.today, mortality=2)
        self.client.force_login(get_user_model().objects.create_superuser(
            "deadmin", "d@x.com", "Str0ngPass!"))

    def photos(self):
        rows = self.client.get("/daily_entry_api/", {"from_date": self.today.isoformat(),
                                                      "to_date": self.today.isoformat()}).json()
        return [(p["kind"], p["label"]) for p in rows[0]["photos"]]

    def test_an_entry_with_no_photos_has_none(self):
        self.assertEqual(self.photos(), [])

    def test_an_older_entry_shows_its_single_field_photos(self):
        self.entry.mort_image = png("mort.png")
        self.entry.feed_image = png("feed.png")
        self.entry.save()
        self.assertEqual(self.photos(), [("mortality", "Mortality"), ("feed", "Feed")])

    def test_a_mirrored_first_photo_is_listed_once(self):
        for kind in ("mortality", "mortality", "feed_2", "culls"):
            DailyEntryPhoto.objects.create(entry=self.entry, kind=kind, image=png(kind + ".png"))
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.mort_image)   # mirrored from the first mortality row
        self.assertEqual([k for k, _ in self.photos()],
                         ["mortality", "mortality", "culls", "feed_2"])
