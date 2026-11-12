"""Host-owned filesystem operations exposed to plugins."""
import os
import shutil

from core.watch_directories import EPG_WATCH_DIR, LOGO_WATCH_DIR, M3U_WATCH_DIR


def make_filesystem_context(data_dir, authorize, directories=None):
    roots = dict(directories or {"logos": LOGO_WATCH_DIR, "m3u": M3U_WATCH_DIR, "epg": EPG_WATCH_DIR})
    data_root = os.path.abspath(data_dir) if data_dir else None
    roots = {name: os.path.abspath(path) for name, path in roots.items()}

    def ensure_directory(name):
        if name not in roots:
            raise ValueError(f"Unknown Dispatcharr directory: {name}")
        authorize(True)
        if os.path.islink(roots[name]):
            raise ValueError("Shared directory must not be a symlink")
        os.makedirs(roots[name], exist_ok=True)
        return roots[name]

    def remove_directory(path):
        path = os.fspath(path)
        if not os.path.isabs(path):
            raise ValueError("Directory path must be absolute")
        path = os.path.abspath(path)
        if path in roots.values() or path == data_root:
            raise ValueError("Cannot remove a directory root")
        candidates = [(root, True) for root in roots.values()] + ([(data_root, False)] if data_root else [])
        for root, shared in candidates:
            if os.path.commonpath((root, path)) == root and path != root:
                break
        else:
            raise ValueError("Directory must be inside plugin data or a shared directory")
        if os.path.islink(root):
            raise ValueError("Directory root must not be a symlink")
        if not shared and os.path.islink(os.path.dirname(root)):
            raise ValueError("Plugin data parent must not be a symlink")
        resolved_root = os.path.realpath(root)
        if not shared and any(
            os.path.commonpath((os.path.realpath(shared_root), resolved_root)) == os.path.realpath(shared_root)
            for shared_root in roots.values()
        ):
            shared = True
        authorize(shared)
        # Traverse from the filesystem root using directory descriptors and
        # O_NOFOLLOW. This avoids symlink substitution during traversal.
        if not hasattr(os, "O_NOFOLLOW") or not shutil.rmtree.avoids_symlink_attacks:
            raise NotImplementedError("Safe directory removal is unavailable")
        path = os.path.join(resolved_root, os.path.relpath(path, root))
        parts = path.strip(os.sep).split(os.sep)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(os.sep, flags)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            shutil.rmtree(parts[-1], dir_fd=fd)
        finally:
            os.close(fd)

    return {"directories": roots, "ensure_directory": ensure_directory, "remove_directory": remove_directory}
