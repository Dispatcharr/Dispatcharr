#!/usr/bin/env python3
import os
import stat
import time
import errno
import logging
import requests
import subprocess
import json

from fuse import FUSE, Operations, FuseOSError

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

MAPPINGS_DIR = "/mnt/mappings"    # folder with files whose content is the URL to the stream
MOUNT_POINT = "/mnt/streams"      # mount point for the FUSE filesystem

CACHE_TTL = 300              # seconds for cache validity

class StreamFS(Operations):
    def __init__(self, mappings_dir):
        self.mappings_dir = mappings_dir
        self._reload_mappings()
        self.size_cache = {}
        self.metadata_cache = {}

    def _reload_mappings(self):
        try:
            self.files = os.listdir(self.mappings_dir)
        except FileNotFoundError:
            self.files = []

    def _get_url_for_file(self, filename):
        try:
            with open(os.path.join(self.mappings_dir, filename), "r") as f:
                return f.read().strip()
        except Exception as e:
            logging.error(f"Failed to read URL for {filename}: {e}")
            return None

    def _http_head_size(self, url):
        now = time.time()
        if url in self.size_cache:
            ts, size = self.size_cache[url]
            if now - ts < CACHE_TTL:
                return size

        try:
            r = requests.head(url, timeout=5)
            if r.status_code in (200, 206):
                size = int(r.headers.get('Content-Length', '0'))
                self.size_cache[url] = (now, size)
                logging.debug(f"Fetched size {size} for {url}")
                return size
            else:
                logging.warning(f"HEAD request returned status {r.status_code} for {url}")
        except Exception as e:
            logging.error(f"HEAD request failed for {url}: {e}")
        return 0

    def _get_metadata(self, url):
        now = time.time()
        if url in self.metadata_cache:
            ts, metadata_str = self.metadata_cache[url]
            if now - ts < CACHE_TTL:
                return metadata_str

        # Use ffprobe to get video metadata
        # Note: ffprobe expects a URL or a local file path
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_name,width,height",
                "-of", "json", url
            ]
            logging.debug(f"Running ffprobe for {url}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode != 0:
                logging.error(f"ffprobe error for {url}: {proc.stderr.strip()}")
                metadata_str = "ffprobe error: " + proc.stderr.strip()
            else:
                info = json.loads(proc.stdout)
                format_info = info.get("format", {})
                streams = info.get("streams", [])

                duration = format_info.get("duration", "unknown")
                duration = float(duration) if duration != "unknown" else None

                # Gather codecs and resolution from first video stream
                video_stream = None
                for s in streams:
                    if s.get("codec_type") == "video":
                        video_stream = s
                        break

                codec = video_stream.get("codec_name", "unknown") if video_stream else "unknown"
                width = video_stream.get("width", "unknown") if video_stream else "unknown"
                height = video_stream.get("height", "unknown") if video_stream else "unknown"

                metadata_str = (
                    f"Duration: {duration:.2f} sec\n" if duration else "Duration: unknown\n"
                )
                metadata_str += f"Video codec: {codec}\n"
                metadata_str += f"Resolution: {width}x{height}\n"

            self.metadata_cache[url] = (now, metadata_str)
            return metadata_str
        except Exception as e:
            logging.error(f"Failed to run ffprobe for {url}: {e}")
            return "Metadata unavailable\n"

    # -- FUSE operations --

    def readdir(self, path, fh):
        logging.debug(f"readdir called for {path}")
        self._reload_mappings()
        yield '.'
        yield '..'

        for filename in self.files:
            # yield video file
            yield filename

    def getattr(self, path, fh=None):
        logging.debug(f"getattr called for {path}")

        if path == "/" or path == "":
            return dict(st_mode=(stat.S_IFDIR | 0o755), st_nlink=2)

        # Normal video files
        filename = path.lstrip("/")
        if filename not in self.files:
            raise FuseOSError(errno.ENOENT)

        url = self._get_url_for_file(filename)
        if not url:
            raise FuseOSError(errno.ENOENT)

        size = self._http_head_size(url)

        # Get stat of mapping file for ownership and timestamps
        full_path = os.path.join(self.mappings_dir, filename)
        try:
            st = os.lstat(full_path)
            uid = st.st_uid
            gid = st.st_gid
            atime = st.st_atime
            mtime = st.st_mtime
            ctime = st.st_ctime
        except Exception:
            uid = os.getuid()
            gid = os.getgid()
            atime = mtime = ctime = time.time()

        return dict(
            st_mode=(stat.S_IFREG | 0o444),
            st_nlink=1,
            st_size=size,
            st_uid=uid,
            st_gid=gid,
            st_atime=atime,
            st_mtime=mtime,
            st_ctime=ctime,
        )

    def getxattr(self, path, name, position=0):
        logging.debug(f"getxattr called for {path} name={name}")
        # Return ENOTSUP error without exception
        raise FuseOSError(errno.ENOTSUP)

    def open(self, path, flags):
        filename = path.lstrip("/").lstrip(".").rstrip(".info")
        logging.debug(f"Requested to open {filename}")
        logging.debug(f"Current files: {json.dumps(self.files)}")
        if filename not in self.files:
            raise FuseOSError(errno.ENOENT)
        logging.debug(f"open called for file: {filename}")
        return 0

    def read(self, path, size, offset, fh):
        logging.debug(f"read called for path={path}, size={size}, offset={offset}")

        if path.endswith(".info"):
            base_filename = path[1:-5]
            url = self._get_url_for_file(base_filename)
            if not url:
                return b""
            metadata_str = self._get_metadata(url)
            data = metadata_str.encode("utf-8")
            return data[offset:offset + size]

        filename = path.lstrip("/")
        url = self._get_url_for_file(filename)
        if not url:
            return b""

        headers = {"Range": f"bytes={offset}-{offset + size - 1}"}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=15) as r:
                r.raise_for_status()
                data = bytearray()
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) >= size:
                        break
                # Make sure to return exactly requested size
                return bytes(data[:size])
        except Exception as e:
            logging.error(f"Error reading {url} range {offset}-{offset + size - 1}: {e}")
            return b""

if __name__ == "__main__":
    os.makedirs(MAPPINGS_DIR, exist_ok=True)
    os.makedirs(MOUNT_POINT, exist_ok=True)

    logging.info(f"Mounting StreamFS: {MAPPINGS_DIR} -> {MOUNT_POINT}")

    FUSE(StreamFS(MAPPINGS_DIR), MOUNT_POINT, nothreads=True, foreground=True, allow_other=True)
