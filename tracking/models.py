# pylint: disable=no-member
"""Database schema for the Employee Tracking module.

Provider-agnostic GPS tracking storage. The sync pipeline (management
command → provider adapter → these tables) is the only writer for
provider-sourced rows; the UI and reports read exclusively from here and
never call the GPS vendor directly.

Table map (Meta.db_table is set explicitly so the physical names match the
approved schema):

    employee_tracking_provider      TrackingProvider   (vendor config, encrypted creds)
    employee_tracking_employee_map  EmployeeProviderMapping (ERP employee ↔ vendor id)
    employee_tracking_sync          TrackingSync       (one row per sync run)
    employee_live_location          EmployeeLiveLocation (current position, 1 row/employee)
    employee_location_history       EmployeeLocationHistory (raw GPS pings, high volume)
    employee_route                  EmployeeRoute      (per-employee daily summary)
    employee_route_points           EmployeeRoutePoint (ordered stops/legs of a route)
    employee_customer_visit         EmployeeCustomerVisit (CRM visit records)
    employee_geofence               EmployeeGeofence   (office/farm/customer fences)
    employee_tracking_logs          TrackingLog        (append-only events + alerts)
    employee_tracking_settings      TrackingSettings   (singleton runtime config)

Scale notes: ``employee_location_history`` is the only unbounded-growth table.
It carries a composite ``(employee, recorded_at)`` B-tree for per-employee
timelines and a BRIN index on ``recorded_at`` for cheap date-range scans, and
has no inbound foreign keys, so it can be converted to monthly range
partitions (pg_partman or a raw-SQL migration) without touching the rest of
the schema. Dashboards read the pre-aggregated ``employee_route`` /
``employee_live_location`` tables, never the raw pings.
"""

from django.contrib.auth.models import User
from django.contrib.postgres.indexes import BrinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from hr.models import Employee
from inventory.models import Warehouse
from sales.models import Customer

from .fields import EncryptedTextField

# Reused by every latitude/longitude column: ~0.11 m precision, validated range.
LAT_VALIDATORS = [MinValueValidator(-90), MaxValueValidator(90)]
LNG_VALIDATORS = [MinValueValidator(-180), MaxValueValidator(180)]


def _lat_field(**kwargs):
    return models.DecimalField(
        max_digits=9, decimal_places=6, validators=LAT_VALIDATORS, **kwargs
    )


def _lng_field(**kwargs):
    return models.DecimalField(
        max_digits=9, decimal_places=6, validators=LNG_VALIDATORS, **kwargs
    )


class AuditModel(models.Model):
    """Standard audit columns, matching the notification-app convention."""

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    modified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TrackingProvider(AuditModel):
    """A configured GPS-tracking vendor (TrackoLap today; pluggable).

    ``provider_type`` selects the adapter class in ``tracking.providers``;
    everything the adapter needs to talk to the vendor lives on this row, so
    switching or adding vendors is configuration, not code. All credential
    fields are encrypted at rest (see ``tracking.crypto``). Editable from the
    Tracking Settings page and the Django admin — never from ``.env``.
    """

    PROVIDER_CHOICES = [
        ("trackolap", "TrackoLap"),
        ("geopunch", "GeoPunch"),
        ("traccar", "Traccar"),
        ("custom", "Custom API"),
    ]
    SYNC_STATUS_CHOICES = [
        ("never", "Never Synced"),
        ("ok", "OK"),
        ("error", "Error"),
    ]

    name = models.CharField(
        max_length=100, unique=True, help_text="Display name, e.g. 'TrackoLap Production'."
    )
    provider_type = models.CharField(
        max_length=20, choices=PROVIDER_CHOICES, default="trackolap", db_index=True
    )
    api_url = models.URLField(
        max_length=255, help_text="Vendor API base URL, no trailing endpoint path."
    )
    username = models.CharField(max_length=150, blank=True)
    password = EncryptedTextField(
        blank=True, help_text="Stored encrypted; never rendered back to the browser."
    )
    access_token = EncryptedTextField(
        blank=True, help_text="Static/refreshed API token, stored encrypted."
    )
    api_key = EncryptedTextField(
        blank=True, help_text="API key for key-based vendors, stored encrypted."
    )
    refresh_interval_seconds = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(15)],
        help_text="How often the background sync pulls live locations.",
    )
    webhook_url = models.URLField(
        max_length=255, blank=True,
        help_text="Inbound webhook endpoint registered with the vendor (optional).",
    )
    webhook_secret = EncryptedTextField(
        blank=True, help_text="Shared secret used to verify webhook signatures."
    )
    priority = models.PositiveSmallIntegerField(
        default=1, help_text="Sync order when several providers are active; lower runs first."
    )
    is_active = models.BooleanField(
        default=True, help_text="Inactive providers are skipped by the background sync."
    )
    extra_config = models.JSONField(
        default=dict, blank=True,
        help_text="Provider-specific options the adapter understands (non-secret only).",
    )
    last_sync_status = models.CharField(
        max_length=10, choices=SYNC_STATUS_CHOICES, default="never", editable=False
    )
    last_synced_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error = models.TextField(blank=True, editable=False)

    class Meta:
        db_table = "employee_tracking_provider"
        ordering = ("priority", "id")
        verbose_name = "Tracking Provider"

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"


