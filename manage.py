#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

def main():
    """Run administrative tasks."""
    # Use isolated test DB settings for `manage.py test` (empty test_<dbname>).
    # Override with --settings=... on the command line if needed.
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        os.environ["DJANGO_SETTINGS_MODULE"] = "dispatcharr.settings_test"
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Make sure it's installed and "
            "available on your PYTHONPATH environment variable."
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
