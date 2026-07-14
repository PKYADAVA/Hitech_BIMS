import secrets

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

CONNECTION_STATUS_CHOICES = [
    ("online", _("Online")),
    ("offline", _("Offline")),
    ("error", _("Error")),
    ("unknown", _("Unknown")),
]


class Hub(models.Model):
    """A Tapo H100 hub bridging local sensors onto the network."""

    name = models.CharField(max_length=100, help_text=_("Label, e.g. 'Setter Room 1'"))
    alias = models.CharField(max_length=100, blank=True, help_text=_("Alias reported by the device"))
    ip_address = models.GenericIPAddressField(help_text=_("Current LAN IP address"))
    mac_address = models.CharField(max_length=17, blank=True)
    device_id = models.CharField(
        max_length=64, unique=True,
        help_text=_("Stable Tapo device id (survives IP changes from DHCP)"),
    )
    model = models.CharField(max_length=30, default="H100")
    firmware_version = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=10, choices=CONNECTION_STATUS_CHOICES, default="unknown")
    signal_strength = models.IntegerField(null=True, blank=True, help_text=_("RSSI"))
    last_seen = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, help_text=_("Inactive hubs are skipped by polling"))
    api_token = models.CharField(
        max_length=64, unique=True, blank=True, editable=False,
        help_text=_("Secret token an on-site collector script uses to push readings for this hub"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hub")
        verbose_name_plural = _("Hubs")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        # full_clean() runs validate_unique() right after clean(), so the
        # token must exist by here - generating it only in save() would be
        # too late and make every blank token collide on uniqueness.
        if not self.api_token:
            self.api_token = secrets.token_hex(24)

    def save(self, *args, **kwargs):
        if not self.api_token:
            self.api_token = secrets.token_hex(24)
        super().save(*args, **kwargs)

    def regenerate_api_token(self):
        self.api_token = secrets.token_hex(24)
        self.save(update_fields=["api_token", "updated_at"])


class Sensor(models.Model):
    """A Tapo child sensor device attached to a Hub, optionally mapped to a Setter."""

    DEVICE_TYPE_CHOICES = [
        ("t310", _("T310 Temperature & Humidity")),
        # Future: t315, t100, t110, s200 - same shape, no schema change needed.
    ]

    hub = models.ForeignKey(Hub, on_delete=models.CASCADE, related_name="sensors")
    setter = models.ForeignKey(
        "hatchery_master.Setter", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sensors",
        help_text=_("Setter this sensor is physically placed in"),
    )
    device_type = models.CharField(max_length=20, choices=DEVICE_TYPE_CHOICES, default="t310")
    device_id = models.CharField(max_length=64, unique=True, help_text=_("Tapo child device id"))
    serial_number = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=30, default="T310")
    alias = models.CharField(max_length=100, blank=True, help_text=_("User-facing label"))

    # Cached latest reading, refreshed on every poll for cheap dashboard reads.
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    humidity_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    battery_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    signal_strength = models.IntegerField(null=True, blank=True, help_text=_("RSSI"))
    last_update = models.DateTimeField(null=True, blank=True, help_text=_("Last successful read from the device"))
    status = models.CharField(max_length=10, choices=CONNECTION_STATUS_CHOICES, default="unknown")

    # The hub's own alarm/threshold event log for this sensor (e.g.
    # "tooHumid", "tempTooCool") - a genuine device-sourced timestamp,
    # distinct from last_update (which only records when *we* last polled).
    last_alarm_event = models.CharField(max_length=50, blank=True)
    last_alarm_at = models.DateTimeField(null=True, blank=True)

    calibration_offset_temp = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    calibration_offset_humidity = models.DecimalField(max_digits=4, decimal_places=2, default=0)

    # Per-sensor threshold overrides; null falls back to the global defaults in conf.py.
    temp_min = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    temp_max = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    humidity_min = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    humidity_max = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    battery_low_pct = models.PositiveSmallIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Sensor")
        verbose_name_plural = _("Sensors")
        ordering = ["hub__name", "alias"]

    def __str__(self):
        return self.alias or f"{self.get_device_type_display()} ({self.device_id})"

    def effective_thresholds(self):
        """This sensor's thresholds, falling back to the global defaults for
        any field left blank - the single source of truth both AlertService
        and the UI's out-of-range highlighting read from, so they can never
        disagree with each other."""
        from .conf import load_config
        config = load_config()
        return {
            "temp_min": self.temp_min if self.temp_min is not None else config.default_temp_min,
            "temp_max": self.temp_max if self.temp_max is not None else config.default_temp_max,
            "humidity_min": self.humidity_min if self.humidity_min is not None else config.default_humidity_min,
            "humidity_max": self.humidity_max if self.humidity_max is not None else config.default_humidity_max,
            "battery_low_pct": self.battery_low_pct if self.battery_low_pct is not None else config.default_battery_low_pct,
        }

    @property
    def is_temperature_out_of_range(self):
        if self.temperature_c is None:
            return False
        thresholds = self.effective_thresholds()
        return self.temperature_c < thresholds["temp_min"] or self.temperature_c > thresholds["temp_max"]

    @property
    def is_humidity_out_of_range(self):
        if self.humidity_pct is None:
            return False
        thresholds = self.effective_thresholds()
        return self.humidity_pct < thresholds["humidity_min"] or self.humidity_pct > thresholds["humidity_max"]

    @property
    def is_battery_low(self):
        if self.battery_pct is None:
            return False
        return self.battery_pct <= self.effective_thresholds()["battery_low_pct"]


class SensorReading(models.Model):
    """Append-only history row, one per successful poll per sensor. Never overwritten."""

    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="readings")
    hub = models.ForeignKey(Hub, on_delete=models.CASCADE, related_name="readings")
    timestamp = models.DateTimeField(db_index=True)
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    humidity_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    battery_pct = models.PositiveSmallIntegerField(null=True)
    signal_strength = models.IntegerField(null=True)

    class Meta:
        verbose_name = _("Sensor reading")
        verbose_name_plural = _("Sensor readings")
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["sensor", "-timestamp"])]


