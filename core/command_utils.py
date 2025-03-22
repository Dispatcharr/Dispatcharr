import sys
import os

def is_management_command(excluded_commands=None):
    """
    Detect if we're running a Django management command like migrate, collectstatic, etc.

    Args:
        excluded_commands: List of commands that should still use Redis (e.g. runserver)

    Returns:
        bool: True if we're running a management command
    """
    # First check if we're in build mode
    if os.environ.get("DISPATCHARR_BUILD") == "1":
        return True

    if excluded_commands is None:
        excluded_commands = ['runserver', 'runworker', 'daphne']

    # Check if we're running via manage.py
    if not ('manage.py' in sys.argv[0]):
        return False

    # Check if we have a command argument
    if len(sys.argv) > 1:
        command = sys.argv[1]
        # Return False if command is in excluded list - these commands DO need Redis
        if command in excluded_commands:
            return False
        # Otherwise it's a command that should work without Redis
        return True

    return False