class EmployeeProviderMapping(models.Model):
    """Maps an ERP employee to their identity inside one provider.

    Vendors key people by their own IDs; this table is the join the sync uses
    to attribute pings/visits to ``hr.Employee`` rows without ever modifying
    the HR schema.
    """

    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.CASCADE, related_name="employee_mappings"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="tracking_mappings"
    )
    external_id = models.CharField(
        max_length=100, help_text="Employee identifier inside the provider."
    )
    external_name = models.CharField(
        max_length=150, blank=True, help_text="Name as known to the provider (diagnostic aid)."
    )
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(
        null=True, blank=True, help_text="Last time the provider reported data for this identity."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "employee_tracking_employee_map"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"], name="uq_tracking_map_provider_external"
            ),
            models.UniqueConstraint(
                fields=["provider", "employee"], name="uq_tracking_map_provider_employee"
            ),
        ]
        verbose_name = "Employee Provider Mapping"

    def __str__(self):
        return f"{self.employee} ↔ {self.provider.name}:{self.external_id}"


class TrackingSync(models.Model):
    """One row per background-sync run (per provider, per data kind).

    The scheduler command creates the row when a run starts and finalises it
    with counters and status. ``window_start``/``window_end`` record the
    incremental cursor actually used, so the next run can resume from
    ``window_end`` and a failed window can be replayed exactly.
    """

    SYNC_TYPE_CHOICES = [
        ("live", "Live Locations"),
        ("history", "Location History"),
        ("attendance", "Attendance Events"),
        ("visits", "Customer Visits"),
        ("geofences", "Geofences"),
        ("employees", "Employee Directory"),
    ]
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]
    TRIGGER_CHOICES = [
        ("scheduler", "Scheduler"),
        ("manual", "Manual"),
        ("webhook", "Webhook"),
    ]

    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.CASCADE, related_name="sync_runs"
    )
    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="running")
    triggered_by = models.CharField(max_length=10, choices=TRIGGER_CHOICES, default="scheduler")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    window_start = models.DateTimeField(
        null=True, blank=True, help_text="Start of the incremental window fetched by this run."
    )
    window_end = models.DateTimeField(
        null=True, blank=True, help_text="End of the incremental window; next run resumes here."
    )
    records_fetched = models.PositiveIntegerField(default=0)
    records_created = models.PositiveIntegerField(default=0)
    records_updated = models.PositiveIntegerField(default=0)
    records_skipped = models.PositiveIntegerField(
        default=0, help_text="Duplicates and rows for unmapped employees."
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "employee_tracking_sync"
        ordering = ("-started_at",)
        indexes = [
            models.Index(
                fields=["provider", "sync_type", "-started_at"],
                name="ix_tracking_sync_prov_type",
            ),
        ]
        verbose_name = "Tracking Sync Run"

    def __str__(self):
        return f"{self.provider.name} {self.sync_type} @ {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class EmployeeLiveLocation(models.Model):
    """Current position of one employee — exactly one row per employee.

    Overwritten in place by every live sync, so the live dashboard is a
    single indexed table scan regardless of history volume.
    """

    STATUS_CHOICES = [
        ("online", "Online"),
        ("idle", "Idle"),
        ("moving", "Moving"),
        ("offline", "Offline"),
        ("unknown", "Unknown"),
    ]

    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="live_location"
    )
    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    latitude = _lat_field()
    longitude = _lng_field()
    accuracy_m = models.FloatField(null=True, blank=True, help_text="GPS accuracy in metres.")
    speed_kmh = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True, help_text="Bearing in degrees (0–360).")
    altitude_m = models.FloatField(null=True, blank=True)
    address = models.TextField(blank=True, help_text="Reverse-geocoded address, if resolved.")
    battery_pct = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(100)]
    )
    network = models.CharField(
        max_length=30, blank=True, help_text="Device network state, e.g. 'wifi', '4g', 'none'."
    )
    gps_enabled = models.BooleanField(default=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="unknown", db_index=True
    )
    is_checked_in = models.BooleanField(
        default=False, help_text="Mirrors today's attendance state for dashboard tiles."
    )
    current_customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Customer whose geofence/visit the employee is currently inside.",
    )
    recorded_at = models.DateTimeField(
        db_index=True, help_text="Device-side timestamp of this position (GPS fix)."
    )
    heartbeat_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Last device heartbeat. Vendors refresh the GPS fix only on "
                  "movement, so online/offline is judged by the freshest of "
                  "fix and heartbeat.",
    )
    synced_at = models.DateTimeField(auto_now=True, help_text="When the ERP last updated this row.")

    class Meta:
        db_table = "employee_live_location"
        verbose_name = "Employee Live Location"

    def __str__(self):
        return f"{self.employee} @ {self.latitude},{self.longitude} ({self.status})"


