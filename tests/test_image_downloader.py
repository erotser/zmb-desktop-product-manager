import socket
import urllib.error
import urllib.request

import pytest

from app.image_downloader import ImageDownloadError, download_image, is_downloadable_url

# These hit a real, whitelisted host to verify actual HTTP behavior end to
# end, not just mocked logic -- deliberately using small, stable public
# assets rather than mocking urllib, since the thing most likely to break
# here is a real-world HTTP edge case (status codes, content-type headers).
REAL_IMAGE_URL = "https://raw.githubusercontent.com/github/explore/main/topics/python/python.png"
REAL_404_URL = "https://raw.githubusercontent.com/this/does/not/exist-zpm-test.jpg"
REAL_NON_IMAGE_URL = "https://raw.githubusercontent.com/github/explore/main/README.md"


def _network_available() -> bool:
    try:
        urllib.request.urlopen("https://raw.githubusercontent.com", timeout=5)
        return True
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _network_available(),
    reason="No network access to raw.githubusercontent.com -- skipping live download tests.",
)


def test_is_downloadable_url():
    assert is_downloadable_url("https://example.com/a.jpg") is True
    assert is_downloadable_url("http://example.com/a.jpg") is True
    assert is_downloadable_url("a-bare-filename.jpg") is False
    assert is_downloadable_url("") is False
    assert is_downloadable_url(None) is False


def test_download_real_image(tmp_path):
    path = download_image(REAL_IMAGE_URL, tmp_path)
    from pathlib import Path
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0
    assert path.endswith(".png")


def test_download_is_cached_on_second_call(tmp_path):
    path1 = download_image(REAL_IMAGE_URL, tmp_path)
    path2 = download_image(REAL_IMAGE_URL, tmp_path)
    assert path1 == path2
    # Only one file for this URL should exist in the cache dir.
    from pathlib import Path
    matches = list(Path(tmp_path).glob("*.png"))
    assert len(matches) == 1


def test_download_404_raises_clear_error(tmp_path):
    with pytest.raises(ImageDownloadError, match="404"):
        download_image(REAL_404_URL, tmp_path)


def test_download_non_image_response_raises(tmp_path):
    with pytest.raises(ImageDownloadError, match="didn't return an image"):
        download_image(REAL_NON_IMAGE_URL, tmp_path)


def test_download_bare_filename_raises_without_network_call(tmp_path):
    with pytest.raises(ImageDownloadError, match="Not a downloadable URL"):
        download_image("just-a-filename.jpg", tmp_path)
