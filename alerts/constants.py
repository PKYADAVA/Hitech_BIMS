"""Enumerations and constant values for the Alert & Audit module.

Everything the rest of the module keys off — actions, severities, event
types, default noise fields — lives here so there is a single, greppable
source of truth and no magic strings scattered across the codebase.
"""
from __future__ import annotations

from django.db import models


class Action(models.TextChoices):
    """The low-level CRUD/business action that produced an alert.

    ``Action`` describes *what happened to the row*; :class:`EventType`
    describes *what it means for the business*. They are intentionally
    separate so a generic ``UPDATE`` action can still map to a specific
    ``ORDER_APPROVED`` event.
    """

    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
    BULK_CREATE = "bulk_create", "Bulk Create"
    BULK_UPDATE = "bulk_update", "Bulk Update"
    BULK_DELETE = "bulk_delete", "Bulk Delete"
    SOFT_DELETE = "soft_delete", "Soft Delete"
    RESTORE = "restore", "Restore"
    STATUS_CHANGE = "status_change", "Status Change"
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"
    LOGIN = "login", "Login"
    LOGOUT = "logout", "Logout"
    LOGIN_FAILED = "login_failed", "Login Failed"
    PASSWORD_CHANGE = "password_change", "Password Change"
    FILE_UPLOAD = "file_upload", "File Upload"
    FILE_DELETE = "file_delete", "File Delete"
    CUSTOM = "custom", "Custom Business Event"


class Severity(models.TextChoices):
    """Visual/operational weight of an alert."""

    INFO = "info", "Info"
    SUCCESS = "success", "Success"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    CRITICAL = "critical", "Critical"


class EventType(models.TextChoices):
    """Business-meaningful event names.

    Extra event types can be added here, or supplied ad-hoc as free strings
    through :func:`alerts.services.emit_event` — the model stores the value
    as a plain ``CharField`` so it is never a hard constraint.
    """

    # Generic CRUD (auto-derived from Action for registered models)
    OBJECT_CREATED = "object_created", "Object Created"
    OBJECT_UPDATED = "object_updated", "Object Updated"
    OBJECT_DELETED = "object_deleted", "Object Deleted"
    OBJECT_SOFT_DELETED = "object_soft_deleted", "Object Soft Deleted"
    OBJECT_RESTORED = "object_restored", "Object Restored"
    BULK_OPERATION = "bulk_operation", "Bulk Operation"
    STATUS_CHANGED = "status_changed", "Status Changed"

    # User / auth
    USER_CREATED = "user_created", "User Created"
    USER_UPDATED = "user_updated", "User Updated"
    USER_DELETED = "user_deleted", "User Deleted"
    ROLE_CHANGED = "role_changed", "Role Changed"
    LOGIN = "login", "Login"
    LOGOUT = "logout", "Logout"
    LOGIN_FAILED = "login_failed", "Login Failed"
    PASSWORD_RESET = "password_reset", "Password Reset"

    # Files
    FILE_UPLOADED = "file_uploaded", "File Uploaded"
    FILE_DELETED = "file_deleted", "File Deleted"

    # Domain examples (extend freely)
    ORDER_CREATED = "order_created", "Order Created"
    ORDER_APPROVED = "order_approved", "Order Approved"
    ORDER_REJECTED = "order_rejected", "Order Rejected"
    DOCUMENT_PUBLISHED = "document_published", "Document Published"


# Fields that change on almost every save and carry no audit value. They are
# excluded from field-level diffs unless a model explicitly opts them back in.
DEFAULT_IGNORE_FIELDS: frozenset[str] = frozenset(
    {
        "updated_at",
        "modified",
        "modified_at",
        "last_login",
        "last_modified",
        "created_at",
        "date_created",
        "search_vector",
    }
)

# App labels whose models are framework/plumbing noise. Excluded when
# ``TRACK_ALL_MODELS`` is on so we never audit sessions, migrations, the
# admin log, content types, or the alert tables themselves (infinite loop).
DEFAULT_IGNORE_APP_LABELS: frozenset[str] = frozenset(
    {
        "admin",
        "auth",  # Permission/Group rows are noisy; User is registered explicitly.
        "contenttypes",
        "sessions",
        "migrations",
        "alerts",
    }
)

# Candidate field names treated as a "status" transition.
STATUS_FIELD_NAMES: frozenset[str] = frozenset({"status", "state", "stage", "approval_status"})

# Candidate field names treated as a soft-delete flag / timestamp.
SOFT_DELETE_BOOL_FIELDS: frozenset[str] = frozenset({"is_deleted", "deleted", "is_removed"})
SOFT_DELETE_DATE_FIELDS: frozenset[str] = frozenset({"deleted_at", "date_deleted"})

# Thread-local / contextvar key under which the active request is stashed.
REQUEST_CONTEXT_KEY = "alerts_current_request"
