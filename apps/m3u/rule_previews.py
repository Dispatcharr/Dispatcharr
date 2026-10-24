"""Read-only, complete ordered-draft previews and explicit application."""

import regex
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin
from apps.channels.models import ChannelGroupM3UAccount, Stream
from apps.vod.models import M3UMovieRelation, M3USeriesRelation, M3UVODCategoryRelation

from .filter_catalog import (
    has_live_filter_catalog,
    iter_live_filter_catalog,
    live_filter_catalog_timestamp,
    live_filter_catalog_ready,
)
from .group_rules import (
    compile_group_rules,
    evaluate_group_rules,
    REGEX_TIMEOUT_SECONDS,
)
from .models import M3UAccount, M3UFilter, M3UGroupRule
from .filter_preview import selection_availability, selection_inventory
from .category_preview import (
    CategoryPreviewError,
    cached_preview,
    can_load_preview,
    load_preview,
)
from .serializers import (
    M3UFilterPreviewRequestSerializer,
    M3UFilterAvailabilitySerializer,
    M3UFilterSelectionSerializer,
    M3UGroupRuleOrderSerializer,
    M3UGroupRulePreviewRequestSerializer,
    M3UGroupRuleSerializer,
    M3UGroupContentQuerySerializer,
    M3UGroupContentAvailabilitySerializer,
    M3UPreviewResponseSerializer,
    M3URuleApplyResponseSerializer,
    M3URuleOrderSerializer,
    validate_unique_rule_matches,
    rule_result_fields,
)

PREVIEW_PARAMETERS = [
    OpenApiParameter("page", int, description="Page number, starting at 1."),
    OpenApiParameter("page_size", int, description="Rows per page, from 1 to 100."),
]


def _pagination(request):
    try:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 50))
    except (ValueError, TypeError) as exc:
        raise serializers.ValidationError("Invalid pagination.") from exc
    if page < 1 or not 1 <= page_size <= 100:
        raise serializers.ValidationError(
            "page must be positive and page_size between 1 and 100."
        )
    return page, page_size


def _draft_rows(request, serializer_class, model, *, existing_rules=()):
    serializer = serializer_class(
        data=request.data,
        context={"existing_group_rules": {str(row.pk): row for row in existing_rules}},
    )
    serializer.is_valid(raise_exception=True)
    target_id = serializer.validated_data["target_id"]
    rows = []
    ids = set()
    for values in serializer.validated_data["rules"]:
        values = dict(values)
        preview_id = values.pop("preview_id")
        values.pop("id", None)
        if preview_id in ids:
            raise serializers.ValidationError("Draft rule IDs must be unique.")
        ids.add(preview_id)
        row = model(**values)
        row.id = preview_id
        rows.append(row)
    if target_id not in ids:
        raise serializers.ValidationError(
            "The selected rule is missing from the draft."
        )
    rows.sort(key=lambda row: row.order)
    return rows, target_id


def _paged_matches(matches, page, page_size):
    start = (page - 1) * page_size
    end = start + page_size
    count = 0
    results = []
    for match in matches:
        if start <= count < end:
            results.append(match)
        count += 1
    return {"count": count, "results": results, "page": page, "page_size": page_size}


def _provider_content_response(rows, query, page, page_size):
    search = query.get("search", "").casefold()
    matches = (
        {"relation_id": index, "name": str(row.get("name") or "")}
        for index, row in sorted(
            enumerate(rows), key=lambda pair: str(pair[1].get("name") or "")
        )
        if search in str(row.get("name") or "").casefold()
    )
    result = _paged_matches(matches, page, page_size)
    result.update(content_source="provider", can_load_provider=False)
    return Response(M3UPreviewResponseSerializer(result).data)


def _reorder(queryset, request):
    serializer = M3URuleOrderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    ids = serializer.validated_data["ids"]
    positions = serializer.validated_data.get("positions", list(range(len(ids))))
    if len(positions) != len(ids) or len(set(positions)) != len(positions):
        raise serializers.ValidationError("Provide one unique position per saved rule.")
    if len(set(ids)) != len(ids):
        raise serializers.ValidationError("Rule IDs must be unique.")
    with transaction.atomic():
        rows = list(queryset.select_for_update())
        by_id = {row.id: row for row in rows}
        if set(ids) != set(by_id):
            raise serializers.ValidationError(
                "Include exactly the saved rules for this account and scope."
            )
        for position, row_id in zip(positions, ids):
            by_id[row_id].order = position
        queryset.model.objects.bulk_update(rows, ["order"])
    return Response(M3URuleApplyResponseSerializer({"updated": len(rows)}).data)


