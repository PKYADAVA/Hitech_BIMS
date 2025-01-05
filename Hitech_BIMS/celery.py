from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Hitech_BIMS.settings")

app = Celery("Hitech_BIMS")

# Configure Celery using Django settings with a 'CELERY_' namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatically discover tasks in installed apps.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
