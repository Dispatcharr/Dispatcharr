"""Admin API for the VOD profiles that shape Xtream Codes output per user."""

from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin
from apps.m3u.rule_previews import (
    PREVIEW_PARAMETERS,
    _draft_rows,
    _paged_matches,
    _pagination,
    _reorder,
)
from apps.m3u.serializers import (
    M3UGroupRuleOrderSerializer,
    M3UPreviewResponseSerializer,
    M3URuleApplyResponseSerializer,
)

from . import profiles
from .models import (
    M3UMovieRelation,
    M3USeriesRelation,
    VODProfile,
    VODProfileAssignment,
    VODProfileCategoryRule,
)
from .profile_serializers import (
    VODProfileCategoryRulePreviewRequestSerializer,
    VODProfileCategoryRuleSerializer,
    VODProfileSerializer,
)


class VODProfileViewSet(viewsets.ModelViewSet):
    serializer_class = VODProfileSerializer
    permission_classes = [IsAdmin]
    pagination_class = None

    def get_queryset(self):
        profiles.default_profile()
        return VODProfile.objects.prefetch_related(
            Prefetch(
                "assignments", queryset=VODProfileAssignment.objects.only("user_id")
            ),
            "category_rules",
        )

    def perform_destroy(self, instance):
        if instance.is_default:
            raise ValidationError(
                {"detail": "Make another profile the default before deleting it."}
            )
        instance.delete()


