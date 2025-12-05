# Generated migration to replace {time} placeholders with {starttime}

import re
from django.db import migrations


def migrate_time_placeholders(apps, schema_editor):
    """
    Replace {time} with {starttime} and {time24} with {starttime24}
    in all dummy EPG source custom_properties templates.
    """
    EPGSource = apps.get_model('epg', 'EPGSource')

    # Fields that contain templates with placeholders
    template_fields = [
        'title_template',
        'description_template',
        'upcoming_title_template',
        'upcoming_description_template',
        'ended_title_template',
        'ended_description_template',
        'channel_logo_url',
        'program_poster_url',
    ]

    # Get all dummy EPG sources
    dummy_sources = EPGSource.objects.filter(source_type='dummy')

    updated_count = 0
    for source in dummy_sources:
        if not source.custom_properties:
            continue

        modified = False
        custom_props = source.custom_properties.copy()

        for field in template_fields:
            if field in custom_props and custom_props[field]:
                original_value = custom_props[field]

                # Replace {time24} first (before {time}) to avoid double replacement
                # e.g., {time24} shouldn't become {starttime24} via {time} -> {starttime}
                new_value = original_value
                new_value = re.sub(r'\{time24\}', '{starttime24}', new_value)
                new_value = re.sub(r'\{time\}', '{starttime}', new_value)

                if new_value != original_value:
                    custom_props[field] = new_value
                    modified = True

        if modified:
            source.custom_properties = custom_props
            source.save(update_fields=['custom_properties'])
            updated_count += 1

    if updated_count > 0:
        print(f"Migration complete: Updated {updated_count} dummy EPG source(s) with new placeholder names.")
    else:
        print("No dummy EPG sources needed placeholder updates.")


def reverse_migration(apps, schema_editor):
    """
    Reverse the migration by replacing {starttime} back to {time}.
    """
    EPGSource = apps.get_model('epg', 'EPGSource')

    template_fields = [
        'title_template',
        'description_template',
        'upcoming_title_template',
        'upcoming_description_template',
        'ended_title_template',
        'ended_description_template',
        'channel_logo_url',
        'program_poster_url',
    ]

    dummy_sources = EPGSource.objects.filter(source_type='dummy')

    updated_count = 0
    for source in dummy_sources:
        if not source.custom_properties:
            continue

        modified = False
        custom_props = source.custom_properties.copy()

        for field in template_fields:
            if field in custom_props and custom_props[field]:
                original_value = custom_props[field]

                # Reverse the replacements
                new_value = original_value
                new_value = re.sub(r'\{starttime24\}', '{time24}', new_value)
                new_value = re.sub(r'\{starttime\}', '{time}', new_value)

                if new_value != original_value:
                    custom_props[field] = new_value
                    modified = True

        if modified:
            source.custom_properties = custom_props
            source.save(update_fields=['custom_properties'])
            updated_count += 1

    if updated_count > 0:
        print(f"Reverse migration complete: Reverted {updated_count} dummy EPG source(s) to old placeholder names.")


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0019_alter_programdata_sub_title'),
    ]

    operations = [
        migrations.RunPython(migrate_time_placeholders, reverse_migration),
    ]