def _apply_group_matches(account, scope, matches):
    """Apply only this rule's winning fields, preserving unrelated defaults."""
    model = (
        ChannelGroupM3UAccount
        if scope == M3UGroupRule.Scope.LIVE
        else M3UVODCategoryRelation
    )
    by_id = {row["relation_id"]: row for row in matches}
    category_updates = []
    rows = list(
        model.objects.select_for_update().filter(id__in=by_id, m3u_account=account)
    )
    for row in rows:
        match = by_id[row.id]
        if match["would_enable"] is not None:
            row.enabled = match["would_enable"]
        if match["would_ignore"] is not None:
            row.ignored = match["would_ignore"]
        patch = match["metadata_defaults"]
        if scope != M3UGroupRule.Scope.LIVE:
            row.metadata_defaults = {**(row.metadata_defaults or {}), **patch}
        category_updates.append({
            "target_id": match["target_id"],
            "enabled": match["would_enable"],
            "ignored": match["would_ignore"],
            "metadata_defaults": patch,
        })
    if rows:
        model.objects.bulk_update(
            rows, ["enabled", "ignored"] if scope == "live" else ["enabled", "ignored", "metadata_defaults"]
        )
    states = {match["would_enable"] for match in matches}
    ignored_states = {match["would_ignore"] for match in matches}
    return {
        "updated": len(rows),
        "scope": scope,
        "enabled": states.pop() if len(states) == 1 else None,
        "ignored": ignored_states.pop() if len(ignored_states) == 1 else None,
        "target_ids": [row["target_id"] for row in matches],
        "category_updates": category_updates,
    }


def _imported_live_inventory(account_id):
    for stream in (
        Stream.objects.filter(m3u_account_id=account_id)
        .select_related("channel_group")
        .order_by("id")
        .iterator(chunk_size=2000)
    ):
        yield {
            "name": stream.name,
            "group": stream.channel_group.name if stream.channel_group else "",
            "url": stream.url or "",
        }


