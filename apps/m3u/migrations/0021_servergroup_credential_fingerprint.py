# Generated manually for shared credential connection pools (#1137)

from django.db import migrations, models

from apps.m3u.connection_pool import (
    compute_credential_fingerprint,
    extract_credentials_from_stream_url,
)


def _historical_account_fingerprint(M3UAccount, M3UAccountProfile, Stream, account):
    """Resolve fingerprint for migration using historical models only."""
    fingerprint = compute_credential_fingerprint(
        account.username or "",
        account.password or "",
    )
    if fingerprint:
        return fingerprint

    sample_url = (
        Stream.objects.filter(m3u_account_id=account.pk)
        .exclude(url="")
        .values_list("url", flat=True)
        .first()
    )
    if sample_url:
        url_user, url_pass = extract_credentials_from_stream_url(sample_url)
        return compute_credential_fingerprint(url_user or "", url_pass or "")

    return None


def backfill_credential_pools(apps, schema_editor):
    from django.db.models import Min

    M3UAccount = apps.get_model("m3u", "M3UAccount")
    ServerGroup = apps.get_model("m3u", "ServerGroup")
    M3UAccountProfile = apps.get_model("m3u", "M3UAccountProfile")
    Stream = apps.get_model("dispatcharr_channels", "Stream")

    seen = {}
    for account in M3UAccount.objects.all():
        props = account.custom_properties or {}
        if props.get("exclude_from_credential_pool"):
            continue
        if account.server_group_id:
            group = ServerGroup.objects.filter(pk=account.server_group_id).first()
            if group and not group.credential_fingerprint:
                continue

        fingerprint = _historical_account_fingerprint(
            M3UAccount, M3UAccountProfile, Stream, account
        )
        if not fingerprint:
            continue

        if fingerprint not in seen:
            short = fingerprint[:16]
            group, _ = ServerGroup.objects.get_or_create(
                credential_fingerprint=fingerprint,
                defaults={
                    "name": f"credential-pool-{short}",
                    "max_streams": 0,
                },
            )
            seen[fingerprint] = group
        else:
            group = seen[fingerprint]

        M3UAccount.objects.filter(pk=account.pk).update(server_group_id=group.pk)

    for group in seen.values():
        agg = M3UAccount.objects.filter(
            server_group_id=group.pk, max_streams__gt=0
        ).aggregate(min_limit=Min("max_streams"))
        new_max = agg["min_limit"] or 0
        if group.max_streams != new_max:
            ServerGroup.objects.filter(pk=group.pk).update(max_streams=new_max)


class Migration(migrations.Migration):

    dependencies = [
        ("m3u", "0020_servergroup_max_streams"),
        ("dispatcharr_channels", "0037_auto_sync_overhaul"),
    ]

    operations = [
        migrations.AddField(
            model_name="servergroup",
            name="credential_fingerprint",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Auto-assigned hash for accounts sharing the same IPTV credentials",
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(backfill_credential_pools, migrations.RunPython.noop),
    ]
