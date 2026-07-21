import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Hitech_BIMS.settings")
django.setup()

import json
import re
from django.conf import settings
settings.ALLOWED_HOSTS.append("testserver")
from django.test import Client
from django.contrib.auth import get_user_model
from hatchery.models import EggGrading, TraySetting
from hatchery_master.models import Hatchery, Setter

User = get_user_model()
user = User.objects.filter(is_superuser=True).first()
client = Client()
client.force_login(user)

hatchery = Hatchery.objects.filter(is_active=True).first()
setter = Setter.objects.filter(is_active=True, hatchery=hatchery).first() or Setter.objects.filter(is_active=True).first()
grading = EggGrading.objects.filter(purchase_invoice__isnull=False).order_by("-date", "-id").first()

ts_payload = {
    "hatchery": hatchery.id, "setting_date": "2026-06-01", "grading": grading.id,
    "lines": [{"setter": setter.id, "no_trays": "10", "tray_size": "30", "total_eggs": "300", "eggs_set": "300"}],
}
resp = client.post("/tray_set_api/", data=json.dumps(ts_payload), content_type="application/json")
assert resp.status_code == 201, resp.json()
ts_id = resp.json()["id"]
print("Created TraySetting", ts_id, "with setter", setter.setter_no)

resp = client.get("/hatch-entry/add/")
content = resp.content.decode()
assert resp.status_code == 200

# Extract the traySettings JS array literal and confirm this ts's lines are present
match = re.search(r"const traySettings = (\[.*?\]);", content, re.DOTALL)
assert match, "could not find traySettings JS array in page"
tray_settings = json.loads(match.group(1))
entry = next((t for t in tray_settings if t["id"] == ts_id), None)
assert entry, f"tray setting {ts_id} not found in traySettings payload"
print("tray_settings entry lines:", entry["lines"])
assert entry["lines"] == [{"setter_no": setter.setter_no, "eggs_set": "300.00"}]

print("\nALL CHECKS PASSED")
TraySetting.objects.filter(pk=ts_id).delete()
print("Cleaned up.")
