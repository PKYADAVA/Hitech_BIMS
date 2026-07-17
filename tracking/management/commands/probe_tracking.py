"""Commissioning diagnostic: show what a provider actually returns.

Fetches one data kind through the real adapter and prints (a) the raw,
unwrapped vendor records and (b) what the parser made of them — so a
payload-shape mismatch is visible immediately instead of manifesting as
"success, 0 records" syncs.

Read-only: nothing is written to the database. Credentials are never printed.

Examples:
    python manage.py probe_tracking --kind employees
    python manage.py probe_tracking --kind live --limit 3
    python manage.py probe_tracking --kind history --hours 8
    python manage.py probe_tracking --provider "TrackWick" --kind attendance
"""

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracking.exceptions import TrackingError
from tracking.models import TrackingProvider
from tracking.providers import get_adapter
from tracking.providers.trackwick import TrackWickProviderAdapter

KINDS = ("employees", "live", "history", "visits", "attendance", "geofences")
WINDOWED = {"history", "visits", "attendance"}


class Command(BaseCommand):
    help = "Fetch one data kind from a provider and print raw + parsed records (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default=None,
                            help="Provider id or name (default: first active).")
        parser.add_argument("--kind", default="employees", choices=KINDS)
        parser.add_argument("--hours", type=float, default=23.9,
                            help="Window size for history/visits/attendance "
                                 "(default 23.9 — TrackWick's asset/history "
                                 "endpoint rejects windows of 24h or more).")
        parser.add_argument("--limit", type=int, default=5,
                            help="Raw records to print (default 5).")

    def handle(self, *args, **options):
        provider = self._provider(options["provider"])
        adapter = get_adapter(provider)
        kind = options["kind"]
        if not adapter.supports(kind):
            raise CommandError(
                f"Provider '{provider.name}' does not support '{kind}' "
                "(no endpoint configured).")

        self.stdout.write(f"Provider : {provider.name} ({provider.provider_type})")
        self.stdout.write(f"Base URL : {provider.api_url}")
        if isinstance(adapter, TrackWickProviderAdapter):
            endpoint = adapter._endpoints[kind]  # pylint: disable=protected-access
            self.stdout.write(f"Endpoint : {endpoint['method']} {endpoint['path']}")

        window_end = timezone.now()
        window_start = window_end - timedelta(hours=options["hours"])

        # Raw view first (TrackWick only — mock has no wire format).
        if isinstance(adapter, TrackWickProviderAdapter):
            params = None
            if kind == "history":
                # asset_id is mandatory on this endpoint; probe the first
                # known asset so the raw preview is a valid request.
                employees = adapter.fetch_employees()
                if not employees:
                    raise CommandError("No employees in the vendor directory to probe history for.")
                object_id = adapter._asset_object_id(employees[0].external_id)  # pylint: disable=protected-access
                if not object_id:
                    raise CommandError(f"Could not resolve an asset id for '{employees[0].external_id}'.")
                self.stdout.write(f"Probing history for employee '{employees[0].external_id}' "
                                 f"(asset_id={object_id})\n")
                params = {"start_time": int(window_start.timestamp() * 1000),
                         "end_time": int(window_end.timestamp() * 1000),
                         "asset_id": object_id}
            elif kind in WINDOWED:
                params = {adapter._generic_params["from"]: int(window_start.timestamp() * 1000),  # pylint: disable=protected-access
                         adapter._generic_params["to"]: int(window_end.timestamp() * 1000)}  # pylint: disable=protected-access
            try:
                raw = adapter._request(kind, params)  # pylint: disable=protected-access
            except TrackingError as exc:
                raise CommandError(f"Request failed: {exc}") from exc
            records = adapter._as_records(raw)  # pylint: disable=protected-access
            self.stdout.write(self.style.HTTP_INFO(
                f"\nRaw unwrapped data type: {type(raw).__name__}; "
                f"records recognised: {len(records)}"))
            if isinstance(raw, dict):
                self.stdout.write("Top-level keys: " + ", ".join(sorted(raw)[:30]))
            for record in records[:options["limit"]]:
                self.stdout.write(json.dumps(record, indent=2, default=str)[:2000])
            if not records:
                self.stdout.write(json.dumps(raw, indent=2, default=str)[:3000])

        # Parsed view.
        try:
            if kind in WINDOWED:
                fetcher = {"history": adapter.fetch_location_history,
                           "visits": adapter.fetch_visits,
                           "attendance": adapter.fetch_attendance_events}[kind]
                parsed = fetcher(window_start, window_end)
            elif kind == "employees":
                parsed = adapter.fetch_employees()
            elif kind == "live":
                parsed = adapter.fetch_live_locations()
            else:
                parsed = adapter.fetch_geofences()
        except TrackingError as exc:
            raise CommandError(f"Parse/fetch failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"\nParsed into {len(parsed)} DTO(s):"))
        for dto in parsed[:options["limit"]]:
            self.stdout.write("  " + repr(dto)[:400])
        if records_hint := (isinstance(adapter, TrackWickProviderAdapter)
                            and len(records) > 0 and len(parsed) == 0):
            _ = records_hint
            self.stdout.write(self.style.WARNING(
                "\nRecords arrived but none parsed — the field names differ from "
                "the parser's aliases. Share the raw record above to fix the mapping."))

    @staticmethod
    def _provider(identifier):
        providers = TrackingProvider.objects.filter(is_active=True)
        if identifier:
            providers = (providers.filter(pk=int(identifier))
                         if str(identifier).isdigit()
                         else providers.filter(name__iexact=identifier))
        provider = providers.order_by("priority", "id").first()
        if provider is None:
            raise CommandError("No matching active provider found.")
        return provider
