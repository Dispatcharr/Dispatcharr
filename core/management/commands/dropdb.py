import sys
import psycopg2
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection

class Command(BaseCommand):
    help = "Drop the entire database (schema and data) and recreate it. (PostgreSQL only)"

    def handle(self, *args, **options):
        db_settings = settings.DATABASES['default']
        db_name = db_settings['NAME']
        user = db_settings['USER']
        password = db_settings['PASSWORD']
        host = db_settings.get('HOST', 'postgres')
        port = db_settings.get('PORT', 5432)

        self.stdout.write(self.style.WARNING(
            f"WARNING: This will irreversibly drop the entire database '{db_name}'!"
        ))
        confirm = input("Type 'yes' to proceed: ")
        if confirm.lower() != 'yes':
            self.stdout.write("Aborted. No changes made.")
            return

        # Close Django's current connection to the target DB
        connection.close()

        # For PostgreSQL, we need to connect to a different database (e.g. the maintenance database "postgres")
        maintenance_db = 'postgres'
        try:
            self.stdout.write("Connecting to maintenance database...")
            conn = psycopg2.connect(dbname=maintenance_db, user=user, password=password, host=host, port=port)
            conn.autocommit = True
            cur = conn.cursor()
            self.stdout.write(f"Dropping database '{db_name}'...")
            cur.execute(f"DROP DATABASE IF EXISTS {db_name};")
            self.stdout.write(f"Creating database '{db_name}'...")
            cur.execute(f"CREATE DATABASE {db_name};")
            cur.close()
            conn.close()
            self.stdout.write(self.style.SUCCESS(f"Database '{db_name}' has been dropped and recreated."))
            self.stdout.write("Now run 'python manage.py migrate' to reapply your migrations.")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error dropping/creating database: {e}"))
            sys.exit(1)
