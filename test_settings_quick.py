"""Scratch settings so a test run here cannot collide with the other session.

Two Claude sessions share this checkout. Running the suite twice against the
same test database deadlocks Postgres and produces phantom failures, and the
rotating file handler on Windows raises PermissionError when two processes
hold logs/info.log. A database of its own and a null log handler avoid both.

Not committed — a local convenience, not part of the project.
"""
from Hitech_BIMS.settings import *  # noqa: F401,F403

DATABASES["default"]["TEST"] = {"NAME": "test_hitech_bims_quick"}  # noqa: F405

LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"]},
}
