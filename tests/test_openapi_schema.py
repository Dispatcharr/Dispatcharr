from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory, override_settings

from apps.api.schema_views import LockedSpectacularAPIView, clear_schema_cache


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
