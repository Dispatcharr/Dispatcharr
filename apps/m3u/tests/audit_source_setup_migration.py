"""Exercise fresh and historical 03 migrations on synthetic, isolated data only."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


def migrate(target, *, historical=False):
    executor = MigrationExecutor(connection)
    if historical:
        executor.loader = MigrationLoader(connection, replace_migrations=False)
    executor.migrate(target)
    return executor.loader.project_state(target).apps


def run():
    if connection.vendor != "postgresql" or not connection.settings_dict[
        "NAME"
    ].startswith("test_"):
        raise RuntimeError(
            "This audit requires an isolated test_* PostgreSQL database."
        )

    replacement = ("m3u", "0021_source_setup_squashed")
    before = [("m3u", "0020_separate_live_vod_refresh")]
    migrate(before)
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan([replacement])
    assert [(migration.name, backwards) for migration, backwards in plan] == [
        (replacement[1], False)
    ]
    state = migrate([replacement])
    Account = state.get_model("m3u", "M3UAccount")
    assert "setup_step" in {field.name for field in Account._meta.fields}
    assert "xc_live_refresh_min_age_minutes" not in {
        field.name for field in Account._meta.fields
    }
    print("FRESH_SOURCE_SETUP_WITHOUT_RETIRED_FIELD_OK", flush=True)

    # A deployed, partially applied historical chain must finish normally.
    migrate(before)
    state = migrate([("m3u", "0024_m3uaccount_setup_navigation")], historical=True)
    Account = state.get_model("m3u", "M3UAccount")
    Rule = state.get_model("m3u", "M3UGroupRule")
    account = Account.objects.create(
        name="Synthetic legacy setup",
        is_active=False,
        setup_step="categories",
        vod_refresh_after_live=False,
        xc_live_refresh_min_age_minutes=55,
        custom_properties={"enable_vod": True},
    )
    rule = Rule.objects.create(
        m3u_account=account, scope="movie", regex_pattern="Synthetic", action="disable"
    )
    expected = Account.objects.filter(pk=account.pk).values().get()
    expected.pop("xc_live_refresh_min_age_minutes")
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    state = MigrationExecutor(connection).loader.project_state().apps
    assert (
        state.get_model("m3u", "M3UAccount")
        .objects.filter(pk=account.pk)
        .values()
        .get()
        == expected
    )
    assert (
        state.get_model("m3u", "M3UGroupRule").objects.get(pk=rule.pk).regex_pattern
        == "Synthetic"
    )
    assert replacement in MigrationRecorder(connection).applied_migrations()
    print("PARTIAL_LEGACY_SETUP_AND_RULES_PRESERVED_OK", flush=True)

    # The already-complete historical chain needs a recorder update, not DDL.
    applied_before = set(MigrationRecorder(connection).applied_migrations())
    MigrationRecorder(connection).record_unapplied(*replacement)
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    assert executor.migration_plan(targets) == []
    executor.migrate(targets)
    assert set(MigrationRecorder(connection).applied_migrations()) == applied_before
    assert (
        state.get_model("m3u", "M3UAccount")
        .objects.filter(pk=account.pk)
        .values()
        .get()
        == expected
    )
    print("COMPLETE_LEGACY_SETUP_REPLACEMENT_IS_NOOP_OK", flush=True)

    # Channel provenance backfills only an unambiguous owning category.
    state = migrate([("dispatcharr_channels", "0039_add_radio_fields"), replacement])
    Account = state.get_model("m3u", "M3UAccount")
    Group = state.get_model("dispatcharr_channels", "ChannelGroup")
    Membership = state.get_model("dispatcharr_channels", "ChannelGroupM3UAccount")
    Channel = state.get_model("dispatcharr_channels", "Channel")
    Stream = state.get_model("dispatcharr_channels", "Stream")
    Link = state.get_model("dispatcharr_channels", "ChannelStream")
    owner = Account.objects.create(
        name="Synthetic cleanup owner",
        is_active=False,
        custom_properties={"orphan_channel_cleanup": "never"},
    )
    backup = Account.objects.create(name="Synthetic cleanup backup", is_active=False)
    first = Group.objects.create(name="Synthetic first group")
    second = Group.objects.create(name="Synthetic second group")
    membership = Membership.objects.create(m3u_account=owner, channel_group=first)
    Membership.objects.create(m3u_account=owner, channel_group=second)
    primary = Stream.objects.create(
        name="Synthetic primary",
        url="https://example.invalid/primary",
        m3u_account=owner,
        channel_group=first,
        stream_hash="synthetic-migration-primary",
    )
    alternate = Stream.objects.create(
        name="Synthetic alternate",
        url="https://example.invalid/alternate",
        m3u_account=owner,
        channel_group=second,
        stream_hash="synthetic-migration-alternate",
    )
    backup_stream = Stream.objects.create(
        name="Synthetic backup",
        url="https://example.invalid/backup",
        m3u_account=backup,
        channel_group=second,
        stream_hash="synthetic-migration-backup",
    )
    channel = Channel.objects.create(
        name="Synthetic clear owner", auto_created=True, auto_created_by=owner
    )
    ambiguous = Channel.objects.create(
        name="Synthetic ambiguous owner", auto_created=True, auto_created_by=owner
    )
    for target, streams in (
        (channel, (primary, backup_stream)),
        (ambiguous, (primary, alternate)),
    ):
        for stream in streams:
            Link.objects.create(channel=target, stream=stream)
    state = migrate(
        [("dispatcharr_channels", "0040_channel_auto_created_from"), replacement]
    )
    Channel = state.get_model("dispatcharr_channels", "Channel")
    Membership = state.get_model("dispatcharr_channels", "ChannelGroupM3UAccount")
    assert Channel.objects.get(pk=channel.pk).auto_created_from_id == membership.pk
    assert Channel.objects.get(pk=ambiguous.pk).auto_created_from_id is None
    assert (
        Membership.objects.get(pk=membership.pk).custom_properties[
            "orphan_channel_cleanup"
        ]
        == "never"
    )
    print("CHANNEL_CATEGORY_PROVENANCE_AND_CLEANUP_BACKFILL_OK", flush=True)


run()