class StreamFilterPreviewMixin:
    @extend_schema(methods=["GET"], responses=M3UFilterAvailabilitySerializer)
    @extend_schema(
        methods=["POST"],
        request=M3UFilterSelectionSerializer,
        responses=M3UFilterAvailabilitySerializer,
        description=(
            "Check a draft category selection using cached previews only. "
            "Does not fetch, save selections or import content."
        ),
    )
    @action(detail=False, methods=["get", "post"], permission_classes=[IsAdmin])
    def availability(self, request, *args, **kwargs):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        if request.method == "POST":
            selection = M3UFilterSelectionSerializer(data=request.data)
            selection.is_valid(raise_exception=True)
            try:
                result = selection_availability(
                    account, selection.validated_data["group_ids"]
                )
            except CategoryPreviewError as exc:
                raise serializers.ValidationError(str(exc)) from exc
            return Response(M3UFilterAvailabilitySerializer(result).data)
        busy = account.status in (
            M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING,
        )
        failed = account.status == M3UAccount.Status.ERROR
        result = {
            "ready": not busy and not failed and live_filter_catalog_ready(account),
            "selected_count": account.channel_group.filter(enabled=True).count(),
            "refresh_in_progress": busy,
            "refresh_failed": failed,
            "last_completed_refresh": (
                live_filter_catalog_timestamp(account.id)
                if has_live_filter_catalog(account.id) else None
            ),
        }
        return Response(M3UFilterAvailabilitySerializer(result).data)

    @extend_schema(
        request=M3UFilterPreviewRequestSerializer,
        responses=M3UPreviewResponseSerializer,
        parameters=PREVIEW_PARAMETERS,
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="preview-draft",
        permission_classes=[IsAdmin],
    )
    def preview_draft(self, request, *args, **kwargs):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        page, page_size = _pagination(request)
        rows, target_id = _draft_rows(
            request, M3UFilterPreviewRequestSerializer, M3UFilter
        )
        compiled = [
            (
                row,
                regex.compile(
                    row.regex_pattern,
                    (
                        0
                        if (row.custom_properties or {}).get("case_sensitive", True)
                        else regex.IGNORECASE
                    ),
                ),
            )
            for row in rows
            if row.enabled
        ]
        draft_selection = "group_ids" in request.data
        if draft_selection:
            selection = M3UFilterSelectionSerializer(data=request.data)
            selection.is_valid(raise_exception=True)
            complete = True
            inventory = selection_inventory(
                account, selection.validated_data["group_ids"]
            )
        else:
            complete = has_live_filter_catalog(account.id)
            inventory = (
                iter_live_filter_catalog(account.id)
                if complete
                else _imported_live_inventory(account.id)
            )
        inventory_count = 0
        coverage = {str(row.id): 0 for row in rows}

        def matches():
            nonlocal inventory_count
            for stream in inventory:
                inventory_count += 1
                for row, pattern in compiled:
                    key = {"name": "name", "group": "group", "url": "url"}[
                        row.filter_type
                    ]
                    if not pattern.search(
                        stream.get(key) or "", timeout=REGEX_TIMEOUT_SECONDS
                    ):
                        continue
                    coverage[str(row.id)] += 1
                    if row.id == target_id:
                        yield {
                            "name": stream.get("name") or "",
                            "group": stream.get("group") or "",
                            "result": "exclude" if row.exclude else "include",
                        }
                    break

        try:
            response = _paged_matches(matches(), page, page_size)
        except CategoryPreviewError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        except TimeoutError as exc:
            raise serializers.ValidationError(
                "A regular expression took too long. Simplify it and retry."
            ) from exc
        except (OSError, ValueError) as exc:
            raise serializers.ValidationError(
                "The saved preview catalog is unavailable. Run a Live refresh and retry."
            ) from exc
        response.update(
            {
                "inventory_count": inventory_count,
                "rule_coverage": [
                    {"rule_id": rule_id, "count": count}
                    for rule_id, count in coverage.items()
                ],
                "catalog_complete": complete,
                "last_completed_refresh": (
                    live_filter_catalog_timestamp(account.id)
                    if complete and not draft_selection
                    else (None if draft_selection else account.updated_at)
                ),
                "refresh_in_progress": account.status
                in (M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING),
            }
        )
        return Response(M3UPreviewResponseSerializer(response).data)

    @extend_schema(
        request=M3URuleOrderSerializer, responses=M3URuleApplyResponseSerializer
    )
    @action(detail=False, methods=["post"], permission_classes=[IsAdmin])
    def reorder(self, request, *args, **kwargs):
        return _reorder(self.get_queryset(), request)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=M3UGroupRule.Scope.values,
                description="Filter import rules by content scope.",
            ),
        ],
    ),
)
class M3UGroupRuleViewSet(viewsets.ModelViewSet):
    queryset = M3UGroupRule.objects.all()
    serializer_class = M3UGroupRuleSerializer
    permission_classes = [IsAdmin]
    pagination_class = None

    def get_queryset(self):
        account_id = self.kwargs.get("account_id")
        if account_id is None:
            return self.queryset.none()
        queryset = self.queryset.filter(m3u_account_id=account_id)
        scope = self.request.query_params.get("scope")
        return queryset.filter(scope=scope) if scope else queryset

    def perform_create(self, serializer):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        serializer.save(m3u_account=account)

    @extend_schema(
        description="List category IDs with imported content for this account. Read-only; does not contact the provider or import anything.",
        responses=M3UGroupContentAvailabilitySerializer,
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="content-availability",
        permission_classes=[IsAdmin],
    )
    def content_availability(self, request, *args, **kwargs):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        available = {
            "live": list(
                Stream.objects.filter(m3u_account=account)
                .exclude(channel_group_id=None)
                .order_by("channel_group_id")
                .values_list("channel_group_id", flat=True)
                .distinct()
            )
        }
        for scope, model in (
            (M3UGroupRule.Scope.MOVIE, M3UMovieRelation),
            (M3UGroupRule.Scope.SERIES, M3USeriesRelation),
        ):
            available[scope] = list(
                model.objects.filter(m3u_account=account, category__category_type=scope)
                .order_by("category_id")
                .values_list("category_id", flat=True)
                .distinct()
            )
        return Response(M3UGroupContentAvailabilitySerializer(available).data)

    @extend_schema(
        parameters=PREVIEW_PARAMETERS + [M3UGroupContentQuerySerializer],
        responses=M3UPreviewResponseSerializer,
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="content-preview",
        permission_classes=[IsAdmin],
    )
    def content_preview(self, request, *args, **kwargs):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        query = M3UGroupContentQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        scope = query.validated_data["scope"]
        group_id = query.validated_data["group_id"]
        search = query.validated_data.get("search", "")
        page, page_size = _pagination(request)
        if scope == M3UGroupRule.Scope.LIVE:
            relation = get_object_or_404(
                ChannelGroupM3UAccount, m3u_account=account, channel_group_id=group_id
            )
            queryset = Stream.objects.filter(
                m3u_account=account, channel_group_id=group_id
            )
            title_field = "name"
        else:
            relation = get_object_or_404(
                M3UVODCategoryRelation,
                m3u_account=account,
                category_id=group_id,
                category__category_type=scope,
            )
            model = (
                M3UMovieRelation
                if scope == M3UGroupRule.Scope.MOVIE
                else M3USeriesRelation
            )
            title_field = (
                "movie__name" if scope == M3UGroupRule.Scope.MOVIE else "series__name"
            )
            queryset = model.objects.filter(m3u_account=account, category_id=group_id)
        can_load = False
        if not queryset.exists() and can_load_preview(account, scope, relation):
            rows = cached_preview(account, scope, relation)
            if rows is not None:
                return _provider_content_response(
                    rows, query.validated_data, page, page_size
                )
            can_load = True
        if search:
            queryset = queryset.filter(**{f"{title_field}__icontains": search})
        count = queryset.count()
        start = (page - 1) * page_size
        if scope == M3UGroupRule.Scope.LIVE:
            results = [
                {"relation_id": row_id, "name": name}
                for row_id, name in queryset.order_by(title_field, "id").values_list(
                    "id", title_field
                )[start : start + page_size]
            ]
        else:
            from apps.vod.metadata import category_key, category_metadata_map

            content_field = "movie" if scope == M3UGroupRule.Scope.MOVIE else "series"
            sources = list(
                queryset.select_related(content_field).order_by(title_field, "id")[
                    start : start + page_size
                ]
            )
            defaults = category_metadata_map(sources)
            results = [
                {
                    "relation_id": source.pk,
                    "name": getattr(source, content_field).name,
                    "source_metadata": source.effective_metadata(
                        category_defaults=defaults.get(category_key(source), {})
                    ),
                }
                for source in sources
            ]
        return Response(
            M3UPreviewResponseSerializer(
                {
                    "count": count,
                    "results": results,
                    "page": page,
                    "page_size": page_size,
                    "content_source": "imported",
                    "can_load_provider": can_load,
                }
            ).data
        )

    @extend_schema(
        description=(
            "Explicitly load one XC category into a private 15-minute cache. "
            "Does not import content or save category selections. A subsequent "
            "import can reuse the complete category payload."
        ),
        request=M3UGroupContentQuerySerializer,
        parameters=PREVIEW_PARAMETERS,
        responses=M3UPreviewResponseSerializer,
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="load-content-preview",
        permission_classes=[IsAdmin],
    )
    def load_content_preview(self, request, *args, **kwargs):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        query = M3UGroupContentQuerySerializer(data=request.data)
        query.is_valid(raise_exception=True)
        scope = query.validated_data["scope"]
        group_id = query.validated_data["group_id"]
        page, page_size = _pagination(request)
        if scope == M3UGroupRule.Scope.LIVE:
            relation = get_object_or_404(
                ChannelGroupM3UAccount, m3u_account=account, channel_group_id=group_id
            )
        else:
            relation = get_object_or_404(
                M3UVODCategoryRelation.objects.select_related("category"),
                m3u_account=account,
                category_id=group_id,
                category__category_type=scope,
            )
        try:
            rows = load_preview(account, scope, relation)
        except CategoryPreviewError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return _provider_content_response(rows, query.validated_data, page, page_size)

    def _matches(self, account, rules, target_id, scope, stats=None):
        compiled = compile_group_rules(rules)
        if scope == M3UGroupRule.Scope.LIVE:
            relations = (
                ChannelGroupM3UAccount.objects.filter(m3u_account=account)
                .select_related("channel_group")
                .order_by("id")
            )
            model = Stream
            name_field = "channel_group"
            key_field = "channel_group_id"
        else:
            relations = (
                M3UVODCategoryRelation.objects.filter(
                    m3u_account=account, category__category_type=scope
                )
                .select_related("category")
                .order_by("id")
            )
            model = (
                M3UMovieRelation
                if scope == M3UGroupRule.Scope.MOVIE
                else M3USeriesRelation
            )
            name_field = "category"
            key_field = "category_id"
        item_counts = dict(
            model.objects.filter(m3u_account=account).order_by().values(key_field)
            .annotate(total=Count("pk")).values_list(key_field, "total")
        )
        for relation in relations.iterator(chunk_size=2000):
            if stats is not None:
                stats["inventory_count"] += 1
            name = getattr(relation, name_field).name
            decision = evaluate_group_rules(
                compiled,
                group_name=name,
                default_enabled=relation.enabled,
            )
            winners = set(decision.metadata_rule_ids.values())
            if decision.matched_rule_id is not None:
                winners.add(decision.matched_rule_id)
            if stats is not None:
                for rule_id in winners:
                    stats["coverage"][str(rule_id)] += 1
                if "field_coverage" in stats:
                    for key, rule_id in decision.metadata_rule_ids.items():
                        stats["field_coverage"][str(rule_id)][key] += 1
                    if decision.matched_rule_id is not None:
                        counts = stats["field_coverage"][str(decision.matched_rule_id)]
                        counts["import"] += 1
            if target_id in winners:
                import_match = decision.matched_rule_id == target_id
                yield {
                    "relation_id": relation.id,
                    "name": name,
                    "target_id": getattr(relation, key_field),
                    "currently_enabled": relation.enabled,
                    "currently_ignored": relation.ignored,
                    "would_enable": (
                        decision.enabled if import_match else None
                    ),
                    "would_ignore": decision.ignored if import_match else None,
                    "action": decision.action if import_match else "keep",
                    "item_count": item_counts.get(getattr(relation, key_field), 0),
                    "metadata_defaults": decision.fields_for_rule(target_id),
                }

    @extend_schema(
        request=M3UGroupRulePreviewRequestSerializer,
        responses=M3UPreviewResponseSerializer,
        parameters=PREVIEW_PARAMETERS,
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="preview-draft",
        permission_classes=[IsAdmin],
    )
    def preview_draft(self, request, *args, **kwargs):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        page, page_size = _pagination(request)
        rows, target_id = _draft_rows(
            request,
            M3UGroupRulePreviewRequestSerializer,
            M3UGroupRule,
            existing_rules=account.group_rules.all(),
        )
        scopes = {row.scope for row in rows}
        if len(scopes) != 1:
            raise serializers.ValidationError(
                "All draft rules must use the same content scope."
            )
        scope = scopes.pop()
        stats = {
            "inventory_count": 0,
            "coverage": {str(row.id): 0 for row in rows},
        }
        if scope != M3UGroupRule.Scope.LIVE:
            stats["field_coverage"] = {
                str(row.id): {key: 0 for key in rule_result_fields(row)}
                for row in rows
            }
        try:
            response = _paged_matches(
                self._matches(account, rows, target_id, scope, stats), page, page_size
            )
        except TimeoutError as exc:
            raise serializers.ValidationError(
                "A regular expression took too long. Simplify it and retry."
            ) from exc
        catalog_scope = "live-groups" if scope == M3UGroupRule.Scope.LIVE else scope
        complete = has_live_filter_catalog(account.id, catalog_scope)
        timings = (account.custom_properties or {}).get("refresh_timings") or {}
        refresh_kind = "live" if scope == M3UGroupRule.Scope.LIVE else "vod"
        response.update(
            {
                "inventory_count": stats["inventory_count"],
                "rule_coverage": [
                    {"rule_id": rule_id, "count": count}
                    | (
                        {"field_counts": stats["field_coverage"][rule_id]}
                        if "field_coverage" in stats else {}
                    )
                    for rule_id, count in stats["coverage"].items()
                ],
                "catalog_complete": complete,
                "last_completed_refresh": (
                    live_filter_catalog_timestamp(account.id, catalog_scope)
                    if complete
                    else timings.get(f"{refresh_kind}_completed_at")
                    or (account.updated_at if refresh_kind == "live" else None)
                ),
                "refresh_in_progress": (
                    scope == M3UGroupRule.Scope.LIVE
                    and account.status
                    in (M3UAccount.Status.FETCHING, M3UAccount.Status.PARSING)
                ),
            }
        )
        return Response(M3UPreviewResponseSerializer(response).data)

    @extend_schema(request=None, responses=M3URuleApplyResponseSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    def apply(self, request, *args, **kwargs):
        rule = self.get_object()
        self.get_serializer(rule, data={}, partial=True).is_valid(raise_exception=True)
        if rule.requires_review:
            raise serializers.ValidationError(
                "Choose an import result and save this paused rule before applying it."
            )
        if not rule.enabled:
            raise serializers.ValidationError("Enable this rule before applying it.")
        rules = list(
            rule.m3u_account.group_rules.filter(scope=rule.scope).order_by(
                "order", "id"
            )
        )
        try:
            with transaction.atomic():
                M3UAccount.objects.select_for_update().get(pk=rule.m3u_account_id)
                matches = list(self._matches(rule.m3u_account, rules, rule.id, rule.scope))
                result = _apply_group_matches(rule.m3u_account, rule.scope, matches)
        except TimeoutError as exc:
            raise serializers.ValidationError(
                "A regular expression took too long. Nothing was applied."
            ) from exc
        return Response(
            M3URuleApplyResponseSerializer(result).data
        )

    @extend_schema(
        request=M3UGroupRulePreviewRequestSerializer,
        responses=M3URuleApplyResponseSerializer,
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="save-apply",
        permission_classes=[IsAdmin],
    )
    def save_apply(self, request, *args, **kwargs):
        account = get_object_or_404(M3UAccount, pk=self.kwargs["account_id"])
        rows, target_id = _draft_rows(
            request,
            M3UGroupRulePreviewRequestSerializer,
            M3UGroupRule,
            existing_rules=account.group_rules.all(),
        )
        scopes = {row.scope for row in rows}
        if len(scopes) != 1:
            raise serializers.ValidationError(
                "All draft rules must use the same scope."
            )
        scope = scopes.pop()
        target = next(row for row in rows if row.id == target_id)
        if target.requires_review:
            raise serializers.ValidationError(
                "Choose an import result before saving and applying this paused rule."
            )
        if not target.enabled:
            raise serializers.ValidationError("Enable this rule before applying it.")
        validate_unique_rule_matches(rows)
        with transaction.atomic():
            M3UAccount.objects.select_for_update().get(pk=account.pk)
            existing = {
                rule.id: rule
                for rule in account.group_rules.select_for_update().filter(scope=scope)
            }
            saved_ids = {int(row.id) for row in rows if row.id.isdigit()}
            if saved_ids != set(existing):
                raise serializers.ValidationError(
                    "The saved rules changed. Reload them and preview again."
                )
            saved_rows = []
            saved_target = None
            for row in rows:
                instance = existing.get(int(row.id)) if row.id.isdigit() else None
                values = {
                    field: getattr(row, field)
                    for field in M3UGroupRuleSerializer.Meta.fields
                    if field not in {"id", "requires_review"}
                }
                serializer = M3UGroupRuleSerializer(
                    instance, data=values, context={"validated_rule_list": True}
                )
                serializer.is_valid(raise_exception=True)
                saved = serializer.save(m3u_account=account)
                saved_rows.append(saved)
                if row.id == target_id:
                    saved_target = saved
            try:
                matches = list(
                    self._matches(account, saved_rows, saved_target.id, scope)
                )
            except TimeoutError as exc:
                raise serializers.ValidationError(
                    "A regular expression took too long. Nothing was saved or applied."
                ) from exc
            result = _apply_group_matches(account, scope, matches)
        return Response(
            M3URuleApplyResponseSerializer(result).data
        )

    @extend_schema(
        request=M3UGroupRuleOrderSerializer, responses=M3URuleApplyResponseSerializer
    )
    @action(detail=False, methods=["post"], permission_classes=[IsAdmin])
    def reorder(self, request, *args, **kwargs):
        serializer = M3UGroupRuleOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scope = serializer.validated_data["scope"]
        return _reorder(self.get_queryset().filter(scope=scope), request)