class EmployeeLocationHistory(models.Model):
    """Raw GPS pings — append-only, high volume (millions of rows).

    Duplicate prevention is structural: ``(employee, recorded_at)`` is unique,
    and provider-supplied point IDs are additionally unique per provider, so
    replaying a sync window can never double-insert. Kept free of inbound FKs
    so it can be range-partitioned by month later without schema surgery.
    """

    EVENT_CHOICES = [
        ("ping", "Ping"),
        ("stop", "Stop"),
        ("idle", "Idle"),
        ("check_in", "Check In"),
        ("check_out", "Check Out"),
    ]

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="location_history"
    )
    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    latitude = _lat_field()
    longitude = _lng_field()
    accuracy_m = models.FloatField(null=True, blank=True)
    speed_kmh = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    altitude_m = models.FloatField(null=True, blank=True)
    battery_pct = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(100)]
    )
    event_type = models.CharField(max_length=10, choices=EVENT_CHOICES, default="ping")
    address = models.TextField(blank=True)
    external_id = models.CharField(
        max_length=100, blank=True, help_text="Provider's ID for this point, when it supplies one."
    )
    recorded_at = models.DateTimeField(help_text="Device-side timestamp of the ping.")
    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "employee_location_history"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "recorded_at"], name="uq_loc_hist_employee_time"
            ),
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                condition=~models.Q(external_id=""),
                name="uq_loc_hist_provider_external",
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "recorded_at"], name="ix_loc_hist_emp_time"),
            BrinIndex(fields=["recorded_at"], name="brin_loc_hist_recorded_at"),
        ]
        verbose_name = "Location History Point"
        verbose_name_plural = "Location History"

    def __str__(self):
        return f"{self.employee_id} @ {self.recorded_at:%Y-%m-%d %H:%M:%S}"


