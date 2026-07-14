from django.contrib import admin

from .models import Alert, Hub, Sensor, SensorReading


@admin.register(Hub)
class HubAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'device_id', 'status', 'last_seen', 'is_active')
    search_fields = ('name', 'alias', 'ip_address', 'device_id', 'mac_address')
    list_filter = ('status', 'is_active')
    list_per_page = 20


@admin.register(Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = (
        'alias', 'hub', 'setter', 'device_type', 'temperature_c', 'humidity_pct',
        'battery_pct', 'status', 'last_update', 'is_active',
    )
    search_fields = ('alias', 'device_id', 'serial_number')
    list_filter = ('device_type', 'status', 'is_active', 'hub')
    list_per_page = 20


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'hub', 'timestamp', 'temperature_c', 'humidity_pct', 'battery_pct')
    list_filter = ('hub', 'sensor')
    date_hierarchy = 'timestamp'
    list_per_page = 50


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('alert_type', 'sensor', 'hub', 'message', 'triggered_at', 'resolved_at', 'is_acknowledged')
    list_filter = ('alert_type', 'is_acknowledged')
    date_hierarchy = 'triggered_at'
    list_per_page = 50
