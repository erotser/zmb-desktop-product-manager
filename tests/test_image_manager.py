from pathlib import Path

import pytest
from PIL import Image

from app.image_manager import (
    CompressionSettings, ImageExportError, ImageExporter,
    gallery_image_filename, main_image_filename, sanitize_filename_component,
    variation_image_filename,
)
from app.models import GalleryImage, Product, Variation


def make_test_image(path: Path, size=(3000, 2000), color=(200, 50, 50), alpha=False):
    mode = "RGBA" if alpha else "RGB"
    img = Image.new(mode, size, color + (128,) if alpha else color)
    img.save(path)
    return path


def test_sanitize_filename_component_strips_unsafe_chars():
    assert sanitize_filename_component("TSHIRT-001/RED?") == "TSHIRT-001-RED-"
    assert sanitize_filename_component("  ") == "image"


def test_main_image_filename_uses_sku_and_extension():
    p = Product(sku="TSHIRT-001", product_type="simple", name="Tee", price="1")
    settings = CompressionSettings(output_format="webp")
    assert main_image_filename(p, settings) == "TSHIRT-001.webp"

    settings_jpeg = CompressionSettings(output_format="jpeg")
    assert main_image_filename(p, settings_jpeg) == "TSHIRT-001.jpg"


def test_gallery_and_variation_filenames():
    p = Product(sku="TSHIRT-001", product_type="variable", name="Tee")
    settings = CompressionSettings(output_format="webp")
    assert gallery_image_filename(p, 0, settings) == "TSHIRT-001-gallery-1.webp"
    assert gallery_image_filename(p, 1, settings) == "TSHIRT-001-gallery-2.webp"
    assert variation_image_filename("TSHIRT-001-RED-S", settings) == "TSHIRT-001-RED-S.webp"


def test_compression_reduces_file_size_and_resizes(tmp_path):
    source = make_test_image(tmp_path / "source.png", size=(4000, 3000))
    original_size = source.stat().st_size

    settings = CompressionSettings(output_format="webp", quality=80, max_dimension=1000)
    exporter = ImageExporter(tmp_path / "out", tmp_path / "cache", settings)

    product = Product(sku="TSHIRT-001", product_type="simple", name="Tee", price="1", image_path=str(source))
    result = exporter.export_images([product], confirm_clear=lambda: True)

    out_file = tmp_path / "out" / "TSHIRT-001.webp"
    assert out_file.exists()
    assert out_file.stat().st_size < original_size

    with Image.open(out_file) as img:
        assert max(img.size) <= 1000

    assert result[str(source)] == "TSHIRT-001.webp"


def test_jpeg_flattens_transparency_onto_white(tmp_path):
    source = make_test_image(tmp_path / "source.png", size=(200, 200), alpha=True)
    settings = CompressionSettings(output_format="jpeg", quality=85, max_dimension=None)
    exporter = ImageExporter(tmp_path / "out", tmp_path / "cache", settings)

    product = Product(sku="MUG-001", product_type="simple", name="Mug", price="1", image_path=str(source))
    exporter.export_images([product], confirm_clear=lambda: True)

    out_file = tmp_path / "out" / "MUG-001.jpg"
    assert out_file.exists()
    with Image.open(out_file) as img:
        assert img.mode == "RGB"  # no alpha channel survives into JPEG


def test_confirm_clear_false_aborts_without_touching_folder(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    sentinel = out_dir / "should_survive.txt"
    sentinel.write_text("do not delete me")

    source = make_test_image(tmp_path / "source.png")
    settings = CompressionSettings()
    exporter = ImageExporter(out_dir, tmp_path / "cache", settings)
    product = Product(sku="X", product_type="simple", name="X", price="1", image_path=str(source))

    with pytest.raises(ImageExportError):
        exporter.export_images([product], confirm_clear=lambda: False)

    assert sentinel.exists()


def test_export_clears_previous_contents(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stale_file = out_dir / "OLD-PRODUCT.webp"
    stale_file.write_text("stale image from a previous export")

    source = make_test_image(tmp_path / "source.png")
    settings = CompressionSettings()
    exporter = ImageExporter(out_dir, tmp_path / "cache", settings)
    product = Product(sku="NEW-PRODUCT", product_type="simple", name="X", price="1", image_path=str(source))

    exporter.export_images([product], confirm_clear=lambda: True)

    assert not stale_file.exists()
    assert (out_dir / "NEW-PRODUCT.webp").exists()


def test_export_only_includes_given_products_not_whole_library(tmp_path):
    source_a = make_test_image(tmp_path / "a.png")
    source_b = make_test_image(tmp_path / "b.png")
    settings = CompressionSettings()
    exporter = ImageExporter(tmp_path / "out", tmp_path / "cache", settings)

    product_a = Product(sku="A", product_type="simple", name="A", price="1", image_path=str(source_a))
    product_b = Product(sku="B", product_type="simple", name="B", price="1", image_path=str(source_b))

    # Only export product_a -- product_b's image must not appear.
    exporter.export_images([product_a], confirm_clear=lambda: True)

    assert (tmp_path / "out" / "A.webp").exists()
    assert not (tmp_path / "out" / "B.webp").exists()


def test_variation_and_gallery_images_all_exported(tmp_path):
    main_src = make_test_image(tmp_path / "main.png")
    gallery_src = make_test_image(tmp_path / "gallery.png")
    var_src = make_test_image(tmp_path / "var.png")

    settings = CompressionSettings()
    exporter = ImageExporter(tmp_path / "out", tmp_path / "cache", settings)

    product = Product(
        sku="TSHIRT-001", product_type="variable", name="Tee",
        image_path=str(main_src),
        gallery=[GalleryImage(path=str(gallery_src), alt="gallery shot")],
        variations=[Variation(sku="TSHIRT-001-RED-S", price="10", image_path=str(var_src))],
    )

    result = exporter.export_images([product], confirm_clear=lambda: True)

    assert (tmp_path / "out" / "TSHIRT-001.webp").exists()
    assert (tmp_path / "out" / "TSHIRT-001-gallery-1.webp").exists()
    assert (tmp_path / "out" / "TSHIRT-001-RED-S.webp").exists()
    assert len(result) == 3


def test_missing_source_file_raises_clear_error(tmp_path):
    settings = CompressionSettings()
    exporter = ImageExporter(tmp_path / "out", tmp_path / "cache", settings)
    product = Product(sku="X", product_type="simple", name="X", price="1", image_path="/nonexistent/file.png")

    with pytest.raises(ImageExportError):
        exporter.export_images([product], confirm_clear=lambda: True)


def test_reexport_without_changes_uses_cache_not_recompress(tmp_path):
    source = make_test_image(tmp_path / "source.png")
    settings = CompressionSettings()
    exporter = ImageExporter(tmp_path / "out", tmp_path / "cache", settings)
    product = Product(sku="X", product_type="simple", name="X", price="1", image_path=str(source))

    exporter.export_images([product], confirm_clear=lambda: True)
    cache_files_after_first = list((tmp_path / "cache").iterdir())

    exporter.export_images([product], confirm_clear=lambda: True)
    cache_files_after_second = list((tmp_path / "cache").iterdir())

    # Same cache entry reused, not duplicated.
    assert len(cache_files_after_first) == len(cache_files_after_second) == 1
