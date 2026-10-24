from datetime import datetime, timedelta, timezone
import logging
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone as django_timezone
from core.models import CoreSettings, UserAgent
import re
from django.dispatch import receiver
from apps.channels.models import StreamProfile
from django_celery_beat.models import PeriodicTask
from core.utils import custom_properties_as_dict
from .utils import parse_m3u_hash_keys

CUSTOM_M3U_ACCOUNT_NAME = "custom"
logger = logging.getLogger(__name__)


class M3UAccount(models.Model):
    class SetupStep(models.TextChoices):
        ACCOUNT = "account", "Account"
        CONTENT = "content", "Content"
        EPG = "epg", "Optional EPG"
        CATEGORIES = "categories", "Categories"

    class Types(models.TextChoices):
        STADNARD = "STD", "Standard"
        XC = "XC", "Xtream Codes"

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        FETCHING = "fetching", "Fetching"
        PARSING = "parsing", "Parsing"
        ERROR = "error", "Error"
        SUCCESS = "success", "Success"
        PENDING_SETUP = "pending_setup", "Pending Setup"
        DISABLED = "disabled", "Disabled"

    """Represents an M3U Account for IPTV streams."""
    name = models.CharField(
        max_length=255, unique=True, help_text="Unique name for this M3U account"
    )
    server_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        help_text="The base URL of the M3U server (optional if a file is uploaded)",
    )
    file_path = models.CharField(max_length=255, blank=True, null=True)
    server_group = models.ForeignKey(
        "ServerGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="m3u_accounts",
        help_text="The server group this M3U account belongs to",
    )
    max_streams = models.PositiveIntegerField(
        default=0, help_text="Maximum number of concurrent streams (0 for unlimited)"
    )
    is_active = models.BooleanField(
        default=True, help_text="Set to false to deactivate this M3U account"
    )
    created_at = models.DateTimeField(
        auto_now_add=True, help_text="Time when this account was created"
    )
    updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Time when this account was last successfully refreshed",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IDLE
    )
    setup_step = models.CharField(
        max_length=16, choices=SetupStep.choices, blank=True, default="",
        help_text="Unfinished guided setup step, independent of refresh status.",
    )
    last_message = models.TextField(
        null=True,
        blank=True,
        help_text="Last status message, including success results or error information",
    )
    user_agent = models.ForeignKey(
        "core.UserAgent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="m3u_accounts",
        help_text="The User-Agent associated with this M3U account.",
    )
    locked = models.BooleanField(
        default=False, help_text="Protected - can't be deleted or modified"
    )
    stream_profile = models.ForeignKey(
        StreamProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="m3u_accounts",
    )
    account_type = models.CharField(choices=Types.choices, default=Types.STADNARD)
    username = models.CharField(max_length=255, null=True, blank=True)
    password = models.CharField(max_length=255, null=True, blank=True)
    custom_properties = models.JSONField(default=dict, blank=True, null=True)
    refresh_interval = models.IntegerField(default=0)
    refresh_task = models.ForeignKey(
        PeriodicTask, on_delete=models.SET_NULL, null=True, blank=True
    )
    vod_refresh_interval = models.IntegerField(default=0)
    vod_refresh_task = models.ForeignKey(
        PeriodicTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    vod_refresh_after_live = models.BooleanField(
        default=True,
        help_text="Refresh VOD after Live TV unless a separate VOD schedule is configured.",
    )
    stale_stream_days = models.PositiveIntegerField(
        default=7,
        help_text="Number of days after which a stream will be removed if not seen in the M3U source.",
    )
    priority = models.PositiveIntegerField(
        default=0,
        help_text="Priority for VOD provider selection (higher numbers = higher priority). Used when multiple providers offer the same content.",
    )
    def __str__(self):
        return self.name

    def get_effective_hash_keys(self):
        """Return the list of hash key fields to use for this account's streams.

        Uses this account's own ``hash_key`` override (stored under
        ``custom_properties["hash_key"]``) when set; otherwise falls back to
        the global ``m3u_hash_key`` CoreSettings value. A missing key means
        this account inherits the global default. Tokens are stripped and
        limited to the known hash field set.
        """
        custom_props = self.custom_properties or {}
        if isinstance(custom_props, dict):
            keys = parse_m3u_hash_keys(custom_props.get("hash_key"))
            if keys:
                return keys
        return parse_m3u_hash_keys(CoreSettings.get_m3u_hash_key())

    def update_setup_step_for_account_type(self, previous_account_type):
        """Keep unfinished setup aligned with the edited connection type."""
        if not self.setup_step or self.setup_step in {
            self.SetupStep.ACCOUNT, self.SetupStep.CONTENT,
        }:
            return
        if self.account_type != self.Types.XC:
            self.setup_step = self.SetupStep.CATEGORIES
        elif previous_account_type != self.Types.XC:
            self.setup_step = self.SetupStep.EPG

    def get_refresh_schedule(self, *, vod=False):
        """Describe the existing Beat schedule without changing or running it."""
        task = self.vod_refresh_task if vod else self.refresh_task
        if task is None:
            return {"enabled": False, "last_run_at": None, "next_run_at": None}

        next_run = None
        if task.enabled:
            try:
                now = django_timezone.now()
                reference = task.last_run_at or task.date_changed or now
                due = task.schedule.is_due(reference)
                seconds = 0 if due.is_due else max(0, float(due.next))
                next_run = now + timedelta(seconds=seconds)
            except (AttributeError, TypeError, ValueError, OverflowError):
                logger.warning(
                    "Could not calculate next refresh for task %s",
                    task.name,
                    exc_info=True,
                )
        return {
            "enabled": bool(task.enabled),
            "last_run_at": task.last_run_at,
            "next_run_at": next_run,
        }

    @classmethod
    def get_vod_category_selection_counts(cls, account_ids):
        """Count saved selections for multiple accounts without loading categories."""
        from apps.vod.models import M3UVODCategoryRelation

        rows = (
            M3UVODCategoryRelation.objects.filter(m3u_account_id__in=account_ids)
            .order_by()
            .values("m3u_account_id", "category__category_type")
            .annotate(
                total=models.Count("id"),
                selected=models.Count("id", filter=models.Q(enabled=True)),
            )
        )
        counts = {}
        for row in rows:
            counts.setdefault(row["m3u_account_id"], {})[
                row["category__category_type"]
            ] = {"selected": row["selected"], "total": row["total"]}
        return counts

    def get_category_selection_counts(self, *, vod_counts=None):
        """Summarize saved account memberships, including disabled categories."""
        if vod_counts is None:
            vod_counts = self.get_vod_category_selection_counts([self.pk]).get(
                self.pk, {}
            )
        live = list(self.channel_group.all())
        return {
            "live": {
                "selected": sum(row.enabled for row in live),
                "total": len(live),
            },
            **{
                scope: vod_counts.get(scope, {"selected": 0, "total": 0})
                for scope in ("movie", "series")
            },
        }

    def clean(self):
        if self.max_streams < 0:
            raise ValidationError("Max streams cannot be negative.")

    def display_action(self):
        return "Exclude" if self.exclude else "Include"

    @classmethod
    def get_custom_account(cls):
        return cls.objects.get(name=CUSTOM_M3U_ACCOUNT_NAME, locked=True)

    def get_user_agent(self):
        """Return the account-assigned UserAgent model, or None for system default.

        Returns None when this account has no User-Agent of its own so callers
        do not pay a Postgres hit for the system default row. For outbound
        HTTP headers and XC clients, use ``get_user_agent_string()``, which
        resolves the Redis-cached system default when needed.
        """
        if self.user_agent_id:
            return self.user_agent
        return None

    def get_user_agent_string(self):
        """Return the User-Agent string for provider requests.

        Uses this account's configured User-Agent when set; otherwise the
        Redis-cached system default from ``CoreSettings.get_default_user_agent()``.
        """
        if self.user_agent_id:
            ua = self.user_agent
            if ua is not None and ua.user_agent:
                return ua.user_agent
        return CoreSettings.get_default_user_agent()

    def save(self, *args, **kwargs):
        if self.custom_properties is not None and not isinstance(
            self.custom_properties, dict
        ):
            self.custom_properties = custom_properties_as_dict(self.custom_properties)

        # Prevent auto_now behavior by handling updated_at manually
        if "update_fields" in kwargs and "updated_at" not in kwargs["update_fields"]:
            # Don't modify updated_at for regular updates
            kwargs.setdefault("update_fields", [])
            if "updated_at" in kwargs["update_fields"]:
                kwargs["update_fields"].remove("updated_at")
        super().save(*args, **kwargs)

    # def get_channel_groups(self):
    #     return ChannelGroup.objects.filter(m3u_account__m3u_account=self)

    # def is_channel_group_enabled(self, channel_group):
    #     """Check if the specified ChannelGroup is enabled for this M3UAccount."""
    #     return self.channel_group.filter(channel_group=channel_group, enabled=True).exists()

    # def get_enabled_streams(self):
    #     """Return all streams linked to this account with enabled ChannelGroups."""
    #     return self.streams.filter(channel_group__in=ChannelGroup.objects.filter(m3u_account__enabled=True))


class M3UFilter(models.Model):
    """Defines filters for M3U accounts based on stream name or group title."""

    FILTER_TYPE_CHOICES = (
        ("group", "Group"),
        ("name", "Stream Name"),
        ("url", "Stream URL"),
    )

    m3u_account = models.ForeignKey(
        M3UAccount,
        on_delete=models.CASCADE,
        related_name="filters",
        help_text="The M3U account this filter is applied to.",
    )
    filter_type = models.CharField(
        max_length=50,
        choices=FILTER_TYPE_CHOICES,
        default="group",
        help_text="Filter based on either group title or stream name.",
    )
    regex_pattern = models.CharField(
        max_length=200, help_text="A regex pattern to match streams or groups."
    )
    exclude = models.BooleanField(
        default=True,
        help_text="If True, matching items are excluded; if False, only matches are included.",
    )
    enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    custom_properties = models.JSONField(default=dict, blank=True, null=True)

    def applies_to(self, stream_name, group_name):
        if not self.enabled:
            return False
        target = group_name if self.filter_type == "group" else stream_name
        return bool(re.search(self.regex_pattern, target, re.IGNORECASE))

    def clean(self):
        try:
            re.compile(self.regex_pattern)
        except re.error:
            raise ValidationError(f"Invalid regex pattern: {self.regex_pattern}")

    def __str__(self):
        filter_type_display = dict(self.FILTER_TYPE_CHOICES).get(
            self.filter_type, "Unknown"
        )
        exclude_status = "Exclude" if self.exclude else "Include"
        return f"[{self.m3u_account.name}] {filter_type_display}: {self.regex_pattern} ({exclude_status})"


class M3UGroupRule(models.Model):
    """Ordered import policy for newly discovered provider groups."""

    class Scope(models.TextChoices):
        LIVE = "live", "Live TV"
        MOVIE = "movie", "VOD Movies"
        SERIES = "series", "VOD Series"

    class MatchField(models.TextChoices):
        GROUP_NAME = "group_name", "Group name"
        ITEM_NAME = "item_name", "Contained item name"

    class MatchMode(models.TextChoices):
        ANY = "any", "Any item"
        ALL = "all", "All items"

    class Action(models.TextChoices):
        # Keep the retired metadata-only result readable for review.
        KEEP = "keep", "Keep import selection"
        ENABLE = "enable", "Import enabled"
        DISABLE = "disable", "Import disabled"
        IGNORE = "ignore", "Ignore"

    m3u_account = models.ForeignKey(
        M3UAccount, on_delete=models.CASCADE, related_name="group_rules"
    )
    scope = models.CharField(max_length=10, choices=Scope.choices)
    match_field = models.CharField(
        max_length=20, choices=MatchField.choices, default=MatchField.GROUP_NAME
    )
    match_mode = models.CharField(
        max_length=10, choices=MatchMode.choices, default=MatchMode.ANY
    )
    regex_pattern = models.CharField(max_length=500)
    action = models.CharField(
        max_length=10, choices=Action.choices, default=Action.DISABLE
    )
    case_sensitive = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    metadata_defaults = models.JSONField(default=dict, blank=True)

    @property
    def requires_review(self):
        # Retain retired results for review without rewriting saved policies.
        return self.action not in {self.Action.ENABLE, self.Action.DISABLE, self.Action.IGNORE}

    class Meta:
        ordering = ("scope", "order", "id")
        indexes = [
            models.Index(
                fields=("m3u_account", "scope", "enabled", "order"),
                name="m3u_group_rule_lookup_idx",
            )
        ]

    def clean(self):
        import regex

        try:
            regex.compile(self.regex_pattern)
        except regex.error as exc:
            raise ValidationError({"regex_pattern": str(exc)}) from exc


class ServerGroup(models.Model):
    """
    Groups M3U accounts that share provider credentials.

    Accounts assigned to the same server group share credential-scoped connection
    counters when their logins match. Limits come from each account profile's
    max_streams, not from the group itself.
    """

    name = models.CharField(
        max_length=100, unique=True, help_text="Unique name for this server group."
    )

    def __str__(self):
        return self.name


class M3UAccountProfile(models.Model):
    """Represents a profile associated with an M3U Account."""

    m3u_account = models.ForeignKey(
        "M3UAccount",
        on_delete=models.CASCADE,
        related_name="profiles",
        help_text="The M3U account this profile belongs to.",
    )
    name = models.CharField(
        max_length=255, help_text="Name for the M3U account profile"
    )
    is_default = models.BooleanField(
        default=False, help_text="Set to false to deactivate this profile"
    )
    max_streams = models.PositiveIntegerField(
        default=0, help_text="Maximum number of concurrent streams (0 for unlimited)"
    )
    is_active = models.BooleanField(
        default=True, help_text="Set to false to deactivate this profile"
    )
    search_pattern = models.CharField(
        max_length=255,
    )
    replace_pattern = models.CharField(
        max_length=255,
    )
    current_viewers = models.PositiveIntegerField(default=0)
    custom_properties = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Custom properties for storing account information from provider (e.g., XC account details, expiration dates)"
    )
    exp_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Account expiration date, auto-synced from custom_properties on save",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["m3u_account", "name"], name="unique_account_name"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.m3u_account.name})"

    def save(self, *args, **kwargs):
        """Auto-sync exp_date from custom_properties for XC accounts on every save.
        For non-XC accounts, exp_date is set directly and left untouched here.

        Leftover XC user_info on a Standard account must not overwrite a
        manually set expiration (e.g. after converting XC to Standard).
        """
        if self.custom_properties is not None and not isinstance(
            self.custom_properties, dict
        ):
            self.custom_properties = custom_properties_as_dict(self.custom_properties)

        is_xc = (
            bool(self.m3u_account_id)
            and self.m3u_account.account_type == M3UAccount.Types.XC
        )
        if is_xc:
            parsed = self._parse_exp_date_from_custom_properties()
            if parsed is not None:
                self.exp_date = parsed
        # else: keep whatever exp_date is already set (manual entry for non-XC)
        super().save(*args, **kwargs)

    @staticmethod
    def _parse_exp_date(raw_value):
        """Parse a raw exp_date value (unix timestamp or ISO string) into a datetime."""
        if raw_value is None:
            return None
        try:
            if isinstance(raw_value, (int, float)):
                return datetime.fromtimestamp(float(raw_value), tz=timezone.utc)
            elif isinstance(raw_value, str):
                try:
                    return datetime.fromtimestamp(float(raw_value), tz=timezone.utc)
                except ValueError:
                    return datetime.fromisoformat(raw_value)
        except (ValueError, TypeError, OSError):
            pass
        return None

    def _parse_exp_date_from_custom_properties(self):
        """Extract exp_date from custom_properties JSON."""
        if not self.custom_properties:
            return None
        user_info = self.custom_properties.get('user_info', {})
        return self._parse_exp_date(user_info.get('exp_date'))

    def get_account_expiration(self):
        """Get account expiration date — uses the dedicated field if set, otherwise parses JSON."""
        if self.exp_date:
            return self.exp_date
        return self._parse_exp_date_from_custom_properties()

    def get_account_status(self):
        """Get account status from custom properties if available"""
        if not self.custom_properties:
            return None

        user_info = self.custom_properties.get('user_info', {})
        return user_info.get('status')

    def get_max_connections(self):
        """Get maximum connections from custom properties if available"""
        if not self.custom_properties:
            return None

        user_info = self.custom_properties.get('user_info', {})
        return user_info.get('max_connections')

    def get_active_connections(self):
        """Get active connections from custom properties if available"""
        if not self.custom_properties:
            return None

        user_info = self.custom_properties.get('user_info', {})
        return user_info.get('active_cons')

    def get_last_refresh(self):
        """Get last refresh timestamp from custom properties if available"""
        if not self.custom_properties:
            return None

        last_refresh = self.custom_properties.get('last_refresh')
        if last_refresh:
            try:
                from datetime import datetime
                return datetime.fromisoformat(last_refresh)
            except (ValueError, TypeError):
                pass

        return None


@receiver(models.signals.post_save, sender=M3UAccount)
def create_profile_for_m3u_account(sender, instance, created, **kwargs):
    """Create the default profile on account create; keep its max_streams in sync on update.

    Account form Max Streams is enforced via the default profile's max_streams
    (connection pool / playback). Sync only when max_streams is part of the
    account save and the value actually changed. Status/last_message saves
    during M3U refresh must not load or rewrite the default profile, or they
    can race with XC account-info refresh and clobber exp_date /
    custom_properties.

    Uses QuerySet.update (not model.save) so we never touch other profile
    columns and avoid profile.save() side effects (XC exp_date JSON sync,
    expiration-notification signal).
    """
    if created:
        M3UAccountProfile.objects.create(
            m3u_account=instance,
            name=f"{instance.name} Default",
            max_streams=instance.max_streams,
            is_default=True,
            is_active=True,
            search_pattern="^(.*)$",
            replace_pattern="$1",
        )
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "max_streams" not in update_fields:
        return

    M3UAccountProfile.objects.filter(
        m3u_account=instance,
        is_default=True,
    ).exclude(max_streams=instance.max_streams).update(
        max_streams=instance.max_streams
    )
