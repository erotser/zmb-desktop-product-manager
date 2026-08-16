"""
Data model for Zombee Product Manager Desktop.

These are plain dataclasses -- no ORM. The database layer (db.py) reads and
writes them directly. Keeping this layer dumb and dependency-free keeps the
final packaged .exe small and the logic easy to unit test without a GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


PRODUCT_TYPES = ("simple", "variable")


@dataclass
class GalleryImage:
    """One image in a product's gallery."""
    path: Optional[str] = None     # NEW local source file picked in this app, or None
    alt: str = ""
    position: int = 0
    image_ref: Optional[str] = None    # existing URL/filename from an imported CSV (kept if path is never set)


@dataclass
class ProductAttribute:
    """
    An attribute definition on a product.

    For a SIMPLE product, `values` is the literal list of display values
    (e.g. ["Cotton", "Polyester"]) that gets pipe-joined straight into the
    CSV cell -- no variations involved.

    For a VARIABLE product, `values` is the *palette* of possible options
    (e.g. ["Red", "Blue"] for a Color attribute) used to build/validate
    variation rows. The actual value used on any given variation lives on
    that Variation's `attribute_values` dict, not here.
    """
    name: str
    values: list[str] = field(default_factory=list)
    position: int = 0


@dataclass
class Variation:
    """One variation row of a variable product."""
    sku: str
    price: str = ""                 # kept as string; validated/parsed at save/export time
    sale_price: str = ""
    stock_qty: str = ""
    manage_stock: bool = False
    description: str = ""
    image_path: Optional[str] = None   # NEW local source file path picked in this app, or None
    image_alt: str = ""
    image_ref: Optional[str] = None    # existing URL/filename from an imported CSV (kept if image_path is never set)
    attribute_values: dict[str, str] = field(default_factory=dict)  # {"Color": "Red", "Size": "S"}
    id: Optional[int] = None           # set once persisted to the local DB

    def has_image_set(self) -> bool:
        return bool(self.image_path or self.image_ref)


@dataclass
class CustomField:
    name: str
    value: str = ""


@dataclass
class Product:
    """
    A product, simple or variable. This is the unit the GUI edits and the
    CSV importer/exporter operates on.
    """
    sku: str
    product_type: str = "simple"       # "simple" or "variable"
    name: str = ""
    description: str = ""
    short_description: str = ""
    categories: str = ""               # "Clothing > T-Shirts|Sale" -- same syntax as the CSV column
    tags: str = ""                     # "Bestseller|Handmade" -- pipe separated, flat
    image_path: Optional[str] = None   # NEW local source file picked in this app, or None
    image_alt: str = ""
    image_ref: Optional[str] = None    # existing URL/filename from an imported CSV (kept if image_path is never set)
    gallery: list[GalleryImage] = field(default_factory=list)
    attributes: list[ProductAttribute] = field(default_factory=list)
    custom_fields: list[CustomField] = field(default_factory=list)

    # Simple-product-only fields (variable products carry price/stock per variation instead)
    price: str = ""
    sale_price: str = ""
    stock_qty: str = ""
    manage_stock: bool = False

    variations: list[Variation] = field(default_factory=list)  # variable products only

    id: Optional[int] = None           # set once persisted to the local DB

    def is_simple(self) -> bool:
        return self.product_type == "simple"

    def is_variable(self) -> bool:
        return self.product_type == "variable"

    def has_image_set(self) -> bool:
        return bool(self.image_path or self.image_ref)

    def validate(self) -> list[str]:
        """Returns a list of human-readable problems, empty if valid."""
        errors = []
        if not self.sku.strip():
            errors.append("SKU is required.")
        if not self.name.strip():
            errors.append("Product name is required.")
        if self.product_type not in PRODUCT_TYPES:
            errors.append(f'product_type must be one of {PRODUCT_TYPES}.')

        if self.is_simple():
            if not self._is_non_negative_number(self.price):
                errors.append("Price must be a non-negative number.")
            if self.sale_price and not self._is_non_negative_number(self.sale_price):
                errors.append("Sale price must be a non-negative number.")
        else:
            if not self.variations:
                errors.append("A variable product needs at least one variation.")
            seen_skus = set()
            for v in self.variations:
                if not v.sku.strip():
                    errors.append("Every variation needs a SKU.")
                elif v.sku in seen_skus:
                    errors.append(f'Duplicate variation SKU "{v.sku}" within this product.')
                elif v.sku == self.sku:
                    errors.append(f'Variation SKU "{v.sku}" must not be the same as the parent SKU.')
                seen_skus.add(v.sku)
                if not self._is_non_negative_number(v.price):
                    errors.append(f'Variation "{v.sku}": price must be a non-negative number.')
                if v.sale_price and not self._is_non_negative_number(v.sale_price):
                    errors.append(f'Variation "{v.sku}": sale price must be a non-negative number.')

        return errors

    @staticmethod
    def _is_non_negative_number(value: str) -> bool:
        if value is None or str(value).strip() == "":
            return False
        try:
            return float(value) >= 0
        except (TypeError, ValueError):
            return False
