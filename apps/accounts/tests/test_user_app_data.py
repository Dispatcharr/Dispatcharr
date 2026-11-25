"""Per-app user storage under /api/accounts/users/me/app-data/."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.app_data import (
    APP_DATA_MAX_APPS,
    APP_DATA_MAX_CONTENT_LENGTH,
    APP_DATA_MAX_TOTAL_BYTES,
    APP_DATA_MAX_VALUE_BYTES,
    CODE_BODY_TOO_LARGE,
    CODE_FORBIDDEN,
    CODE_INVALID_CONTENT_LENGTH,
    CODE_KEY_INVALID,
    CODE_KEY_NOT_FOUND,
    CODE_MAX_APPS,
    CODE_TOTAL_TOO_LARGE,
    CODE_USER_NOT_FOUND,
    CODE_VALUE_HAS_NUL,
    CODE_VALUE_NOT_OBJECT,
    CODE_VALUE_TOO_DEEP,
    CODE_VALUE_TOO_LARGE,
)

User = get_user_model()

ME_APP_DATA = "/api/accounts/users/me/app-data/"
ME_URL = "/api/accounts/users/me/"
USERS_URL = "/api/accounts/users/"


def me_key_url(key):
    return f"{ME_APP_DATA}{key}/"


def user_app_data_url(user_id, key=None):
    base = f"/api/accounts/users/{user_id}/app-data/"
    return f"{base}{key}/" if key else base


def assert_error(test, response, status_code, code):
    test.assertEqual(response.status_code, status_code)
    body = response.json()
    test.assertEqual(body.get("code"), code)
    test.assertIsInstance(body.get("detail"), str)
    test.assertTrue(body["detail"])


class UserAppDataEndpointTests(TestCase):
    def setUp(self):
        # API-key auth keeps per-IP failure state in the shared cache; start clean.
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="viewer",
            password="testpass123",
            user_level=User.UserLevel.STANDARD,
            api_key="viewer-api-key",
        )
        self.streamer = User.objects.create_user(
            username="streamer",
            password="testpass123",
            user_level=User.UserLevel.STREAMER,
        )
        self.admin = User.objects.create_user(
            username="admin",
            password="testpass123",
            user_level=User.UserLevel.ADMIN,
        )
        self.other = User.objects.create_user(
            username="other",
            password="testpass123",
            user_level=User.UserLevel.STANDARD,
        )
        self.client.force_authenticate(self.user)

    def test_put_get_list_delete_round_trip(self):
        key = "com.example.app1"
        payload = {"theme": "dark", "lastChannel": 42}

        put = self.client.put(me_key_url(key), payload, format="json")
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.json(), payload)

        get_one = self.client.get(me_key_url(key))
        self.assertEqual(get_one.status_code, 200)
        self.assertEqual(get_one.json(), payload)

        listed = self.client.get(ME_APP_DATA)
        self.assertEqual(listed.status_code, 200)
        body = listed.json()
        self.assertIn("limits", body)
        self.assertEqual(len(body["apps"]), 1)
        self.assertEqual(body["apps"][0]["key"], key)
        self.assertGreater(body["apps"][0]["bytes"], 0)
        self.assertEqual(body["total_bytes"], body["apps"][0]["bytes"])
        self.assertNotIn("theme", body)

        delete = self.client.delete(me_key_url(key))
        self.assertEqual(delete.status_code, 204)

        missing = self.client.get(me_key_url(key))
        assert_error(self, missing, 404, CODE_KEY_NOT_FOUND)

        # Idempotent delete: missing key is 204, not 404
        delete_again = self.client.delete(me_key_url(key))
        self.assertEqual(delete_again.status_code, 204)

    def test_keys_are_isolated_and_clear_all(self):
        self.client.put(
            me_key_url("com.example.one"), {"a": 1}, format="json"
        )
        self.client.put(
            me_key_url("com.example.two"), {"b": 2}, format="json"
        )

        self.client.delete(me_key_url("com.example.one"))
        self.assertEqual(
            self.client.get(me_key_url("com.example.two")).json(), {"b": 2}
        )
        self.assertEqual(
            self.client.get(me_key_url("com.example.one")).status_code, 404
        )

        clear_all = self.client.delete(ME_APP_DATA)
        self.assertEqual(clear_all.status_code, 204)
        listed = self.client.get(ME_APP_DATA).json()
        self.assertEqual(listed["apps"], [])
        self.assertEqual(listed["total_bytes"], 0)

    def test_anonymous_is_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(ME_APP_DATA)
        self.assertEqual(response.status_code, 401)

    def test_api_key_auth_works(self):
        self.client.force_authenticate(user=None)
        response = self.client.put(
            me_key_url("com.example.apikey"),
            {"ok": True},
            format="json",
            HTTP_X_API_KEY="viewer-api-key",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_streamer_can_use_own_app_data(self):
        self.client.force_authenticate(self.streamer)
        response = self.client.put(
            me_key_url("com.example.stream"),
            {"x": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_non_admin_cannot_access_other_user(self):
        response = self.client.get(user_app_data_url(self.other.id))
        assert_error(self, response, 403, CODE_FORBIDDEN)

        response = self.client.put(
            user_app_data_url(self.other.id, "com.example.x"),
            {"x": 1},
            format="json",
        )
        assert_error(self, response, 403, CODE_FORBIDDEN)

        response = self.client.delete(
            user_app_data_url(self.other.id, "com.example.x")
        )
        assert_error(self, response, 403, CODE_FORBIDDEN)

        response = self.client.delete(user_app_data_url(self.other.id))
        assert_error(self, response, 403, CODE_FORBIDDEN)

    def test_owner_can_access_own_numeric_id(self):
        put = self.client.put(
            user_app_data_url(self.user.id, "com.example.own"),
            {"mine": True},
            format="json",
        )
        self.assertEqual(put.status_code, 200)
        listed = self.client.get(user_app_data_url(self.user.id))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["apps"][0]["key"], "com.example.own")

    def test_admin_can_read_write_clear_other_user(self):
        self.client.force_authenticate(self.admin)
        key = "com.example.admin"
        put = self.client.put(
            user_app_data_url(self.other.id, key),
            {"managed": True},
            format="json",
        )
        self.assertEqual(put.status_code, 200)

        listed = self.client.get(user_app_data_url(self.other.id))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["apps"][0]["key"], key)

        clear = self.client.delete(user_app_data_url(self.other.id, key))
        self.assertEqual(clear.status_code, 204)

    def test_unknown_user_id_is_404(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(user_app_data_url(999999))
        assert_error(self, response, 404, CODE_USER_NOT_FOUND)

    def test_key_validation(self):
        for bad_key in ("short", "a" * 65, "bad key!", ".leadingdot1"):
            with self.subTest(key=bad_key):
                response = self.client.put(
                    me_key_url(bad_key), {"x": 1}, format="json"
                )
                assert_error(self, response, 400, CODE_KEY_INVALID)

    def test_value_must_be_object(self):
        for body in (["list"], "string", 42, True):
            with self.subTest(body=body):
                response = self.client.put(
                    me_key_url("com.example.obj"), body, format="json"
                )
                assert_error(self, response, 400, CODE_VALUE_NOT_OBJECT)

    def test_rejects_nul_and_excessive_depth(self):
        nul = self.client.put(
            me_key_url("com.example.nul"),
            {"bad": "has\x00nul"},
            format="json",
        )
        assert_error(self, nul, 400, CODE_VALUE_HAS_NUL)

        deep = {"l1": {}}
        cursor = deep["l1"]
        for i in range(2, 10):
            cursor[f"l{i}"] = {}
            cursor = cursor[f"l{i}"]
        depth = self.client.put(
            me_key_url("com.example.deep"), deep, format="json"
        )
        assert_error(self, depth, 400, CODE_VALUE_TOO_DEEP)

    def test_rejects_non_finite_numbers_and_lone_surrogates(self):
        # 1e999 parses to inf, which json.dumps would write as Infinity and
        # Postgres jsonb would then reject, so it must be a 400, not a 500.
        for raw in (b'{"n": 1e999}', b'{"n": -1e999}', b'{"s": "\\ud800"}'):
            with self.subTest(raw=raw):
                response = self.client.generic(
                    "PUT",
                    me_key_url("com.example.badjson"),
                    raw,
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)

    def test_rejects_pathologically_deep_json_without_500(self):
        # Stays under the Content-Length guard so the JSON parser itself is
        # what runs out of recursion room.
        raw = b"[" * 16000 + b"]" * 16000
        self.assertLess(len(raw), APP_DATA_MAX_CONTENT_LENGTH)
        response = self.client.generic(
            "PUT",
            me_key_url("com.example.recurse"),
            raw,
            content_type="application/json",
        )
        assert_error(self, response, 400, CODE_VALUE_TOO_DEEP)

    def test_only_json_bodies_are_accepted(self):
        # A form body would arrive as a QueryDict and store lists of strings.
        response = self.client.put(
            me_key_url("com.example.form"),
            {"theme": "dark"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(
            self.client.get(me_key_url("com.example.form")).status_code, 404
        )

    def test_unchanged_put_does_not_rewrite_row(self):
        key = "com.example.same"
        self.client.put(me_key_url(key), {"a": 1}, format="json")

        with CaptureQueriesContext(connection) as same:
            response = self.client.put(me_key_url(key), {"a": 1}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"a": 1})
        self.assertFalse(
            [q for q in same.captured_queries if q["sql"].lstrip().upper().startswith("UPDATE")]
        )

        with CaptureQueriesContext(connection) as changed:
            response = self.client.put(me_key_url(key), {"a": 2}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            [q for q in changed.captured_queries if q["sql"].lstrip().upper().startswith("UPDATE")]
        )
        self.assertEqual(self.client.get(me_key_url(key)).json(), {"a": 2})

    def test_delete_only_touches_the_target_user_and_key(self):
        from apps.accounts.models import UserAppData

        gone = "com.example.gone"
        kept = "com.example.kept"
        self.client.put(me_key_url(gone), {"a": 1}, format="json")
        self.client.put(me_key_url(kept), {"b": 2}, format="json")
        UserAppData.objects.create(
            user=self.other, key=gone, value={"theirs": True}, byte_size=16
        )

        self.assertEqual(self.client.delete(me_key_url(gone)).status_code, 204)
        # Deleting a key that is already gone is still 204.
        self.assertEqual(self.client.delete(me_key_url(gone)).status_code, 204)

        remaining = set(
            UserAppData.objects.values_list("user_id", "key")
        )
        self.assertEqual(
            remaining, {(self.user.id, kept), (self.other.id, gone)}
        )

        self.assertEqual(self.client.delete(ME_APP_DATA).status_code, 204)
        self.assertEqual(self.client.delete(ME_APP_DATA).status_code, 204)
        self.assertEqual(
            set(UserAppData.objects.values_list("user_id", "key")),
            {(self.other.id, gone)},
        )

    def test_same_key_is_independent_per_user(self):
        key = "com.example.shared"
        self.client.put(me_key_url(key), {"owner": "viewer"}, format="json")
        self.client.force_authenticate(self.other)
        self.client.put(me_key_url(key), {"owner": "other"}, format="json")

        self.assertEqual(
            self.client.get(me_key_url(key)).json(), {"owner": "other"}
        )
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.get(me_key_url(key)).json(), {"owner": "viewer"}
        )

    def test_deleting_a_user_removes_their_app_data(self):
        from apps.accounts.models import UserAppData

        self.client.put(me_key_url("com.example.cascade"), {"a": 1}, format="json")
        self.assertTrue(UserAppData.objects.filter(user=self.user).exists())

        self.user.delete()
        self.assertFalse(UserAppData.objects.filter(user_id=self.user.id).exists())

    def test_stored_byte_size_matches_list_and_total(self):
        from apps.accounts.app_data import json_byte_size
        from apps.accounts.models import UserAppData

        payload = {"title": "caf\u00e9 \u2603", "n": [1, 2, 3]}
        self.client.put(me_key_url("com.example.sized"), payload, format="json")

        entry = UserAppData.objects.get(user=self.user, key="com.example.sized")
        self.assertEqual(entry.byte_size, json_byte_size(payload))

        listed = self.client.get(ME_APP_DATA).json()
        self.assertEqual(listed["apps"][0]["bytes"], entry.byte_size)
        self.assertEqual(listed["total_bytes"], entry.byte_size)

    def test_per_app_size_cap(self):
        # Compact JSON size of {"d": "<padding>"} must exceed the per-app limit.
        overhead = len('{"d":""}')
        padding = "x" * (APP_DATA_MAX_VALUE_BYTES - overhead + 1)
        response = self.client.put(
            me_key_url("com.example.big"),
            {"d": padding},
            format="json",
        )
        assert_error(self, response, 413, CODE_VALUE_TOO_LARGE)

    def test_total_size_cap(self):
        # Eight max-sized apps fill the 1 MiB user budget; one more tips over.
        overhead = len('{"d":""}')
        padding = "x" * (APP_DATA_MAX_VALUE_BYTES - overhead)
        apps_to_fill = APP_DATA_MAX_TOTAL_BYTES // APP_DATA_MAX_VALUE_BYTES
        for i in range(apps_to_fill):
            response = self.client.put(
                me_key_url(f"com.example.fill{i}"),
                {"d": padding},
                format="json",
            )
            self.assertEqual(response.status_code, 200, i)

        over = self.client.put(
            me_key_url("com.example.over"),
            {"d": "y"},
            format="json",
        )
        assert_error(self, over, 413, CODE_TOTAL_TOO_LARGE)

    def test_app_count_cap_replace_does_not_count(self):
        for i in range(APP_DATA_MAX_APPS):
            key = f"com.example.app{i:02d}"
            response = self.client.put(me_key_url(key), {"i": i}, format="json")
            self.assertEqual(response.status_code, 200, key)

        extra = self.client.put(
            me_key_url("com.example.extra1"), {"x": 1}, format="json"
        )
        assert_error(self, extra, 409, CODE_MAX_APPS)

        replace = self.client.put(
            me_key_url("com.example.app00"), {"i": 99}, format="json"
        )
        self.assertEqual(replace.status_code, 200)
        self.assertEqual(replace.json(), {"i": 99})

    def test_content_length_rejected_before_parse(self):
        response = self.client.put(
            me_key_url("com.example.clen"),
            {"ok": True},
            format="json",
            CONTENT_LENGTH=str(APP_DATA_MAX_CONTENT_LENGTH + 1),
        )
        assert_error(self, response, 413, CODE_BODY_TOO_LARGE)

        negative = self.client.put(
            me_key_url("com.example.clen"),
            {"ok": True},
            format="json",
            CONTENT_LENGTH="-1",
        )
        assert_error(self, negative, 400, CODE_INVALID_CONTENT_LENGTH)

    def test_me_and_user_list_omit_app_data(self):
        self.client.put(
            me_key_url("com.example.hide"), {"secret": True}, format="json"
        )

        me = self.client.get(ME_URL)
        self.assertEqual(me.status_code, 200)
        self.assertNotIn("app_data", me.json())

        self.client.force_authenticate(self.admin)
        listed = self.client.get(USERS_URL)
        self.assertEqual(listed.status_code, 200)
        for row in listed.json():
            self.assertNotIn("app_data", row)

    def test_me_patch_and_admin_put_ignore_app_data(self):
        self.client.put(
            me_key_url("com.example.keep"), {"keep": True}, format="json"
        )

        patch = self.client.patch(
            ME_URL,
            {
                "first_name": "Patched",
                "app_data": {"com.example.evil": {"hacked": True}},
            },
            format="json",
        )
        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.json()["first_name"], "Patched")
        self.assertNotIn("app_data", patch.json())
        self.assertEqual(
            self.client.get(me_key_url("com.example.keep")).json(),
            {"keep": True},
        )
        self.assertEqual(
            self.client.get(me_key_url("com.example.evil")).status_code, 404
        )

        self.client.force_authenticate(self.admin)
        admin_patch = self.client.patch(
            f"{USERS_URL}{self.user.id}/",
            {"app_data": {"com.example.evil": {"hacked": True}}},
            format="json",
        )
        self.assertEqual(admin_patch.status_code, 200)
        self.assertNotIn("app_data", admin_patch.json())

        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.get(me_key_url("com.example.keep")).json(),
            {"keep": True},
        )
        self.assertEqual(
            self.client.get(me_key_url("com.example.evil")).status_code, 404
        )

    def test_user_save_does_not_affect_app_data_rows(self):
        from apps.accounts.models import UserAppData

        self.client.put(
            me_key_url("com.example.stale"), {"alive": True}, format="json"
        )
        self.client.put(
            me_key_url("com.example.stale"), {"alive": True, "v": 2}, format="json"
        )

        stale = User.objects.get(pk=self.user.pk)
        stale.first_name = "Stale"
        stale.save()

        entry = UserAppData.objects.get(user_id=self.user.pk, key="com.example.stale")
        self.assertEqual(entry.value, {"alive": True, "v": 2})
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Stale")

    def test_get_one_key_loads_only_that_row(self):
        from apps.accounts.models import UserAppData

        self.client.put(
            me_key_url("com.example.one"), {"a": 1}, format="json"
        )
        self.client.put(
            me_key_url("com.example.two"),
            {"pad": "x" * 2000},
            format="json",
        )
        self.assertEqual(UserAppData.objects.filter(user=self.user).count(), 2)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(me_key_url("com.example.one"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"a": 1})

        value_selects = [
            q["sql"]
            for q in ctx.captured_queries
            if "accounts_userappdata" in q["sql"].lower()
            and "select" in q["sql"].lower()
        ]
        self.assertEqual(len(value_selects), 1)
        self.assertIn("key", value_selects[0].lower())

    def test_list_does_not_select_value_column(self):
        self.client.put(
            me_key_url("com.example.one"), {"a": 1}, format="json"
        )
        with CaptureQueriesContext(connection) as ctx:
            listed = self.client.get(ME_APP_DATA)
        self.assertEqual(listed.status_code, 200)
        sql = " ".join(q["sql"] for q in ctx.captured_queries).lower()
        # values("key", "byte_size") should not pull the JSON payload column.
        self.assertIn("byte_size", sql)
        self.assertNotIn('"value"', sql)
        self.assertNotIn(".value", sql)
