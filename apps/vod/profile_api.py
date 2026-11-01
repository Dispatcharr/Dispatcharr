"""Admin API for the VOD profiles that shape Xtream Codes output per user."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin
from apps.m3u.models import M3UAccount
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

from . import profile_catalog, profiles
from .models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    VODProfile,
    VODProfileAssignment,
    VODProfileCategoryRule,
)
from .profile_serializers import (
    VODProfileCategoryRulePreviewRequestSerializer,
    VODProfileCategoryRuleSerializer,
    VODProfileOptionsSerializer,
    VODProfilePreviewRequestSerializer,
    VODProfilePreviewSerializer,
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

    @extend_schema(request=None, responses=VODProfileSerializer)
    @action(detail=True, methods=["post"])
    def rebuild(self, request, pk=None):
        profile = self.get_object()
        if not profile.is_active:
            raise ValidationError({"detail": "Activate the profile first."})
        if profile.catalog_status != VODProfile.CatalogStatus.BUILDING:
            profile.catalog_status = VODProfile.CatalogStatus.PENDING
            profile.save(update_fields=["catalog_status"])
        profile_catalog.request_catalog_build([profile.pk], countdown=0)
        return Response(self.get_serializer(profile).data)

    @extend_schema(responses=VODProfileOptionsSerializer)
    @action(detail=False, methods=["get"])
    def options(self, request):
        from .library import library_settings
        from .media_languages import MEDIA_LANGUAGE_OPTIONS
        from .metadata import RESOLUTIONS, VIDEO_FEATURES

        users = get_user_model().objects.order_by("username")
        categories = M3UVODCategoryRelation.objects.order_by(
            "m3u_account__name", "category__category_type", "category__name"
        )
        return Response(
            VODProfileOptionsSerializer(
                {
                    "users": users.values("id", "username"),
                    "accounts": M3UAccount.objects.filter(
                        category_relations__isnull=False
                    )
                    .distinct()
                    .order_by("name")
                    .values("id", "name"),
                    "categories": categories.values(
                        "id",
                        "enabled",
                        "custom_properties",
                        "m3u_account_id",
                        "category_id",
                        "category__name",
                        "category__category_type",
                    ),
                    "languages": MEDIA_LANGUAGE_OPTIONS,
                    "metadata_languages": library_settings()["languages"],
                    "resolutions": list(RESOLUTIONS),
                    "video_features": sorted(VIDEO_FEATURES),
                }
            ).data
        )

    @extend_schema(
        request=VODProfilePreviewRequestSerializer,
        responses=VODProfilePreviewSerializer,
    )
    @action(detail=False, methods=["post"])
    def preview(self, request):
        serializer = VODProfilePreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # The saved profile's import rules apply to its unsaved settings.
        result = profile_catalog.preview(
            VODProfile(pk=data.get("profile_id"), **data["profile"]),
            data["content_type"],
            search=data.get("search", ""),
            excluded=data["excluded"],
            account=data.get("account"),
            category=data.get("category"),
            page=data["page"],
            page_size=data["page_size"],
        )
        return Response(VODProfilePreviewSerializer(result).data)


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
        profile_catalog.refresh_catalog(profile)

    def perform_update(self, serializer):
        rule = serializer.instance
        self._check_unique(rule.profile, serializer.validated_data, rule)
        profile_catalog.refresh_catalog(serializer.save().profile)

    def perform_destroy(self, instance):
        profile = instance.profile
        instance.delete()
        profile_catalog.refresh_catalog(profile)

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
        profile_catalog.refresh_catalog(profile)
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
        response = _reorder(
            self.get_queryset().filter(scope=serializer.validated_data["scope"]),
            request,
        )
        profile_catalog.refresh_catalog(self.get_profile())
        return response
