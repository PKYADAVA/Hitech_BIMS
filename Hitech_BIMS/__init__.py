"""
Hitech_BIMS project initialization.

This module initializes the Celery application for the project.
"""
from __future__ import absolute_import, unicode_literals

# Import the Celery app
from .celery import app as celery_app

# Make the Celery app available when importing the package
__all__ = ("celery_app",)