class EmployeeRoute(models.Model):
    """Per-employee, per-day travel summary — the unit reports read.

    Built/refreshed by the sync pipeline from raw pings, so distance and time
    aggregates never require scanning ``employee_location_history`` at
    report time.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="tracking_routes")
    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    date = models.DateField(db_index=True)
    total_distance_km = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    travel_time = models.DurationField(null=True, blank=True)
    idle_time = models.DurationField(null=True, blank=True)
    average_speed_kmh = models.FloatField(null=True, blank=True)
    max_speed_kmh = models.FloatField(null=True, blank=True)
    stops_count = models.PositiveSmallIntegerField(default=0)
    points_count = models.PositiveIntegerField(default=0, help_text="Raw pings behind this summary.")
    first_point_at = models.DateTimeField(null=True, blank=True)
    last_point_at = models.DateTimeField(null=True, blank=True)
    start_address = models.TextField(blank=True)
    end_address = models.TextField(blank=True)
    polyline = models.TextField(
        blank=True,
        help_text="Encoded polyline (Google polyline algorithm) for map replay.",
    )
    is_finalized = models.BooleanField(
        default=False, help_text="True once the day is over and the summary is complete."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "employee_route"
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="uq_route_employee_date"),
        ]
        ordering = ("-date",)
        verbose_name = "Employee Route"

    def __str__(self):
        return f"{self.employee} — {self.date} ({self.total_distance_km} km)"


class EmployeeRoutePoint(models.Model):
    """Ordered legs/stops of a daily route, for timeline and replay views.

    A simplified sequence (stops, idle periods, travel legs) — not every raw
    ping — so a day renders in a handful of rows.
    """

    POINT_TYPE_CHOICES = [
        ("travel", "Travel"),
        ("stop", "Stop"),
        ("idle", "Idle"),
        ("visit", "Customer Visit"),
        ("check_in", "Check In"),
        ("check_out", "Check Out"),
    ]

    route = models.ForeignKey(EmployeeRoute, on_delete=models.CASCADE, related_name="points")
    sequence = models.PositiveSmallIntegerField(help_text="Order of this leg within the day.")
    point_type = models.CharField(max_length=10, choices=POINT_TYPE_CHOICES, default="travel")
    latitude = _lat_field()
    longitude = _lng_field()
    address = models.TextField(blank=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Set when the stop was matched to a customer location/visit.",
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    distance_from_previous_km = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )

    class Meta:
        db_table = "employee_route_points"
        constraints = [
            models.UniqueConstraint(fields=["route", "sequence"], name="uq_route_point_sequence"),
        ]
        ordering = ("route", "sequence")
        verbose_name = "Route Point"

    def __str__(self):
        return f"{self.route_id}#{self.sequence} {self.point_type}"


class EmployeeCustomerVisit(models.Model):
    """A field visit to a CRM customer, with GPS evidence.

    FKs to ``sales.Customer`` so visit history can be embedded in the
    existing Customer Master page. ``PROTECT`` on customer: visit records are
    audit evidence and must not vanish when a customer row is deleted.
    """

    STATUS_CHOICES = [
        ("planned", "Planned"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("missed", "Missed"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="customer_visits")
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="tracking_visits",
        null=True, blank=True,
        help_text="Matched CRM customer; empty when the vendor-side customer "
                  "has no CRM counterpart yet (see external_customer_name).",
    )
    external_customer_name = models.CharField(
        max_length=255, blank=True,
        help_text="Customer name as reported by the provider, kept for "
                  "matching/repair when no CRM customer was found.",
    )
    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    visit_date = models.DateField(db_index=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="completed")
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    check_in_latitude = _lat_field(null=True, blank=True)
    check_in_longitude = _lng_field(null=True, blank=True)
    check_out_latitude = _lat_field(null=True, blank=True)
    check_out_longitude = _lng_field(null=True, blank=True)
    address = models.TextField(blank=True)
    photo = models.ImageField(
        upload_to="visit_photos/", null=True, blank=True,
        help_text="Locally uploaded photo (manual entry).",
    )
    photo_url = models.URLField(
        max_length=500, blank=True,
        help_text="Vendor-hosted visit photo, when the provider supplies one.",
    )
    remarks = models.TextField(blank=True)
    next_follow_up = models.DateField(null=True, blank=True)
    distance_travelled_km = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Distance covered to reach this visit from the previous stop.",
    )
    external_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "employee_customer_visit"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                condition=~models.Q(external_id=""),
                name="uq_visit_provider_external",
            ),
        ]
        indexes = [
            models.Index(fields=["customer", "-visit_date"], name="ix_visit_customer_date"),
            models.Index(fields=["employee", "-visit_date"], name="ix_visit_employee_date"),
        ]
        ordering = ("-visit_date", "-check_in_at")
        verbose_name = "Customer Visit"

    def __str__(self):
        return f"{self.employee} → {self.customer} on {self.visit_date}"


class EmployeeGeofence(AuditModel):
    """A circular geographic fence around a business location.

    Can be anchored to an existing master record (warehouse or customer) so
    fences follow the ERP's own entities; free-standing fences (offices,
    farms) just carry a name and coordinates. ``polygon`` is reserved for
    future polygonal fences without a schema change.
    """

    TYPE_CHOICES = [
        ("office", "Office"),
        ("warehouse", "Warehouse"),
        ("farm", "Farm"),
        ("customer", "Customer"),
        ("dealer", "Dealer"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=150)
    geofence_type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_index=True)
    center_latitude = _lat_field()
    center_longitude = _lng_field()
    radius_m = models.PositiveIntegerField(
        default=200, validators=[MinValueValidator(20)], help_text="Fence radius in metres."
    )
    polygon = models.JSONField(
        null=True, blank=True,
        help_text="Optional [[lat, lng], …] ring; overrides the circle when set.",
    )
    address = models.TextField(blank=True)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name="geofences"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="geofences"
    )
    alert_on_entry = models.BooleanField(default=False)
    alert_on_exit = models.BooleanField(default=False)
    working_start = models.TimeField(
        null=True, blank=True, help_text="Start of the window in which presence is expected."
    )
    working_end = models.TimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    external_id = models.CharField(
        max_length=100, blank=True, help_text="Provider-side geofence ID when mirrored to the vendor."
    )
    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="geofences"
    )

    class Meta:
        db_table = "employee_geofence"
        ordering = ("geofence_type", "name")
        verbose_name = "Geofence"

    def __str__(self):
        return f"{self.name} ({self.get_geofence_type_display()}, {self.radius_m} m)"


class TrackingLog(models.Model):
    """Append-only event stream: sync diagnostics, alerts, and audit trail.

    One table serves three consumers, discriminated by ``log_type``:

    * ``sync``/``webhook`` — integration diagnostics for operators;
    * ``alert`` — user-facing notifications (offline, geofence exit, late
      check-in, missed visit, GPS disabled) with read tracking;
    * ``audit`` — who changed provider/settings rows, with the acting user
      and client IP, mirroring ``account.AccountAuditLog``.

    Rows are never updated (except alert read-state) and never deleted.
    """

    LOG_TYPE_CHOICES = [
        ("sync", "Sync"),
        ("webhook", "Webhook"),
        ("alert", "Alert"),
        ("audit", "Audit"),
    ]
    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("error", "Error"),
        ("critical", "Critical"),
    ]
    EVENT_CHOICES = [
        # sync / webhook
        ("sync_started", "Sync Started"),
        ("sync_completed", "Sync Completed"),
        ("sync_failed", "Sync Failed"),
        ("webhook_received", "Webhook Received"),
        ("webhook_rejected", "Webhook Rejected"),
        # alerts
        ("employee_offline", "Employee Offline"),
        ("gps_disabled", "GPS Disabled"),
        ("no_internet", "No Internet"),
        ("geofence_entry", "Geofence Entered"),
        ("geofence_exit", "Geofence Exited"),
        ("outside_working_area", "Outside Working Area"),
        ("late_check_in", "Late Check-In"),
        ("early_check_out", "Early Check-Out"),
        ("missed_visit", "Missed Customer Visit"),
        # audit
        ("provider_changed", "Provider Configuration Changed"),
        ("settings_changed", "Tracking Settings Changed"),
        ("mapping_changed", "Employee Mapping Changed"),
        ("geofence_changed", "Geofence Changed"),
        ("attendance_approval", "Attendance Approval Decision"),
    ]

    log_type = models.CharField(max_length=10, choices=LOG_TYPE_CHOICES, db_index=True)
    event = models.CharField(max_length=30, choices=EVENT_CHOICES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="info")
    message = models.TextField()
    payload = models.JSONField(
        null=True, blank=True, help_text="Sanitized structured context (never credentials)."
    )
    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs"
    )
    sync_run = models.ForeignKey(
        TrackingSync, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="tracking_logs"
    )
    geofence = models.ForeignKey(
        EmployeeGeofence, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs"
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Acting user for audit events.",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_read = models.BooleanField(default=False, help_text="Alert read-state (alerts only).")
    read_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "employee_tracking_logs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["log_type", "-created_at"], name="ix_tracking_log_type_time"),
            models.Index(fields=["employee", "-created_at"], name="ix_tracking_log_emp_time"),
            models.Index(
                fields=["is_read"],
                condition=models.Q(log_type="alert", is_read=False),
                name="ix_tracking_log_unread_alerts",
            ),
        ]
        verbose_name = "Tracking Log"

    def __str__(self):
        return f"[{self.severity}] {self.event}: {self.message[:60]}"


class EmployeeGpsAttendance(models.Model):
    """One GPS-verified attendance record per employee per day.

    Bridges provider check-in/out events and ``hr.Attendance``. The HR row
    (which payroll reads) is only ever written through
    :meth:`tracking.services.attendance_service`, controlled by the approval
    workflow: rows arrive ``pending`` and are mirrored on approval, or
    immediately when auto-approval is enabled in Tracking Settings. The HR
    schema itself is untouched — this table carries all GPS evidence.
    """

    STATUS_CHOICES = [
        ("pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="gps_attendance"
    )
    provider = models.ForeignKey(
        TrackingProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    date = models.DateField(db_index=True)
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    check_in_latitude = _lat_field(null=True, blank=True)
    check_in_longitude = _lng_field(null=True, blank=True)
    check_out_latitude = _lat_field(null=True, blank=True)
    check_out_longitude = _lng_field(null=True, blank=True)
    check_in_address = models.TextField(blank=True)
    check_out_address = models.TextField(blank=True)
    check_in_photo_url = models.URLField(max_length=500, blank=True)
    check_out_photo_url = models.URLField(max_length=500, blank=True)
    geofence = models.ForeignKey(
        EmployeeGeofence, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Office/work fence the check-in was verified against.",
    )
    check_in_inside_fence = models.BooleanField(
        null=True, blank=True, help_text="Null when no active fence was available to verify against."
    )
    check_out_inside_fence = models.BooleanField(null=True, blank=True)
    is_late = models.BooleanField(default=False)
    late_by = models.DurationField(null=True, blank=True)
    is_early_exit = models.BooleanField(default=False)
    early_by = models.DurationField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="pending", db_index=True
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    attendance = models.ForeignKey(
        "hr.Attendance", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="gps_records",
        help_text="The mirrored HR attendance row, once approved.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "employee_attendance_gps"
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"],
                                    name="uq_gps_attendance_employee_date"),
        ]
        ordering = ("-date",)
        verbose_name = "GPS Attendance"
        verbose_name_plural = "GPS Attendance"

    def __str__(self):
        return f"{self.employee} — {self.date} ({self.status})"


class SyncLock(models.Model):
    """Singleton row (pk=1) coordinating sync_tracking runs across processes.

    Same rationale as environmental_monitoring.PollLock: CACHES is LocMemCache
    (process-local), and Postgres is the one thing every worker/process
    shares, so the overlap guard lives here.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    is_running = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "employee_tracking_sync_lock"
        verbose_name = "Sync lock"
        verbose_name_plural = "Sync lock"


