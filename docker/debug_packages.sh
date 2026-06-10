#!/bin/bash
# Debug script to check installed Python packages in the container

echo "=== Python Version ==="
/dispatcharrpy/bin/python --version

echo ""
echo "=== Python Path ==="
/dispatcharrpy/bin/python -c "import sys; print('\n'.join(sys.path))"

echo ""
echo "=== Checking Critical Packages ==="

packages=(
    "django"
    "django_db_geventpool"
    "drf_spectacular"
    "gevent"
    "psycopg"
    "celery"
    "channels"
)

for package in "${packages[@]}"; do
    if /dispatcharrpy/bin/python -c "import $package" 2>/dev/null; then
        version=$(/dispatcharrpy/bin/python -c "import $package; print(getattr($package, '__version__', 'unknown'))" 2>/dev/null)
        echo "✓ $package (version: $version)"
    else
        echo "✗ $package - NOT FOUND"
    fi
done

echo ""
echo "=== All Installed Packages ==="
/dispatcharrpy/bin/python -c "import pkg_resources; print('\n'.join([f'{d.project_name}=={d.version}' for d in pkg_resources.working_set]))" 2>/dev/null || \
uv pip list --python /dispatcharrpy/bin/python 2>/dev/null || \
echo "Could not list packages"

echo ""
echo "=== Virtual Environment Location ==="
ls -la /dispatcharrpy/lib/python3.13/site-packages/ | grep -E "(django|gevent|psycopg|drf)" || echo "No matching packages found in site-packages"
