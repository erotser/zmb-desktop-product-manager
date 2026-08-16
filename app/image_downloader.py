"""
Downloads a product/variation image from its URL (as referenced in an
imported CSV) so it can be previewed and edited locally, instead of just
showing the URL as text.

Deliberately stdlib-only (urllib), no extra dependency, since this is a
simple one-shot fetch -- not worth adding `requests` for.
"""

from __future__ import annotations

import hashlib
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


class ImageDownloadError(Exception):
    pass


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def is_downloadable_url(value: Optional[str]) -> bool:
    return bool(value) and (value.startswith("http://") or value.startswith("https://"))


def download_image(url: str, cache_dir: str | Path, timeout: int = 15) -> str:
    """
    Downloads `url` into `cache_dir`, reusing an existing cached copy if
    this exact URL was already downloaded before. Returns the local file
    path. Raises ImageDownloadError with a human-readable message on any
    failure (network error, non-image response, etc).
    """
    if not is_downloadable_url(url):
        raise ImageDownloadError(f"Not a downloadable URL: {url}")

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = _cache_key(url)
    existing = list(cache_dir.glob(f"{key}.*"))
    if existing:
        return str(existing[0])

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ZombeeProductManager/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
    except urllib.error.HTTPError as e:
        raise ImageDownloadError(f"Server returned an error ({e.code}) for {url}") from e
    except urllib.error.URLError as e:
        raise ImageDownloadError(f"Could not reach {url}: {e.reason}") from e
    except TimeoutError as e:
        raise ImageDownloadError(f"Timed out downloading {url}") from e

    if not content_type.startswith("image/"):
        raise ImageDownloadError(f"That URL didn't return an image (got \"{content_type}\"): {url}")

    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or Path(url).suffix or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"

    dest = cache_dir / f"{key}{ext}"
    dest.write_bytes(data)
    return str(dest)
