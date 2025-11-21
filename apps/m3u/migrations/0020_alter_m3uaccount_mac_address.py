from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("m3u", "0019_m3uaccountmac"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- Spalte anlegen, falls sie noch nicht existiert
                ALTER TABLE m3u_m3uaccount
                ADD COLUMN IF NOT EXISTS mac_address varchar(255);

                -- Typ (zur Sicherheit) auf varchar(255) setzen
                ALTER TABLE m3u_m3uaccount
                ALTER COLUMN mac_address TYPE varchar(255);
            """,
            reverse_sql="""
                -- Beim Downgrade: Typ wieder auf varchar(17) stellen, falls Spalte existiert
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'm3u_m3uaccount'
                          AND column_name = 'mac_address'
                    ) THEN
                        ALTER TABLE m3u_m3uaccount
                        ALTER COLUMN mac_address TYPE varchar(17);
                    END IF;
                END;
                $$;
            """,
        ),
    ]
