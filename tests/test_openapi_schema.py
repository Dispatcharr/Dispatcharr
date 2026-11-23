from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, RequestFactory, override_settings
from rest_framework.test import force_authenticate

from apps.api.schema_views import (
    LockedSpectacularAPIView, SchemaRateThrottle, _in_progress, clear_schema_cache,
)


def _counting_generator(calls):
    class CountingGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def get_schema(self, request=None, public=True):
            calls["n"] += 1
            return {"openapi": "3.0.3", "paths": {}, "info": {"title": "t"}}

    return CountingGenerator


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "openapi-schema-tests",
        }
    }
)
class LockedSpectacularAPIViewTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        clear_schema_cache()
        self.factory = RequestFactory()

    def tearDown(self):
        clear_schema_cache()

    def test_schema_cache_is_reused(self):
        view = LockedSpectacularAPIView.as_view()
        calls = {"n": 0}

        with patch.object(
            LockedSpectacularAPIView, "generator_class", _counting_generator(calls)
        ):
            for _ in range(3):
                response = view(self.factory.get("/api/schema/"))
                self.assertEqual(response.status_code, 200)

        self.assertEqual(calls["n"], 1)

    def test_clear_schema_cache_forces_rebuild(self):
        view = LockedSpectacularAPIView.as_view()
        calls = {"n": 0}

        with patch.object(
            LockedSpectacularAPIView, "generator_class", _counting_generator(calls)
        ):
            self.assertEqual(view(self.factory.get("/api/schema/")).status_code, 200)
            clear_schema_cache()
            self.assertEqual(view(self.factory.get("/api/schema/")).status_code, 200)

        self.assertEqual(calls["n"], 2)

    def test_parameterized_schema_is_served_without_caching(self):
        view = LockedSpectacularAPIView.as_view()
        calls = {"n": 0}
        with patch.object(LockedSpectacularAPIView, "generator_class", _counting_generator(calls)):
            for params in ({"lang": "fr"}, {"version": "v1"}):
                for _ in range(2):
                    self.assertEqual(
                        view(self.factory.get("/api/schema/", params)).status_code, 200
                    )
        self.assertEqual(calls["n"], 4)
        self.assertFalse(_in_progress)

    def test_schema_throttle_covers_both_routes_and_authenticated_users(self):
        self.assertEqual(SchemaRateThrottle().rate, "50/minute")
        view = LockedSpectacularAPIView.as_view()
        calls = {"n": 0}
        with patch.object(SchemaRateThrottle, "get_rate", return_value="2/minute"), \
             patch.object(LockedSpectacularAPIView, "generator_class", _counting_generator(calls)):
            first = self.factory.get("/api/schema/", REMOTE_ADDR="198.51.100.1")
            second = self.factory.get("/api/swagger.json", REMOTE_ADDR="198.51.100.1")
            force_authenticate(second, user=SimpleNamespace(is_authenticated=True))
            third = self.factory.get("/api/schema/", REMOTE_ADDR="198.51.100.1")
            other = self.factory.get("/api/schema/", REMOTE_ADDR="198.51.100.2")
            self.assertEqual(view(first).status_code, 200)
            self.assertEqual(view(second).status_code, 200)
            self.assertEqual(view(third).status_code, 429)
            self.assertEqual(view(other).status_code, 200)

    def test_waiters_receive_result_when_cache_is_unavailable(self):
        view = LockedSpectacularAPIView.as_view()
        count = 0
        started = threading.Barrier(8)
        lock = threading.Lock()

        class SlowGenerator:
            def __init__(self, *args, **kwargs):
                pass

            def get_schema(self, request=None, public=True):
                nonlocal count
                with lock:
                    count += 1
                time.sleep(0.1)
                return {"openapi": "3.0.3", "paths": {}, "info": {"title": "t"}}

        def hit(_):
            started.wait(timeout=5)
            return view(self.factory.get("/api/schema/"))

        with patch.object(LockedSpectacularAPIView, "generator_class", SlowGenerator), \
             patch.object(LockedSpectacularAPIView, "_cache_get", return_value=None), \
             patch.object(LockedSpectacularAPIView, "_cache_set"):
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(hit, range(8)))

        self.assertEqual(count, 1)
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertFalse(_in_progress)

    def test_concurrent_first_load_uses_single_build(self):
        view = LockedSpectacularAPIView.as_view()
        call_count = 0
        in_flight = 0
        max_in_flight = 0
        counter_lock = threading.Lock()
        started = threading.Barrier(8)

        class SlowGenerator:
            def __init__(self, *args, **kwargs):
                pass

            def get_schema(self, request=None, public=True):
                nonlocal call_count, in_flight, max_in_flight
                with counter_lock:
                    call_count += 1
                    in_flight += 1
                    max_in_flight = max(max_in_flight, in_flight)
                time.sleep(0.05)
                with counter_lock:
                    in_flight -= 1
                return {"openapi": "3.0.3", "paths": {}, "info": {"title": "t"}}

        with patch.object(
            LockedSpectacularAPIView, "generator_class", SlowGenerator
        ):
            def hit(_):
                started.wait(timeout=5)
                response = view(self.factory.get("/api/schema/"))
                self.assertEqual(response.status_code, 200)
                return response.data

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(hit, i) for i in range(8)]
                results = [f.result(timeout=10) for f in as_completed(futures)]

        self.assertEqual(call_count, 1)
        self.assertEqual(max_in_flight, 1)
        self.assertTrue(all(r.get("openapi") == "3.0.3" for r in results))
