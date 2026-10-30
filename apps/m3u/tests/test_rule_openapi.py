"""Keep rule query parameters and reorder contracts aligned with validation."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import include, path
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema
from rest_framework.exceptions import ValidationError

from apps.m3u.api_urls import router
from apps.m3u.models import M3UGroupRule
from apps.m3u.rule_previews import M3UGroupRuleViewSet
from apps.m3u.serializers import M3UGroupRuleOrderSerializer, M3URuleOrderSerializer


class RuleOpenApiTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        names = {
            "m3u-group-rules-list",
            "m3u-group-rules-reorder",
            "m3u-filters-reorder",
        }
        patterns = [pattern for pattern in router.urls if pattern.name in names]
        cls.schema = SchemaGenerator(
            patterns=[path("api/m3u/", include(patterns))]
        ).get_schema(public=True)

    def request_schema(self, path):
        schema = self.schema["paths"][path]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        name = schema["$ref"].rsplit("/", 1)[-1]
        return self.schema["components"]["schemas"][name]

    def test_rule_contracts_generate_valid_openapi(self):
        validate_schema(self.schema)

    def test_rule_list_documents_optional_content_scope(self):
        operation = self.schema["paths"][
            "/api/m3u/accounts/{account_id}/group-rules/"
        ]["get"]
        parameter = next(
            item for item in operation["parameters"] if item["name"] == "scope"
        )
        self.assertEqual(parameter["in"], "query")
        self.assertFalse(parameter.get("required", False))
        self.assertEqual(parameter["schema"]["type"], "string")
        self.assertEqual(
            set(parameter["schema"]["enum"]), set(M3UGroupRule.Scope.values)
        )

    def test_list_scope_parameter_does_not_leak_into_create(self):
        operation = self.schema["paths"][
            "/api/m3u/accounts/{account_id}/group-rules/"
        ]["post"]
        self.assertNotIn(
            "scope", [item["name"] for item in operation.get("parameters", [])]
        )

    def test_group_rule_reorder_requires_scope(self):
        schema = self.request_schema(
            "/api/m3u/accounts/{account_id}/group-rules/reorder/"
        )
        self.assertIn("scope", schema["required"])
        self.assertIn("ids", schema["required"])
        self.assertNotIn("positions", schema["required"])

    def test_stream_filter_reorder_keeps_scope_optional(self):
        schema = self.request_schema(
            "/api/m3u/accounts/{account_id}/filters/reorder/"
        )
        self.assertNotIn("scope", schema["required"])
        self.assertIn("ids", schema["required"])


class RuleOrderValidationTests(SimpleTestCase):
    def test_group_rule_reorder_accepts_each_content_scope(self):
        for scope in M3UGroupRule.Scope.values:
            with self.subTest(scope=scope):
                data = {"ids": [2, 1], "positions": [0, 2], "scope": scope}
                serializer = M3UGroupRuleOrderSerializer(data=data)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data, data)

    def test_group_rule_reorder_rejects_missing_or_invalid_scope_before_querying(self):
        for data, code in (
            ({"ids": []}, "required"),
            ({"ids": [], "scope": "invalid"}, "invalid_choice"),
        ):
            with self.subTest(data=data), patch.object(
                M3UGroupRuleViewSet, "get_queryset"
            ) as get_queryset:
                with self.assertRaises(ValidationError) as error:
                    M3UGroupRuleViewSet().reorder(SimpleNamespace(data=data))
                self.assertEqual(error.exception.status_code, 400)
                self.assertEqual(error.exception.detail["scope"][0].code, code)
                get_queryset.assert_not_called()

    def test_stream_filter_order_validation_does_not_require_scope(self):
        serializer = M3URuleOrderSerializer(data={"ids": [2, 1]})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"ids": [2, 1]})