class TrackingSettings(models.Model):
    """Singleton runtime configuration for the tracking module.

    Same pattern as ``notification.SmsSettings``: one row (pk forced to 1),
    editable from the Tracking Settings page so operators never need a
    deploy or ``.env`` change for day-to-day tuning.
    """

    MAP_CHOICES = [
        ("leaflet_osm", "OpenStreetMap (Leaflet)"),
        ("google", "Google Maps"),
    ]
    UNIT_CHOICES = [("km", "Kilometres"), ("mi", "Miles")]

    enabled = models.BooleanField(
        default=False, help_text="Master switch for the whole tracking module."
    )
    map_provider = models.CharField(max_length=15, choices=MAP_CHOICES, default="leaflet_osm")
    google_maps_api_key = EncryptedTextField(
        blank=True, help_text="Only needed when the map provider is Google Maps."
    )
    dashboard_refresh_seconds = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(10)],
        help_text="Auto-refresh interval of the live dashboard.",
    )
    offline_after_minutes = models.PositiveIntegerField(
        default=15, help_text="Minutes without a ping before an employee is shown offline."
    )
    idle_after_minutes = models.PositiveIntegerField(
        default=10, help_text="Minutes stationary before an employee is shown idle."
    )
    late_check_in_time = models.TimeField(
        null=True, blank=True, help_text="Check-ins after this time raise a Late Check-In alert."
    )
    early_check_out_time = models.TimeField(
        null=True, blank=True, help_text="Check-outs before this time raise an Early Exit alert."
    )
    working_start = models.TimeField(null=True, blank=True)
    working_end = models.TimeField(null=True, blank=True)
    default_geofence_radius_m = models.PositiveIntegerField(default=200)
    distance_unit = models.CharField(max_length=2, choices=UNIT_CHOICES, default="km")
    history_retention_days = models.PositiveIntegerField(
        default=365,
        help_text="Raw pings older than this are eligible for archival (0 = keep forever).",
    )
    alerts_enabled = models.BooleanField(default=True)
    sms_alerts_enabled = models.BooleanField(
        default=False, help_text="Fan alerts out through the existing SMS module."
    )
    attendance_sync_enabled = models.BooleanField(
        default=True,
        help_text="Build GPS attendance records from provider check-in/out events.",
    )
    attendance_auto_approve = models.BooleanField(
        default=False,
        help_text="Mirror GPS attendance into HR immediately, without manual approval.",
    )
    modified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "employee_tracking_settings"
        verbose_name = "Tracking Settings"
        verbose_name_plural = "Tracking Settings"

    def __str__(self):
        return "Employee Tracking Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj
