from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.m3u.serializers import M3UFilterSerializer

from . import profiles
from .models import M3UVODCategoryRelation, VODProfile, VODProfileCategoryRule


class ProfileUsersField(serializers.ListField):
    child = serializers.IntegerField()

    def get_attribute(self, instance):
        return sorted(assignment.user_id for assignment in instance.assignments.all())


def _normalized(normalize, value, *args):
    try:
        return normalize(value, *args)
    except profiles.FieldError as error:
        detail = {error.field: [str(error)]}
        if error.index is not None:
            detail = {str(error.index): detail}
        raise serializers.ValidationError(detail)
    except ValueError as error:
        raise serializers.ValidationError(str(error))


class VODProfileSerializer(serializers.ModelSerializer):
    users = ProfileUsersField(
        read_only=True,
        help_text="Users assigned to this profile in their user settings.",
    )
    excluded_titles = serializers.JSONField(
        required=False,
        help_text="Movies and series this profile never offers, by type and ID.",
    )
    category_rule_states = serializers.SerializerMethodField(
        help_text="Whether the saved import rules enable each account category."
    )
    category_rule_counts = serializers.SerializerMethodField(
        help_text="Enabled import rules per scope."
    )

    class Meta:
        model = VODProfile
        fields = (
            "id",
            "name",
            "is_default",
            "is_active",
            "output_mode",
            "output_groups",
            "name_template",
            "title_source",
            "metadata_source",
            "category_choices",
            "category_rule_states",
            "category_rule_counts",
            "content_filters",
            "excluded_titles",
            "edition_rules",
            "ranking",
            "audio_language_order",
            "subtitle_language_order",
            "provider_order",
            "users",
            "catalog_status",
            "catalog_counts",
            "catalog_progress",
            "catalog_started_at",
            "catalog_completed_at",
            "catalog_error",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "catalog_status",
            "catalog_counts",
            "catalog_progress",
            "catalog_started_at",
            "catalog_completed_at",
            "catalog_error",
            "created_at",
            "updated_at",
        )
        # The single-default constraint is enforced in _save by moving it.
        extra_kwargs = {"is_default": {"validators": []}}

    @extend_schema_field(serializers.DictField(child=serializers.BooleanField()))
    def get_category_rule_states(self, profile):
        return {
            str(relation): decision.enabled
            for relation, *_rest, decision in profiles.category_rule_states(profile)
        }

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_category_rule_counts(self, profile):
        counts = dict.fromkeys(VODProfileCategoryRule.Scope.values, 0)
        for rule in profile.category_rules.all():
            if rule.enabled:
                counts[rule.scope] += 1
        return counts

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a profile name.")
        duplicate = VODProfile.objects.filter(name__iexact=value)
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError("A profile with this name exists.")
        return value

    def validate_category_choices(self, value):
        choices = _normalized(profiles.normalize_category_choices, value)
        relations = {choice["relation"] for choice in choices}
        known = set(
            M3UVODCategoryRelation.objects.filter(pk__in=relations).values_list(
                "pk", flat=True
            )
        )
        if relations - known:
            raise serializers.ValidationError("Select existing categories.")
        return choices

    def validate_excluded_titles(self, value):
        titles = _normalized(profiles.normalize_excluded_titles, value)
        for content_type, model in profiles.TITLE_MODELS.items():
            ids = {
                title["id"] for title in titles if title["content_type"] == content_type
            }
            if len(ids) != model.objects.filter(pk__in=ids).count():
                raise serializers.ValidationError("Select existing titles.")
        return titles

    def validate_name_template(self, value):
        return _normalized(profiles.normalize_name_template, value)

    def validate_title_source(self, value):
        from .library import library_settings

        allowed = (
            profiles.PROVIDER_TITLES,
            profiles.CLEAN_TITLES,
            *library_settings()["languages"],
        )
        if value not in allowed:
            raise serializers.ValidationError(
                "Choose provider, clean or a Library metadata language."
            )
        return value

    def validate_content_filters(self, value):
        return _normalized(profiles.normalize_content_filters, value)

    def validate_edition_rules(self, value):
        return _normalized(profiles.normalize_edition_rules, value)

    def validate_ranking(self, value):
        return _normalized(profiles.normalize_ranking, value)

    def validate_audio_language_order(self, value):
        return _normalized(
            profiles.normalize_language_order, value, "DUB language order"
        )

    def validate_subtitle_language_order(self, value):
        return _normalized(
            profiles.normalize_language_order, value, "SUB language order"
        )

    def validate_provider_order(self, value):
        return _normalized(profiles.normalize_provider_order, value)

    def validate(self, attrs):
        current = self.instance

        def value(field):
            return attrs.get(field, getattr(current, field, None))

        if (
            current is not None
            and current.is_default
            and attrs.get("is_default", True) is False
        ):
            raise serializers.ValidationError(
                {"is_default": "Make another profile the default instead."}
            )
        if value("is_default") and value("is_active") is False:
            raise serializers.ValidationError(
                {"is_active": "The default profile is always active."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        return self._save(VODProfile(), validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        return self._save(instance, validated_data)

    def _save(self, profile, data):
        if data.get("is_default"):
            VODProfile.objects.select_for_update().filter(is_default=True).exclude(
                pk=profile.pk
            ).update(is_default=False)
        for field, item in data.items():
            setattr(profile, field, item)
        profile.save()
        return profile


class VODProfileCategoryRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = VODProfileCategoryRule
        fields = (
            "id",
            "scope",
            "regex_pattern",
            "action",
            "case_sensitive",
            "enabled",
            "order",
        )

    validate_regex_pattern = M3UFilterSerializer.validate_regex_pattern


class VODProfileCategoryRulePreviewRowSerializer(VODProfileCategoryRuleSerializer):
    preview_id = serializers.CharField(max_length=128)

    class Meta(VODProfileCategoryRuleSerializer.Meta):
        fields = VODProfileCategoryRuleSerializer.Meta.fields + ("preview_id",)


class VODProfileCategoryRulePreviewRequestSerializer(serializers.Serializer):
    target_id = serializers.CharField(max_length=128)
    rules = VODProfileCategoryRulePreviewRowSerializer(many=True, allow_empty=False)
