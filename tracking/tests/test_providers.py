# pylint: disable=no-member
"""Tests for the provider layer: registry, TrackWick adapter, mock adapter."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from tracking.dtos import ConnectionTestResult
from tracking.exceptions import (
    TrackingAuthError,
    TrackingConfigurationError,
    TrackingPermanentError,
    TrackingTransientError,
)
from tracking.models import TrackingProvider
from tracking.providers import ADAPTERS, get_adapter
from tracking.providers.mock import MockProviderAdapter
from tracking.providers.trackwick import TrackWickProviderAdapter


def make_provider(**kwargs):
    defaults = {
        "name": "TrackWick",
        "provider_type": "trackolap",
        "api_url": "https://api.trackwick.com/v1",
        "api_key": "k-123",
        "extra_config": {"customer_id": "CID-9"},
    }
    defaults.update(kwargs)
    return TrackingProvider.objects.create(**defaults)


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"success": True, "data": []}

    def json(self):
        if isinstance(self._body, str):
            return json.loads(self._body)  # raises ValueError for non-JSON
        return self._body


class RegistryTests(TestCase):
    def test_trackolap_maps_to_trackwick_adapter(self):
        adapter = get_adapter(make_provider())
        self.assertIsInstance(adapter, TrackWickProviderAdapter)

    def test_unimplemented_type_raises_configuration_error(self):
        provider = make_provider(name="T2", provider_type="traccar")
        with self.assertRaises(TrackingConfigurationError):
            get_adapter(provider)

    def test_mock_registered_for_tests(self):
        self.assertIn("mock", ADAPTERS)


class TrackWickAuthHeaderTests(TestCase):
    def _adapter_with_session(self, **provider_kwargs):
        session = mock.Mock()
        session.get.return_value = FakeResponse()
        provider = make_provider(**provider_kwargs)
        return TrackWickProviderAdapter(provider, session=session), session

    def test_common_headers_sent_on_every_request(self):
        adapter, session = self._adapter_with_session()
        adapter.fetch_employees()
        headers = session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["platform"], "API")
        self.assertEqual(headers["tlp-cid"], "CID-9")
        self.assertEqual(headers["api-key"], "k-123")
        # tlp-t must be a plausible epoch-milliseconds timestamp.
        self.assertGreater(int(headers["tlp-t"]), 1.7e12)

    def test_missing_customer_id_is_configuration_error(self):
        adapter, _ = self._adapter_with_session(name="NoCID", extra_config={})
        with self.assertRaises(TrackingConfigurationError):
            adapter.fetch_employees()

    def test_endpoint_override_from_extra_config(self):
        adapter, session = self._adapter_with_session(
            name="Override",
            extra_config={"customer_id": "CID-9",
                          "endpoints": {"employees": "v2/staff/all"}},
        )
        adapter.fetch_employees()
        url = session.get.call_args.args[0]
        self.assertEqual(url, "https://api.trackwick.com/v1/v2/staff/all")

    def test_default_endpoints_match_confirmed_vendor_paths(self):
        adapter, session = self._adapter_with_session(name="Defaults")
        adapter.fetch_employees()
        self.assertEqual(session.get.call_args.args[0],
                         "https://api.trackwick.com/v1/cust/1/api/asset/list")
        adapter.fetch_live_locations()
        self.assertEqual(session.get.call_args.args[0],
                         "https://api.trackwick.com/v1/integration/api/get")

    def test_attendance_endpoint_uses_post(self):
        adapter, session = self._adapter_with_session(name="PostCheck")
        session.post.return_value = FakeResponse()
        start = datetime.now(timezone.utc) - timedelta(hours=4)
        adapter.fetch_attendance_events(start, datetime.now(timezone.utc))
        self.assertTrue(session.post.called)
        self.assertIn("cust/1/api/punch/in/out", session.post.call_args.args[0])

    def test_geofences_capability_dropped_without_endpoint(self):
        adapter, _session = self._adapter_with_session(name="NoFence")
        self.assertFalse(adapter.supports("geofences"))
        self.assertTrue(adapter.supports("live"))
        with_override, _session2 = self._adapter_with_session(
            name="WithFence",
            extra_config={"customer_id": "CID-9",
                          "endpoints": {"geofences": "cust/1/api/fence/list"}},
        )
        self.assertTrue(with_override.supports("geofences"))


class TrackWickErrorClassificationTests(TestCase):
    _provider_seq = 0

    def _fetch_with_response(self, response):
        type(self)._provider_seq += 1
        session = mock.Mock()
        session.get.return_value = response
        adapter = TrackWickProviderAdapter(
            make_provider(name=f"TrackWick-{self._provider_seq}"), session=session)
        return adapter.fetch_employees()

    def test_401_raises_auth_error(self):
        with self.assertRaises(TrackingAuthError):
            self._fetch_with_response(FakeResponse(status_code=401))

    def test_503_raises_transient_error(self):
        with self.assertRaises(TrackingTransientError):
            self._fetch_with_response(FakeResponse(status_code=503))

    def test_404_permanent_error_mentions_endpoint_overrides(self):
        with self.assertRaises(TrackingPermanentError) as ctx:
            self._fetch_with_response(FakeResponse(status_code=404))
        self.assertIn("endpoint", str(ctx.exception).lower())

    def test_envelope_error_flag_raises_permanent(self):
        body = {"success": False, "message": "invalid request", "code": "E42"}
        with self.assertRaises(TrackingPermanentError) as ctx:
            self._fetch_with_response(FakeResponse(body=body))
        self.assertEqual(ctx.exception.error_code, "E42")

    def test_trackwick_native_error_envelope(self):
        # Live envelope observed from go.trackwick.com: HTTP 200 + s:false.
        body = {"s": False, "ed": "Something specific failed", "rc": 400}
        with self.assertRaises(TrackingPermanentError) as ctx:
            self._fetch_with_response(FakeResponse(body=body))
        self.assertEqual(ctx.exception.error_code, "400")

    def test_trackwick_http200_auth_failures_raise_auth_error(self):
        for message in ("You are not authorized to perform this!", "Access Error!!"):
            with self.assertRaises(TrackingAuthError):
                self._fetch_with_response(FakeResponse(
                    body={"s": False, "ed": message, "rc": 500}))

    def test_trackwick_native_success_envelope_unwraps_d(self):
        body = {"s": True, "d": [{"eid": 7, "name": "Native Person"}]}
        session = mock.Mock()
        session.get.return_value = FakeResponse(body=body)
        adapter = TrackWickProviderAdapter(make_provider(name="Native"), session=session)
        employees = adapter.fetch_employees()
        self.assertEqual(len(employees), 1)
        self.assertEqual(employees[0].external_id, "7")

    def test_non_json_body_raises_permanent(self):
        with self.assertRaises(TrackingPermanentError):
            self._fetch_with_response(FakeResponse(body="<html>not json</html>"))

    def test_test_connection_never_raises(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(status_code=401)
        adapter = TrackWickProviderAdapter(make_provider(), session=session)
        result = adapter.test_connection()
        self.assertIsInstance(result, ConnectionTestResult)
        self.assertFalse(result.success)
        self.assertIn("credentials", result.message.lower())


class TrackWickParsingTests(TestCase):
    def _adapter(self, body):
        session = mock.Mock()
        session.get.return_value = FakeResponse(body=body)
        session.post.return_value = FakeResponse(body=body)
        return TrackWickProviderAdapter(make_provider(), session=session)

    def test_live_locations_parsed_with_alias_keys(self):
        recorded_ms = 1752650000000  # 2025-07-16-ish, epoch ms
        body = {"success": True, "data": [
            {"eid": 101, "lat": "26.85", "lng": "80.95", "time": recorded_ms,
             "speed": "12.5", "battery": "76", "status": "MOVING", "address": "Lucknow"},
            {"employeeId": 102, "latitude": 26.90, "longitude": 80.90,
             "lastUpdated": "2026-07-16T09:30:00+05:30", "state": "offline"},
            {"eid": 103},  # unparseable -> skipped, not fatal
        ]}
        positions = self._adapter(body).fetch_live_locations()
        self.assertEqual(len(positions), 2)

        first = positions[0]
        self.assertEqual(first.external_employee_id, "101")
        self.assertEqual(first.latitude, Decimal("26.85"))
        self.assertEqual(first.status, "moving")
        self.assertEqual(first.battery_pct, 76)
        self.assertEqual(
            first.recorded_at,
            datetime.fromtimestamp(recorded_ms / 1000, tz=timezone.utc),
        )

        second = positions[1]
        self.assertEqual(second.external_employee_id, "102")
        self.assertEqual(second.status, "offline")
        self.assertEqual(second.recorded_at.tzinfo, timezone.utc)

    def test_history_window_params_sent_in_epoch_ms(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse()
        adapter = TrackWickProviderAdapter(make_provider(), session=session)
        start = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=8)
        adapter.fetch_location_history(start, end, external_employee_id="101")
        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["from"], int(start.timestamp() * 1000))
        self.assertEqual(params["to"], int(end.timestamp() * 1000))
        self.assertEqual(params["eid"], "101")

    def test_visits_parsed(self):
        body = [{"visitId": "V1", "eid": 101, "customerName": "ACME",
                 "checkInTime": 1752650000000, "checkOutTime": 1752652400000,
                 "lat": 26.85, "lng": 80.95, "remarks": "ok"}]
        visits = self._adapter(body).fetch_visits(
            datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc)
        )
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0].external_id, "V1")
        self.assertEqual(visits[0].customer_name, "ACME")

    def test_attendance_events_filtered_to_checkin_checkout(self):
        body = [
            {"eid": 101, "type": "PUNCH_IN", "time": 1752650000000},
            {"eid": 101, "type": "ping", "time": 1752650300000},
        ]
        events = self._adapter(body).fetch_attendance_events(
            datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc)
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "check_in")


class MockAdapterTests(TestCase):
    def test_mock_supplies_every_capability(self):
        provider = make_provider(name="Mock", provider_type="mock")
        adapter = get_adapter(provider)
        self.assertIsInstance(adapter, MockProviderAdapter)
        start = datetime.now(timezone.utc) - timedelta(hours=2)
        end = datetime.now(timezone.utc)

        self.assertTrue(adapter.test_connection().success)
        self.assertEqual(len(adapter.fetch_employees()), 2)
        self.assertEqual(len(adapter.fetch_live_locations()), 2)
        self.assertGreater(len(adapter.fetch_location_history(start, end)), 0)
        self.assertEqual(len(adapter.fetch_visits(start, end)), 1)
        self.assertEqual(len(adapter.fetch_attendance_events(start, end)), 2)
        self.assertEqual(len(adapter.fetch_geofences()), 1)
