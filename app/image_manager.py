"""
Image handling for Zombee Product Manager Desktop.

Design decisions (per project discussion):
- Original files the user picks are never modified or moved. They stay
  wherever they are on disk; only their path is stored on the product.
- Compression/resizing happens at EXPORT time, not when an image is first
  added, so changing compression settings later just means re-exporting.
- Export target is a single FLAT folder (no per-product subfolders) --
  every file is renamed using the product/variation SKU, which is already
  guaranteed unique, so flat storage can't collide.
- The folder is cleared and repopulated on every export with ONLY the
  images for the products in that export (not the whole local library).
  Clearing requires the caller to confirm first (see `export_images`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageOps

from .models import Product


SUPPORTED_SOURCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif"}


@dataclass
class CompressionSettings:
    output_format: str = "webp"     # "webp" or "jpeg"
    quality: int = 82               # 1-100
    max_dimension: int = 2000       # longest side, in pixels; None/0 disables resizing
    strip_metadata: bool = True     # EXIF etc.

    def extension(self) -> str:
        return ".webp" if self.output_format == "webp" else ".jpg"


class ImageExportError(Exception):
    pass


def sanitize_filename_component(value: str) -> str:
    """Make a SKU safe to use as a filename. SKUs are already meant to be
    simple identifiers, but this guards against stray slashes/spaces/etc."""
    keep = "-_."
    cleaned = "".join(c if c.isalnum() or c in keep else "-" for c in value.strip())
    return cleaned or "image"


def main_image_filename(product: Product, settings: CompressionSettings) -> str:
    return f"{sanitize_filename_component(product.sku)}{settings.extension()}"


def gallery_image_filename(product: Product, index: int, settings: CompressionSettings) -> str:
    # 1-indexed for human friendliness when someone looks at the folder.
    return f"{sanitize_filename_component(product.sku)}-gallery-{index + 1}{settings.extension()}"


def variation_image_filename(variation_sku: str, settings: CompressionSettings) -> str:
    return f"{sanitize_filename_component(variation_sku)}{settings.extension()}"


def _compress_image(source_path: str, dest_path: Path, settings: CompressionSettings) -> None:
    with Image.open(source_path) as img:
        # Respect the camera's orientation tag before we strip metadata,
        # otherwise sideways/upside-down photos would get baked in wrong.
        img = ImageOps.exif_transpose(img)

        if settings.max_dimension and max(img.size) > settings.max_dimension:
            img.thumbnail((settings.max_dimension, settings.max_dimension), Image.LANCZOS)

        save_kwargs = {}
        if settings.output_format == "webp":
            img_to_save = img.convert("RGBA") if img.mode in ("RGBA", "LA") else img.convert("RGB")
            save_kwargs = {"format": "WEBP", "quality": settings.quality, "method": 6}
        else:
            # JPEG has no transparency -- flatten onto white instead of
            # producing a surprise black background.
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                background = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                img_to_save = background
            else:
                img_to_save = img.convert("RGB")
            save_kwargs = {"format": "JPEG", "quality": settings.quality, "optimize": True}

        if settings.strip_metadata:
            # Saving without passing through the original `exif`/`info` dict
            # already drops metadata for these formats; nothing further needed.
            pass

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        img_to_save.save(dest_path, **save_kwargs)


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ImageExporter:
    """
    Handles the "clear and repopulate a flat folder" export flow, with a
    small on-disk cache (keyed by source file hash + compression settings)
    so re-exporting without changing anything doesn't recompress everything
    from scratch every time.
    """

    def __init__(self, output_dir: str | Path, cache_dir: str | Path, settings: CompressionSettings):
        self.output_dir = Path(output_dir)
        self.cache_dir = Path(cache_dir)
        self.settings = settings
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cached_or_compress(self, source_path: str) -> Path:
        key = f"{_file_hash(source_path)}-{self.settings.output_format}-{self.settings.quality}-{self.settings.max_dimension}"
        cached_path = self.cache_dir / f"{key}{self.settings.extension()}"
        if not cached_path.exists():
            _compress_image(source_path, cached_path, self.settings)
        return cached_path

    def export_images(
        self,
        products: list[Product],
        confirm_clear: Callable[[], bool],
    ) -> dict[str, str]:
        """
        Clears self.output_dir (after calling confirm_clear() -- if it
        returns False, raises ImageExportError and touches nothing) and
        repopulates it with compressed, renamed copies of every image
        belonging to `products`.

        Returns a mapping of {original_source_path: final_filename} for
        every image that was exported, so the CSV writer can look up the
        right filename for each product/variation/gallery image.
        """
        if not confirm_clear():
            raise ImageExportError("Export cancelled: user did not confirm clearing the folder.")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        for existing in self.output_dir.iterdir():
            if existing.is_file():
                existing.unlink()

        filename_map: dict[str, str] = {}

        for product in products:
            if product.image_path:
                filename_map[product.image_path] = self._export_one(
                    product.image_path, main_image_filename(product, self.settings)
                )

            for i, gallery_img in enumerate(product.gallery):
                filename_map[gallery_img.path] = self._export_one(
                    gallery_img.path, gallery_image_filename(product, i, self.settings)
                )

            if product.is_variable():
                for variation in product.variations:
                    if variation.image_path:
                        filename_map[variation.image_path] = self._export_one(
                            variation.image_path, variation_image_filename(variation.sku, self.settings)
                        )

        return filename_map

    def _export_one(self, source_path: str, final_filename: str) -> str:
        if not Path(source_path).exists():
            raise ImageExportError(f"Source image not found: {source_path}")
        compressed = self._cached_or_compress(source_path)
        dest = self.output_dir / final_filename
        dest.write_bytes(compressed.read_bytes())
        return final_filename
