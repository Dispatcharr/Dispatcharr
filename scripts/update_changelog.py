#!/usr/bin/env python
"""
Updates the CHANGELOG.md file for a new release.
Renames [Unreleased] section to the new version with current date.
Usage: python update_changelog.py <version>
"""
import re
import sys
from datetime import datetime
from pathlib import Path


def update_changelog(version):
    """Update CHANGELOG.md with new version and date."""
    changelog_file = Path(__file__).parent.parent / "CHANGELOG.md"
    
    if not changelog_file.exists():
        print("CHANGELOG.md not found")
        sys.exit(1)
    
    content = changelog_file.read_text(encoding='utf-8')
    
    # Check if there's an Unreleased section
    if '## [Unreleased]' not in content:
        print("No [Unreleased] section found in CHANGELOG.md")
        sys.exit(1)
    
    # Get current date in YYYY-MM-DD format
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Replace [Unreleased] with new version and date, and add new [Unreleased] section
    # This pattern preserves everything after [Unreleased] until the next version or end
    new_content = re.sub(
        r'## \[Unreleased\]',
        f'## [Unreleased]\n\n## [{version}] - {today}',
        content,
        count=1
    )
    
    if new_content == content:
        print("Failed to update CHANGELOG.md")
        sys.exit(1)
    
    changelog_file.write_text(new_content, encoding='utf-8')
    print(f"CHANGELOG.md updated for version {version} ({today})")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python update_changelog.py <version>")
        print("Example: python update_changelog.py 0.13.0")
        sys.exit(1)
    
    version = sys.argv[1]
    # Remove 'v' prefix if present
    version = version.lstrip('v')
    
    update_changelog(version)
