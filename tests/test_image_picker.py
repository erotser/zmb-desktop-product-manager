import pytest

from app.image_downloader import ImageDownloadError
from app.ui import image_picker as image_picker_module
from app.ui.image_picker import ImagePickerWidget, set_download_cache_dir


@pytest.fixture
def widget(qtbot, tmp_path):
    set_download_cache_dir(str(tmp_path / "cache"))
    w = ImagePickerWidget()
    qtbot.addWidget(w)
    return w


def test_download_button_hidden_when_no_existing_ref(widget):
    widget.set_value(None, "", None)
    assert widget.download_button.isHidden()


def test_download_button_hidden_for_bare_filename_ref(widget):
    """A bare filename (already on the site, but not a fetchable URL) can't
    be downloaded -- the button shouldn't offer to try."""
    widget.set_value(None, "", "tee-red.jpg")
    assert widget.download_button.isHidden()


def test_download_button_shown_for_url_ref(widget):
    widget.set_value(None, "", "https://example.com/tee.jpg")
    assert not widget.download_button.isHidden()


def test_download_button_hidden_once_a_local_file_is_set(widget, tmp_path):
    fake_image = tmp_path / "local.jpg"
    fake_image.write_bytes(b"fake")
    widget.set_value(str(fake_image), "", "https://example.com/tee.jpg")
    assert widget.download_button.isHidden()


def test_successful_download_sets_local_path(widget, tmp_path, monkeypatch):
    downloaded_file = tmp_path / "downloaded.jpg"
    downloaded_file.write_bytes(b"fake image data")

    monkeypatch.setattr(image_picker_module, "download_image", lambda url, cache_dir: str(downloaded_file))

    widget.set_value(None, "", "https://example.com/tee.jpg")
    widget._on_download_clicked()

    assert widget.get_local_path() == str(downloaded_file)
    # The original reference is kept too (harmless -- local path takes
    # priority on export), so nothing is lost if the user just wanted to look.
    assert widget.get_existing_ref() == "https://example.com/tee.jpg"


def test_failed_download_shows_warning_and_keeps_state(widget, monkeypatch):
    def raise_error(url, cache_dir):
        raise ImageDownloadError("Could not reach https://example.com/tee.jpg: timed out")

    monkeypatch.setattr(image_picker_module, "download_image", raise_error)

    from PySide6.QtWidgets import QMessageBox
    warnings_shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: warnings_shown.append(a) or QMessageBox.Ok))

    widget.set_value(None, "", "https://example.com/tee.jpg")
    widget._on_download_clicked()

    assert widget.get_local_path() is None  # unchanged, download failed
    assert len(warnings_shown) == 1


def test_changed_signal_emitted_on_successful_download(widget, tmp_path, monkeypatch, qtbot):
    downloaded_file = tmp_path / "downloaded.jpg"
    downloaded_file.write_bytes(b"fake")
    monkeypatch.setattr(image_picker_module, "download_image", lambda url, cache_dir: str(downloaded_file))

    widget.set_value(None, "", "https://example.com/tee.jpg")
    with qtbot.waitSignal(widget.changed, timeout=1000):
        widget._on_download_clicked()