class Alert(models.Model):
    """An open or resolved threshold/connectivity alert for a sensor or hub."""

    ALERT_TYPE_CHOICES = [
        ("temp_high", _("Temperature High")),
        ("temp_low", _("Temperature Low")),
        ("humidity_high", _("Humidity High")),
        ("humidity_low", _("Humidity Low")),
        ("battery_low", _("Battery Low")),
        ("sensor_offline", _("Sensor Offline")),
        ("hub_offline", _("Hub Offline")),
    ]

    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts")
    hub = models.ForeignKey(Hub, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts")
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPE_CHOICES)
    message = models.CharField(max_length=255)
    value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    triggered_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        verbose_name = _("Alert")
        verbose_name_plural = _("Alerts")
        ordering = ["-triggered_at"]

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.message}"

    @property
    def is_open(self):
        return self.resolved_at is None


class TapoAccount(models.Model):
    """Single record holding the TP-Link/Tapo cloud account used to authenticate
    against hubs on the local network - editable in the ERP UI (mirrors
    account.models.CompanyProfile's singleton pattern) rather than only via
    environment variables, so operators can rotate it without a server restart.
    """

    email = models.EmailField(blank=True, help_text=_("Tapo account email"))
    password = models.CharField(max_length=255, blank=True, help_text=_("Tapo account password"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Tapo Account")
        verbose_name_plural = _("Tapo Account")

    def __str__(self):
        return self.email or "Tapo Account (not configured)"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class AlertThresholdDefaults(models.Model):
    """Single record holding the global default alert thresholds - editable in
    the ERP UI (mirrors TapoAccount's singleton pattern) so operators can tune
    them per-site without editing .env or restarting the server. Any sensor
    without its own override (Sensor.temp_min etc.) falls back to these.
    """

    temp_min = models.DecimalField(max_digits=5, decimal_places=2, default=35)
    temp_max = models.DecimalField(max_digits=5, decimal_places=2, default=38)
    humidity_min = models.DecimalField(max_digits=5, decimal_places=2, default=50)
    humidity_max = models.DecimalField(max_digits=5, decimal_places=2, default=65)
    battery_low_pct = models.PositiveSmallIntegerField(default=20)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Default Alert Thresholds")
        verbose_name_plural = _("Default Alert Thresholds")

    def __str__(self):
        return "Default Alert Thresholds"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class PollLock(models.Model):
    """Singleton row (pk=1) coordinating poll_sensors runs across processes.

    Needed because CACHES is LocMemCache (process-local); Postgres is the one
    thing every worker/process shares, so the lock lives here instead.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    is_running = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Poll lock")
        verbose_name_plural = _("Poll lock")
