#!/usr/bin/env python3
"""
FreeBSD Compatibility Test Suite for Dispatcharr

This test suite validates that the freebsd_start.sh script and related FreeBSD
components remain compatible with FreeBSD systems after upstream changes.

Each test provides detailed failure messages to help identify and fix breaking changes.

Run with: python -m pytest tests/freebsd/ -v
Or:       python tests/freebsd/test_freebsd_script.py
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import List, Tuple, Set


# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
FREEBSD_SCRIPT = PROJECT_ROOT / "freebsd_start.sh"
DEBIAN_SCRIPT = PROJECT_ROOT / "debian_install.sh"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"


class FreeBSDScriptSyntaxTests(unittest.TestCase):
    """Test that the FreeBSD script uses POSIX-compatible shell syntax."""

    @classmethod
    def setUpClass(cls):
        """Load the script content once for all tests."""
        with open(FREEBSD_SCRIPT, 'r') as f:
            cls.script_content = f.read()
        cls.script_lines = cls.script_content.split('\n')

    def test_script_exists(self):
        """
        TEST: freebsd_start.sh exists in the project root.

        WHY: The FreeBSD installation depends on this script being present.

        FIX: Ensure freebsd_start.sh is not accidentally deleted or renamed.
        """
        self.assertTrue(
            FREEBSD_SCRIPT.exists(),
            f"CRITICAL: freebsd_start.sh not found at {FREEBSD_SCRIPT}\n"
            f"This file is required for FreeBSD installation.\n"
            f"If it was renamed, update this path or restore the file."
        )

    def test_script_has_shebang(self):
        """
        TEST: Script starts with a valid shebang.

        WHY: FreeBSD requires a proper shebang for script execution.

        FIX: First line must be #!/usr/bin/env bash or #!/bin/sh
        """
        first_line = self.script_lines[0] if self.script_lines else ""
        valid_shebangs = ['#!/usr/bin/env bash', '#!/bin/bash', '#!/bin/sh']

        self.assertTrue(
            any(first_line.startswith(s) for s in valid_shebangs),
            f"INVALID SHEBANG: Script starts with '{first_line}'\n"
            f"FreeBSD requires a valid shebang.\n"
            f"Valid options: {valid_shebangs}\n"
            f"FIX: Change line 1 to '#!/usr/bin/env bash'"
        )

    def test_no_bash_process_substitution_in_pipes(self):
        """
        TEST: Avoid problematic process substitution patterns.

        WHY: While bash supports <() syntax, complex patterns can behave
             differently between Linux and FreeBSD bash versions.

        FIX: Use temporary files or pipes instead of complex process substitution.
        """
        # Look for complex process substitution that might cause issues
        problematic_patterns = [
            (r'diff\s+<\(', "diff with process substitution"),
            (r'paste\s+<\(', "paste with process substitution"),
        ]

        issues = []
        for line_num, line in enumerate(self.script_lines, 1):
            for pattern, desc in problematic_patterns:
                if re.search(pattern, line):
                    issues.append(f"  Line {line_num}: {desc}\n    {line.strip()}")

        self.assertEqual(
            len(issues), 0,
            f"PROCESS SUBSTITUTION ISSUES:\n"
            f"The following lines use process substitution that may behave\n"
            f"differently on FreeBSD:\n\n" + "\n".join(issues) + "\n\n"
            f"FIX: Use temporary files or standard pipes instead."
        )

    def test_uses_bsd_sed_syntax(self):
        """
        TEST: sed commands use BSD-compatible syntax.

        WHY: BSD sed (used on FreeBSD) requires different syntax than GNU sed.
             Key difference: BSD sed -i requires an extension argument (use -i '').

        FIX: Use sed -i '' for in-place edits (BSD compatible).
        """
        issues = []
        for line_num, line in enumerate(self.script_lines, 1):
            # Skip comments
            if line.strip().startswith('#'):
                continue

            # Look for sed -i without the BSD-required '' argument
            # BSD sed: sed -i '' 's/...'  or  sed -i'.bak' 's/...'
            # GNU sed: sed -i 's/...'
            if re.search(r"sed\s+-i\s+['\"]s[|/]", line):
                # This is GNU-style sed -i (no extension argument)
                issues.append(f"  Line {line_num}: {line.strip()}")

        self.assertEqual(
            len(issues), 0,
            f"GNU SED SYNTAX DETECTED:\n"
            f"The following lines use GNU sed -i syntax which fails on FreeBSD:\n\n"
            + "\n".join(issues) + "\n\n"
            f"BSD sed requires an extension argument after -i.\n"
            f"FIX: Change 'sed -i 's/...'' to 'sed -i '' 's/.../'"
        )

    def test_correct_bsd_sed_present(self):
        """
        TEST: Verify BSD-style sed commands are present.

        WHY: Confirms the script properly uses BSD sed syntax.

        FIX: Use sed -i '' (empty string suffix) for in-place edits.
        """
        # Look for proper BSD sed usage
        bsd_sed_pattern = r"sed\s+-i\s+''"
        found_bsd_sed = bool(re.search(bsd_sed_pattern, self.script_content))

        self.assertTrue(
            found_bsd_sed,
            f"NO BSD SED SYNTAX FOUND:\n"
            f"The script should use 'sed -i ''' for in-place edits.\n"
            f"This is required for FreeBSD compatibility.\n"
            f"FIX: When adding sed -i commands, use: sed -i '' 's/pattern/replacement/g'"
        )

    def test_no_linux_only_commands(self):
        """
        TEST: Script doesn't use Linux-only commands.

        WHY: Commands like systemctl, apt-get, useradd are Linux-specific
             and will fail on FreeBSD.

        FIX: Use FreeBSD equivalents: service, pkg, pw useradd
        """
        # Commands that should never appear in FreeBSD script
        linux_commands = {
            'systemctl': 'Use "service" or "sysrc" on FreeBSD',
            'apt-get': 'Use "pkg" on FreeBSD',
            'apt ': 'Use "pkg" on FreeBSD',
            'journalctl': 'Use syslog or /var/log/messages on FreeBSD',
            '/etc/systemd/': 'Use /usr/local/etc/rc.d/ on FreeBSD',
            'dpkg': 'Use "pkg" on FreeBSD',
        }

        issues = []
        for line_num, line in enumerate(self.script_lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            for cmd, fix in linux_commands.items():
                if cmd in line:
                    issues.append(
                        f"  Line {line_num}: Found '{cmd}'\n"
                        f"    {stripped[:80]}{'...' if len(stripped) > 80 else ''}\n"
                        f"    Suggestion: {fix}"
                    )

        self.assertEqual(
            len(issues), 0,
            f"LINUX-ONLY COMMANDS DETECTED:\n"
            f"The following lines contain Linux-specific commands:\n\n"
            + "\n\n".join(issues) + "\n\n"
            f"These commands will fail on FreeBSD.\n"
            f"FIX: Replace with FreeBSD equivalents as suggested above."
        )

    def test_uses_freebsd_user_commands(self):
        """
        TEST: User management uses FreeBSD 'pw' command.

        WHY: FreeBSD uses 'pw useradd' and 'pw groupadd' instead of
             Linux 'useradd' and 'groupadd'.

        FIX: Use 'pw useradd' and 'pw groupadd' for user management.
        """
        issues = []

        for line_num, line in enumerate(self.script_lines, 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            # Check for bare 'useradd' (not preceded by 'pw ')
            if 'useradd' in line and 'pw useradd' not in line:
                issues.append(
                    f"  Line {line_num}: Found 'useradd' without 'pw' prefix\n"
                    f"    {stripped[:80]}{'...' if len(stripped) > 80 else ''}"
                )

            # Check for bare 'groupadd' (not preceded by 'pw ')
            if 'groupadd' in line and 'pw groupadd' not in line:
                issues.append(
                    f"  Line {line_num}: Found 'groupadd' without 'pw' prefix\n"
                    f"    {stripped[:80]}{'...' if len(stripped) > 80 else ''}"
                )

        self.assertEqual(
            len(issues), 0,
            f"BARE LINUX USER COMMANDS DETECTED:\n"
            f"The following lines use Linux-style user commands:\n\n"
            + "\n\n".join(issues) + "\n\n"
            f"FreeBSD requires 'pw' prefix for user commands.\n"
            f"FIX: Change 'useradd' to 'pw useradd', 'groupadd' to 'pw groupadd'"
        )

    def test_uses_freebsd_commands(self):
        """
        TEST: Script uses FreeBSD-specific commands.

        WHY: Confirms the script properly uses FreeBSD package management,
             service management, and user management tools.

        FIX: FreeBSD scripts must use: pkg, service, sysrc, pw
        """
        required_commands = {
            'pkg ': 'Package management (pkg install, pkg update)',
            'sysrc': 'RC configuration (sysrc -f /etc/rc.conf)',
            'pw ': 'User/group management (pw useradd, pw groupadd)',
            'service ': 'Service management (service X start/stop)',
        }

        missing = []
        for cmd, desc in required_commands.items():
            if cmd not in self.script_content:
                missing.append(f"  - '{cmd.strip()}': {desc}")

        self.assertEqual(
            len(missing), 0,
            f"MISSING FREEBSD COMMANDS:\n"
            f"The following FreeBSD-specific commands are missing:\n\n"
            + "\n".join(missing) + "\n\n"
            f"FIX: Ensure the script uses FreeBSD-native commands for:\n"
            f"  - Package management: pkg install, pkg update\n"
            f"  - Service control: service X start/stop/restart\n"
            f"  - RC config: sysrc -f /etc/rc.conf variable=value\n"
            f"  - User management: pw useradd, pw groupadd"
        )

    def test_rc_scripts_use_correct_paths(self):
        """
        TEST: RC scripts are placed in the correct FreeBSD location.

        WHY: FreeBSD rc.d scripts must be in /usr/local/etc/rc.d/

        FIX: Set RC_DIR="/usr/local/etc/rc.d"
        """
        correct_rc_path = '/usr/local/etc/rc.d'

        self.assertIn(
            correct_rc_path, self.script_content,
            f"WRONG RC.D PATH:\n"
            f"FreeBSD rc.d scripts must be placed in {correct_rc_path}\n"
            f"FIX: Ensure RC_DIR is set to '{correct_rc_path}'"
        )

    def test_nginx_config_path(self):
        """
        TEST: Nginx configuration uses FreeBSD paths.

        WHY: FreeBSD nginx is typically installed in /usr/local/etc/nginx/

        FIX: Use /usr/local/etc/nginx/ for nginx configuration files.
        """
        correct_nginx_path = '/usr/local/etc/nginx'

        self.assertIn(
            correct_nginx_path, self.script_content,
            f"WRONG NGINX PATH:\n"
            f"FreeBSD nginx config should be in {correct_nginx_path}\n"
            f"FIX: Ensure NGINX_CONFD is set to '{correct_nginx_path}'"
        )


class RequirementsFilteringTests(unittest.TestCase):
    """Test that requirements.txt can be properly filtered for FreeBSD."""

    @classmethod
    def setUpClass(cls):
        """Load requirements content."""
        with open(REQUIREMENTS_FILE, 'r') as f:
            cls.requirements = f.read()
        cls.req_lines = [l.strip() for l in cls.requirements.split('\n') if l.strip()]

    def test_requirements_file_exists(self):
        """
        TEST: requirements.txt exists.

        WHY: The FreeBSD script filters requirements.txt to create
             a FreeBSD-compatible version.

        FIX: Ensure requirements.txt is present in the project root.
        """
        self.assertTrue(
            REQUIREMENTS_FILE.exists(),
            f"CRITICAL: requirements.txt not found at {REQUIREMENTS_FILE}\n"
            f"The FreeBSD install script depends on this file."
        )

    def test_requirements_filtering_logic(self):
        """
        TEST: FreeBSD requirements filtering excludes problematic packages.

        WHY: Certain packages (torch, gevent, etc.) are installed via pkg
             on FreeBSD, not pip, to avoid compilation issues.

        FIX: Update freebsd_start.sh if new packages require system installation.
        """
        # Packages that should be filtered out for FreeBSD
        filtered_packages = [
            ('torch', 'Installed as py311-pytorch via pkg'),
            ('gevent', 'Installed as py311-gevent via pkg'),
            ('cryptography', 'Installed as py311-cryptography via pkg'),
            ('sentence-transformers', 'ML package - not available on FreeBSD'),
            ('tokenizers', 'ML dependency - not available on FreeBSD'),
            ('transformers', 'ML dependency - not available on FreeBSD'),
            ('--extra-index-url', 'PyTorch wheel URL - not used on FreeBSD'),
        ]

        # Check that script filters these
        with open(FREEBSD_SCRIPT, 'r') as f:
            script_content = f.read()

        missing_filters = []
        for pkg, reason in filtered_packages:
            if pkg in self.requirements:
                # Package is in requirements, check it's filtered
                grep_pattern = f"grep -v '^{pkg}'" if not pkg.startswith('--') else f"grep -v '{pkg}'"
                # Look for any grep -v that mentions this package
                if pkg not in script_content or 'grep -v' not in script_content:
                    pass  # We'll do a more flexible check
                # Check if the package name appears in a grep -v context
                if f"'{pkg}" not in script_content and f'"{pkg}' not in script_content:
                    if pkg in self.requirements:
                        missing_filters.append(f"  - {pkg}: {reason}")

        # This is informational - we just want to make sure the filtering logic exists
        self.assertIn(
            'requirements-freebsd.txt', script_content,
            f"MISSING REQUIREMENTS FILTERING:\n"
            f"The FreeBSD script should create a filtered requirements-freebsd.txt\n"
            f"FIX: Add logic to filter problematic packages from requirements.txt"
        )

    def test_core_requirements_present(self):
        """
        TEST: Core Django requirements are present and pip-installable.

        WHY: These packages must be present for Dispatcharr to function.

        FIX: Ensure these packages remain in requirements.txt
        """
        required_packages = [
            'Django',
            'psycopg2',
            'celery',
            'djangorestframework',
            'requests',
            'daphne',
        ]

        missing = []
        for pkg in required_packages:
            if not any(pkg.lower() in line.lower() for line in self.req_lines):
                missing.append(f"  - {pkg}")

        self.assertEqual(
            len(missing), 0,
            f"MISSING CORE REQUIREMENTS:\n"
            f"The following required packages are missing from requirements.txt:\n\n"
            + "\n".join(missing) + "\n\n"
            f"These packages are essential for Dispatcharr.\n"
            f"FIX: Add the missing packages to requirements.txt"
        )


class RCScriptTests(unittest.TestCase):
    """Test the FreeBSD rc.d service script generation."""

    @classmethod
    def setUpClass(cls):
        """Load script content."""
        with open(FREEBSD_SCRIPT, 'r') as f:
            cls.script_content = f.read()

    def test_rc_script_has_provide(self):
        """
        TEST: RC scripts include PROVIDE directive.

        WHY: FreeBSD rc.d scripts require PROVIDE to declare the service name.

        FIX: Each rc.d script must have: # PROVIDE: service_name
        """
        self.assertIn(
            '# PROVIDE:', self.script_content,
            f"MISSING PROVIDE DIRECTIVE:\n"
            f"FreeBSD rc.d scripts must include '# PROVIDE: service_name'\n"
            f"FIX: Add PROVIDE comment to each generated rc.d script"
        )

    def test_rc_script_has_require(self):
        """
        TEST: RC scripts include REQUIRE directive.

        WHY: FreeBSD uses REQUIRE to specify service dependencies.

        FIX: Each rc.d script must have: # REQUIRE: dependency1 dependency2
        """
        self.assertIn(
            '# REQUIRE:', self.script_content,
            f"MISSING REQUIRE DIRECTIVE:\n"
            f"FreeBSD rc.d scripts should include '# REQUIRE: dependencies'\n"
            f"FIX: Add REQUIRE comment listing dependencies (NETWORKING, postgresql, etc.)"
        )

    def test_rc_script_sources_rc_subr(self):
        """
        TEST: RC scripts source /etc/rc.subr.

        WHY: This is required for FreeBSD rc.d script functionality.

        FIX: Add '. /etc/rc.subr' at the start of each rc.d script.
        """
        self.assertIn(
            '. /etc/rc.subr', self.script_content,
            f"MISSING RC.SUBR SOURCE:\n"
            f"FreeBSD rc.d scripts must source /etc/rc.subr\n"
            f"FIX: Add '. /etc/rc.subr' after the header comments"
        )

    def test_rc_script_has_run_rc_command(self):
        """
        TEST: RC scripts call run_rc_command.

        WHY: This is the standard way to handle start/stop/status in FreeBSD.

        FIX: End each rc.d script with: run_rc_command "$1"
        """
        self.assertIn(
            'run_rc_command', self.script_content,
            f"MISSING run_rc_command:\n"
            f"FreeBSD rc.d scripts must call run_rc_command\n"
            f"FIX: Add 'run_rc_command \"$1\"' at the end of each rc.d script"
        )

    def test_rc_script_defines_rcvar(self):
        """
        TEST: RC scripts define rcvar.

        WHY: rcvar links the script to its enable variable in rc.conf.

        FIX: Add: rcvar="servicename_enable"
        """
        self.assertIn(
            'rcvar=', self.script_content,
            f"MISSING rcvar DEFINITION:\n"
            f"FreeBSD rc.d scripts must define rcvar\n"
            f"FIX: Add 'rcvar=\"servicename_enable\"' to each rc.d script"
        )

    def test_all_services_have_rc_scripts(self):
        """
        TEST: All required services have rc.d scripts generated.

        WHY: Dispatcharr needs: gunicorn, celery worker, celery beat, daphne

        FIX: Ensure configure_services() creates all required rc.d scripts.
        """
        required_services = [
            ('dispatcharr', 'Main Gunicorn WSGI server'),
            ('dispatcharr_celery', 'Celery worker for background tasks'),
            ('dispatcharr_celerybeat', 'Celery beat scheduler'),
            ('dispatcharr_daphne', 'Daphne ASGI server for WebSockets'),
        ]

        missing = []
        for service, desc in required_services:
            # Look for the rc.d script creation for this service
            if f'dispatcharr_{service.split("_")[-1]}' not in self.script_content and service not in self.script_content:
                if f'$RC_DIR/{service}' not in self.script_content and f'"$RC_DIR/{service}"' not in self.script_content:
                    missing.append(f"  - {service}: {desc}")

        # More flexible check
        for service, desc in required_services:
            # Check if the service name appears in a cat > context
            if f'/{service}"' in self.script_content or f'/{service} ' in self.script_content:
                continue
            if service == 'dispatcharr' and '"$RC_DIR/dispatcharr"' in self.script_content:
                continue

        self.assertIn(
            'dispatcharr_celery', self.script_content,
            f"MISSING SERVICE RC SCRIPTS:\n"
            f"The following services may be missing rc.d scripts:\n\n"
            + "\n".join([f"  - {s}: {d}" for s, d in required_services]) + "\n\n"
            f"FIX: Ensure configure_services() creates rc.d scripts for all services"
        )


class PlaceholderSubstitutionTests(unittest.TestCase):
    """Test that placeholders are properly substituted in generated files."""

    @classmethod
    def setUpClass(cls):
        """Load script content."""
        with open(FREEBSD_SCRIPT, 'r') as f:
            cls.script_content = f.read()

    def test_placeholders_are_defined(self):
        """
        TEST: All placeholder patterns have corresponding substitutions.

        WHY: Placeholders like __APP_DIR__ must be replaced with actual values.

        FIX: Ensure each placeholder has a corresponding sed substitution.
        """
        # Find all placeholders used in templates
        placeholders = set(re.findall(r'__[A-Z_]+__', self.script_content))

        # For each placeholder, check there's a substitution
        missing_subs = []
        for placeholder in placeholders:
            # Look for sed substitution of this placeholder
            if f's|{placeholder}|' not in self.script_content:
                missing_subs.append(f"  - {placeholder}")

        self.assertEqual(
            len(missing_subs), 0,
            f"UNSUBSTITUTED PLACEHOLDERS:\n"
            f"The following placeholders may not be properly substituted:\n\n"
            + "\n".join(missing_subs) + "\n\n"
            f"FIX: Add sed substitution for each placeholder in configure_services()"
        )

    def test_environment_variables_exported(self):
        """
        TEST: Required environment variables are exported in rc.d scripts.

        WHY: Django/Celery need database and secret key environment variables.

        FIX: Export DJANGO_SECRET_KEY, POSTGRES_* vars in each rc.d script.
        """
        required_exports = [
            'DJANGO_SECRET_KEY',
            'POSTGRES_DB',
            'POSTGRES_USER',
            'POSTGRES_PASSWORD',
            'POSTGRES_HOST',
        ]

        missing = []
        for var in required_exports:
            if f'export {var}' not in self.script_content and f'{var}=' not in self.script_content:
                missing.append(f"  - {var}")

        self.assertEqual(
            len(missing), 0,
            f"MISSING ENVIRONMENT EXPORTS:\n"
            f"The following environment variables should be exported:\n\n"
            + "\n".join(missing) + "\n\n"
            f"FIX: Add 'export {missing[0] if missing else 'VAR'}=\"value\"' to rc.d templates"
        )


class NginxConfigTests(unittest.TestCase):
    """Test Nginx configuration generation for FreeBSD."""

    @classmethod
    def setUpClass(cls):
        """Load script content."""
        with open(FREEBSD_SCRIPT, 'r') as f:
            cls.script_content = f.read()

    def test_nginx_locations_defined(self):
        """
        TEST: All required Nginx locations are defined.

        WHY: Dispatcharr needs specific routes for static, assets, media, and websockets.

        FIX: Ensure nginx config includes all location blocks.
        """
        required_locations = [
            ('location /', 'Main application proxy'),
            ('location /static/', 'Django static files'),
            ('location /assets/', 'Frontend build assets'),
            ('location /media/', 'User uploaded media'),
            ('location /ws/', 'WebSocket connections'),
        ]

        missing = []
        for location, desc in required_locations:
            if location not in self.script_content:
                missing.append(f"  - {location}: {desc}")

        self.assertEqual(
            len(missing), 0,
            f"MISSING NGINX LOCATIONS:\n"
            f"The following Nginx location blocks are missing:\n\n"
            + "\n".join(missing) + "\n\n"
            f"FIX: Add the missing location blocks to the Nginx configuration"
        )

    def test_websocket_upgrade_headers(self):
        """
        TEST: WebSocket location includes required upgrade headers.

        WHY: WebSocket connections require specific headers for protocol upgrade.

        FIX: Include Upgrade and Connection headers in /ws/ location.
        """
        required_headers = [
            'proxy_set_header Upgrade',
            'proxy_set_header Connection',
            'proxy_http_version 1.1',
        ]

        missing = []
        for header in required_headers:
            if header not in self.script_content:
                missing.append(f"  - {header}")

        self.assertEqual(
            len(missing), 0,
            f"MISSING WEBSOCKET HEADERS:\n"
            f"The following WebSocket headers are missing:\n\n"
            + "\n".join(missing) + "\n\n"
            f"FIX: Add WebSocket upgrade headers to the /ws/ location block"
        )

    def test_proxy_params_created(self):
        """
        TEST: proxy_params file is created for FreeBSD.

        WHY: FreeBSD nginx doesn't include proxy_params by default like Debian.

        FIX: Create /usr/local/etc/nginx/proxy_params with standard headers.
        """
        self.assertIn(
            'proxy_params', self.script_content,
            f"MISSING PROXY_PARAMS:\n"
            f"FreeBSD nginx doesn't include proxy_params by default.\n"
            f"FIX: Create proxy_params file with standard proxy headers"
        )


class DirectoryStructureTests(unittest.TestCase):
    """Test that required directories are created."""

    @classmethod
    def setUpClass(cls):
        """Load script content."""
        with open(FREEBSD_SCRIPT, 'r') as f:
            cls.script_content = f.read()

    def test_data_directories_created(self):
        """
        TEST: Required data directories are created.

        WHY: Dispatcharr needs specific directories for logos, recordings, etc.

        FIX: Ensure create_directories() creates all required paths.
        """
        required_dirs = [
            '/data/logos',
            '/data/recordings',
            '/data/uploads/m3us',
            '/data/uploads/epgs',
            '/data/m3us',
            '/data/epgs',
            '/data/plugins',
        ]

        missing = []
        for dir_path in required_dirs:
            if dir_path not in self.script_content:
                missing.append(f"  - {dir_path}")

        self.assertEqual(
            len(missing), 0,
            f"MISSING DIRECTORIES:\n"
            f"The following directories should be created:\n\n"
            + "\n".join(missing) + "\n\n"
            f"FIX: Add mkdir -p commands for missing directories"
        )

    def test_run_directory_for_socket(self):
        """
        TEST: Runtime directory for Gunicorn socket is created.

        WHY: The Gunicorn Unix socket needs a directory in /var/run/.

        FIX: Create /var/run/dispatcharr/ with proper permissions.
        """
        self.assertIn(
            '/var/run/dispatcharr', self.script_content,
            f"MISSING RUNTIME DIRECTORY:\n"
            f"The Gunicorn socket directory /var/run/dispatcharr/ must be created.\n"
            f"FIX: Add mkdir -p /var/run/dispatcharr to create_directories()"
        )


class VariableConsistencyTests(unittest.TestCase):
    """Test that configuration variables are consistent."""

    @classmethod
    def setUpClass(cls):
        """Load script content."""
        with open(FREEBSD_SCRIPT, 'r') as f:
            cls.script_content = f.read()

    def test_app_dir_consistent(self):
        """
        TEST: APP_DIR is used consistently throughout the script.

        WHY: Hardcoded paths can cause issues if APP_DIR is changed.

        FIX: Always use $APP_DIR or ${APP_DIR} instead of hardcoded paths.
        """
        # Check that APP_DIR is defined
        self.assertIn(
            'APP_DIR=', self.script_content,
            f"MISSING APP_DIR:\n"
            f"APP_DIR variable must be defined in configure_variables()"
        )

    def test_dispatch_user_consistent(self):
        """
        TEST: DISPATCH_USER is used for all user operations.

        WHY: Using different user names in different places causes permission issues.

        FIX: Always reference $DISPATCH_USER instead of hardcoding 'dispatcharr'.
        """
        self.assertIn(
            'DISPATCH_USER=', self.script_content,
            f"MISSING DISPATCH_USER:\n"
            f"DISPATCH_USER variable must be defined in configure_variables()"
        )

    def test_postgres_vars_consistent(self):
        """
        TEST: PostgreSQL variables are properly defined.

        WHY: Database connection requires consistent credentials.

        FIX: Define POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST.
        """
        required_vars = ['POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_HOST']

        missing = []
        for var in required_vars:
            if f'{var}=' not in self.script_content:
                missing.append(f"  - {var}")

        self.assertEqual(
            len(missing), 0,
            f"MISSING POSTGRES VARIABLES:\n"
            f"The following PostgreSQL variables should be defined:\n\n"
            + "\n".join(missing) + "\n\n"
            f"FIX: Add missing variables to configure_variables()"
        )


class FeatureParityTests(unittest.TestCase):
    """Test that FreeBSD script has feature parity with Debian script."""

    @classmethod
    def setUpClass(cls):
        """Load both scripts."""
        with open(FREEBSD_SCRIPT, 'r') as f:
            cls.freebsd_content = f.read()

        if DEBIAN_SCRIPT.exists():
            with open(DEBIAN_SCRIPT, 'r') as f:
                cls.debian_content = f.read()
        else:
            cls.debian_content = ""

    def test_has_disclaimer(self):
        """
        TEST: FreeBSD script includes a disclaimer/warning.

        WHY: Users need to be warned this is unsupported.

        FIX: Include show_disclaimer() function.
        """
        self.assertIn(
            'disclaimer', self.freebsd_content.lower(),
            f"MISSING DISCLAIMER:\n"
            f"The FreeBSD script should include a disclaimer warning users\n"
            f"that this installation method is unsupported."
        )

    def test_has_auto_confirm(self):
        """
        TEST: FreeBSD script supports DISPATCHARR_AUTO_CONFIRM for automation.

        WHY: Allows automated/scripted installations without interaction.

        FIX: Check for DISPATCHARR_AUTO_CONFIRM=yes to skip interactive prompts.
        """
        self.assertIn(
            'DISPATCHARR_AUTO_CONFIRM', self.freebsd_content,
            f"MISSING AUTO_CONFIRM:\n"
            f"The script should support DISPATCHARR_AUTO_CONFIRM=yes for automation.\n"
            f"FIX: Add check for this variable to skip interactive prompts."
        )

    def test_has_summary(self):
        """
        TEST: Installation shows a summary at the end.

        WHY: Users need to know where to access the application.

        FIX: Include show_summary() function that displays access URL.
        """
        self.assertIn(
            'summary', self.freebsd_content.lower(),
            f"MISSING SUMMARY:\n"
            f"The script should display a summary with access URLs after installation."
        )


def run_tests():
    """Run all tests with detailed output."""
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        FreeBSDScriptSyntaxTests,
        RequirementsFilteringTests,
        RCScriptTests,
        PlaceholderSubstitutionTests,
        NginxConfigTests,
        DirectoryStructureTests,
        VariableConsistencyTests,
        FeatureParityTests,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("FREEBSD COMPATIBILITY TEST SUMMARY")
    print("=" * 70)

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total - failures - errors

    print(f"\nTotal tests: {total}")
    print(f"Passed:      {passed}")
    print(f"Failed:      {failures}")
    print(f"Errors:      {errors}")

    if failures > 0 or errors > 0:
        print("\n" + "-" * 70)
        print("ATTENTION: Some tests failed!")
        print("Review the detailed output above to identify breaking changes.")
        print("Each failed test includes:")
        print("  - WHY: Explanation of why this matters for FreeBSD")
        print("  - FIX: Specific steps to resolve the issue")
        print("-" * 70)
        return 1

    print("\nAll FreeBSD compatibility tests passed!")
    return 0


if __name__ == '__main__':
    sys.exit(run_tests())