class VODProfileCategoryRuleViewSet(viewsets.ModelViewSet):
    """A profile's import rules, served like the M3U account import rules."""

    serializer_class = VODProfileCategoryRuleSerializer
    permission_classes = [IsAdmin]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def get_profile(self):
        return get_object_or_404(VODProfile, pk=self.kwargs["profile_id"])

    def get_queryset(self):
        # Schema generation has no URL arguments.
        rules = VODProfileCategoryRule.objects.filter(
            profile_id=self.kwargs.get("profile_id")
        ).order_by("order", "id")
        scope = self.request.query_params.get("scope")
        return rules.filter(scope=scope) if scope else rules

    @staticmethod
    def _check_unique(profile, values, instance=None):
        def value(field, default=None):
            return values.get(field, getattr(instance, field, default))

        if not value("enabled", True):
            return
        duplicate = (
            profile.category_rules.filter(
                enabled=True,
                scope=value("scope"),
                regex_pattern=value("regex_pattern"),
                case_sensitive=value("case_sensitive", False),
            )
            .exclude(pk=getattr(instance, "pk", None))
            .first()
        )
        if duplicate is not None:
            raise ValidationError(
                {
                    "regex_pattern": (
                        "An identical active match already exists "
                        f"(rule ID {duplicate.pk}). Edit that rule instead."
                    )
                }
            )

    def perform_create(self, serializer):
        profile = self.get_profile()
        self._check_unique(profile, serializer.validated_data)
        serializer.save(profile=profile)

    def perform_update(self, serializer):
        rule = serializer.instance
        self._check_unique(rule.profile, serializer.validated_data, rule)
        serializer.save()


    @staticmethod
    def _matches(profile, rules, target_id, scope, stats=None):
        """Categories the target rule decides, like the M3U rule preview."""
        choices = {
            choice["relation"]: choice["enabled"] for choice in profile.category_choices
        }
        current = {
            relation: decision.enabled
            for relation, *_rest, decision in profiles.category_rule_states(
                profile, enabled_only=True
            )
        }
        model = M3UMovieRelation if scope == "movie" else M3USeriesRelation
        item_counts = {
            (account, category): total
            for account, category, total in model.objects.order_by()
            .values("m3u_account_id", "category_id")
            .annotate(total=Count("pk"))
            .values_list("m3u_account_id", "category_id", "total")
        }
        for relation, account, category, relation_scope, name, decision in (
            profiles.category_rule_states(profile, rules, enabled_only=True)
        ):
            if relation_scope != scope:
                continue
            if stats is not None:
                stats["inventory_count"] += 1
                if decision.matched_rule_id is not None:
                    stats["coverage"][str(decision.matched_rule_id)] += 1
            if str(decision.matched_rule_id) == str(target_id):
                yield {
                    "relation_id": relation,
                    "name": name,
                    "target_id": relation,
                    "currently_enabled": choices.get(relation, current[relation]),
                    "currently_ignored": False,
                    "would_enable": decision.enabled,
                    "would_ignore": None,
                    "action": decision.action,
                    "item_count": item_counts.get((account, category), 0),
                }

    def _draft(self, request):
        rows, target_id = _draft_rows(
            request,
            VODProfileCategoryRulePreviewRequestSerializer,
            VODProfileCategoryRule,
        )
        scopes = {row.scope for row in rows}
        if len(scopes) != 1:
            raise ValidationError("All draft rules must use the same content scope.")
        return rows, target_id, scopes.pop()

    @extend_schema(
        request=VODProfileCategoryRulePreviewRequestSerializer,
        responses=M3UPreviewResponseSerializer,
        parameters=PREVIEW_PARAMETERS,
    )
    @action(detail=False, methods=["post"], url_path="preview-draft")
    def preview_draft(self, request, *args, **kwargs):
        profile = self.get_profile()
        page, page_size = _pagination(request)
        rows, target_id, scope = self._draft(request)
        stats = {"inventory_count": 0, "coverage": {str(row.id): 0 for row in rows}}
        try:
            response = _paged_matches(
                self._matches(profile, rows, target_id, scope, stats), page, page_size
            )
        except TimeoutError as exc:
            raise ValidationError(
                "A regular expression took too long. Simplify it and retry."
            ) from exc
        response.update(
            {
                "inventory_count": stats["inventory_count"],
                "rule_coverage": [
                    {"rule_id": rule_id, "count": count}
                    for rule_id, count in stats["coverage"].items()
                ],
            }
        )
        return Response(M3UPreviewResponseSerializer(response).data)

    @extend_schema(
        request=VODProfileCategoryRulePreviewRequestSerializer,
        responses=M3URuleApplyResponseSerializer,
    )
    @action(detail=False, methods=["post"], url_path="save-apply")
    def save_apply(self, request, *args, **kwargs):
        """Save the rules; the target rule then decides its matches again."""
        rows, target_id, scope = self._draft(request)
        target = next(row for row in rows if row.id == target_id)
        if not target.enabled:
            raise ValidationError("Enable this rule before applying it.")
        with transaction.atomic():
            profile = get_object_or_404(
                VODProfile.objects.select_for_update(), pk=self.kwargs["profile_id"]
            )
            existing = {
                rule.id: rule
                for rule in profile.category_rules.select_for_update().filter(
                    scope=scope
                )
            }
            if {int(row.id) for row in rows if row.id.isdigit()} != set(existing):
                raise ValidationError(
                    "The saved rules changed. Reload them and preview again."
                )
            saved_rows, saved_target = [], None
            for row in rows:
                serializer = VODProfileCategoryRuleSerializer(
                    existing.get(int(row.id)) if row.id.isdigit() else None,
                    data={
                        field: getattr(row, field)
                        for field in VODProfileCategoryRuleSerializer.Meta.fields
                        if field != "id"
                    },
                )
                serializer.is_valid(raise_exception=True)
                saved = serializer.save(profile=profile)
                saved_rows.append(saved)
                if row.id == target_id:
                    saved_target = saved
            try:
                matches = list(
                    self._matches(profile, saved_rows, saved_target.id, scope)
                )
            except TimeoutError as exc:
                raise ValidationError(
                    "A regular expression took too long. Nothing was saved or applied."
                ) from exc
            # Manual choices of the matched categories give way to the rule.
            applied = {match["relation_id"] for match in matches}
            profile.category_choices = [
                choice
                for choice in profile.category_choices
                if choice["relation"] not in applied
            ]
            profile.save(update_fields=["category_choices", "updated_at"])
        return Response(
            M3URuleApplyResponseSerializer(
                {
                    "updated": len(matches),
                    "category_updates": [
                        {
                            "target_id": match["relation_id"],
                            "enabled": match["would_enable"],
                            "ignored": None,
                            "metadata_defaults": {},
                        }
                        for match in matches
                    ],
                }
            ).data
        )

    @extend_schema(
        request=M3UGroupRuleOrderSerializer, responses=M3URuleApplyResponseSerializer
    )
    @action(detail=False, methods=["post"])
    def reorder(self, request, *args, **kwargs):
        serializer = M3UGroupRuleOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _reorder(
            self.get_queryset().filter(scope=serializer.validated_data["scope"]),
            request,
        )
