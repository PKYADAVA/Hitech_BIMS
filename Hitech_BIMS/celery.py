"""
Celery configuration for Hitech_BIMS project.
"""
from __future__ import absolute_import, unicode_literals
import os
import logging
from celery import Celery
from celery.signals import after_setup_logger

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Hitech_BIMS.settings")

# Create Celery app
app = Celery("Hitech_BIMS")

# Configure Celery using Django settings with a 'CELERY_' namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatically discover tasks in installed apps.
app.autodiscover_tasks()


@after_setup_logger.connect
def setup_loggers(logger, *args, **kwargs):
    """Configure Celery logging."""
    formatter = logging.Formatter(
        '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
    )
    
    # Add file handler
    file_handler = logging.FileHandler('logs/celery.log')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to verify Celery is working."""
    logger = logging.getLogger(__name__)
    logger.info(f"Request: {self.request!r}")
    return "Celery is working!"
