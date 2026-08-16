"""
CSV import/export matching the Zombee Product Manager WordPress plugin's
exact column format, so files move freely between this app and the plugin
in either direction.

Column order (must match includes/class-vpci-exporter.php build_header()):
    parent_sku, product_type, product_name, product_description,
    product_short_description, product_categories, product_tags,
    product_image, product_image_alt, product_gallery_images,
    product_gallery_images_alt, [attribute:Name...], [customf:Name...],
    variation_sku, variation_price, variation_sale_price,
    variation_stock_qty, variation_manage_stock, variation_image,
    variation_image_alt, variation_description
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

from .models import CustomField, GalleryImage, Product, ProductAttribute, Variation


BASE_HEADER_BEFORE_DYNAMIC = [
    "parent_sku", "product_type", "product_name", "product_description",
    "product_short_description", "product_categories", "product_tags",
    "product_image", "product_image_alt", "product_gallery_images",
    "product_gallery_images_alt",
]
BASE_HEADER_AFTER_DYNAMIC = [
    "variation_sku", "variation_price", "variation_sale_price",
    "variation_stock_qty", "variation_manage_stock", "variation_image",
    "variation_image_alt", "variation_description",
]

REQUIRED_COLUMNS = {"parent_sku", "product_name", "variation_price"}

_ATTR_RE = re.compile(r"^attribute\s*:\s*(.+)$", re.IGNORECASE)
_CUSTOMF_RE = re.compile(r"^customf\s*:\s*(.+)$", re.IGNORECASE)
_FORMULA_TRIGGER_RE = re.compile(r"^[=+\-@\t\r]")
_ESCAPED_TRIGGER_RE = re.compile(r"^'[=+\-@\t\r]")


class CsvFormatError(Exception):
    pass


# ---------------------------------------------------------------------- #
# Formula-injection protection (mirrors VPCI_Exporter::sanitize_csv_cell /
# VPCI_CSV_Parser::strip_formula_escape in the WordPress plugin exactly, so
# a file round-tripped through either tool behaves identically).
# ---------------------------------------------------------------------- #

def sanitize_csv_cell(value: str) -> str:
    if not isinstance(value, str) or value == "":
        return value
    if _FORMULA_TRIGGER_RE.match(value):
        return "'" + value
    return value


def strip_formula_escape(value: str) -> str:
    if isinstance(value, str) and _ESCAPED_TRIGGER_RE.match(value):
        return value[1:]
    return value


# ---------------------------------------------------------------------- #
# Export
# ---------------------------------------------------------------------- #

def collect_attribute_names(products: list[Product]) -> list[str]:
    seen: dict[str, None] = {}
    for p in products:
        for a in p.attributes:
            seen.setdefault(a.name, None)
    return list(seen.keys())


def collect_custom_field_names(products: list[Product]) -> list[str]:
    seen: dict[str, None] = {}
    for p in products:
        for cf in p.custom_fields:
            seen.setdefault(cf.name, None)
    return list(seen.keys())


def build_header(attribute_names: list[str], custom_field_names: list[str]) -> list[str]:
    header = list(BASE_HEADER_BEFORE_DYNAMIC)
    header += [f"attribute:{name}" for name in attribute_names]
    header += [f"customf:{name}" for name in custom_field_names]
    header += list(BASE_HEADER_AFTER_DYNAMIC)
    return header


def export_to_csv(
    products: list[Product],
    csv_path: str | Path,
    image_filename_map: Optional[dict[str, str]] = None,
) -> None:
    """
    Writes `products` to a CSV file at `csv_path` in the plugin's format.

    `image_filename_map` should be the dict returned by
    ImageExporter.export_images() (original source path -> exported bare
    filename). If a product/variation image's source path isn't in the map
    (e.g. the image export step was skipped), that image column is left
    blank rather than writing something the plugin can't resolve.
    """
    image_filename_map = image_filename_map or {}

    attribute_names = collect_attribute_names(products)
    custom_field_names = collect_custom_field_names(products)
    header = build_header(attribute_names, custom_field_names)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for product in products:
            common = _common_row_fields(product, image_filename_map)

            if product.is_simple():
                writer.writerow(_sanitize_row(_build_simple_row(product, attribute_names, custom_field_names, common)))
            else:
                for variation in product.variations:
                    writer.writerow(_sanitize_row(
                        _build_variation_row(product, variation, attribute_names, custom_field_names, common, image_filename_map)
                    ))


def _sanitize_row(row: list) -> list:
    return [sanitize_csv_cell(str(v)) if v is not None else "" for v in row]


def _common_row_fields(product: Product, image_filename_map: dict[str, str]) -> dict:
    image_filename = _resolve_image_value(product.image_path, product.image_ref, image_filename_map)

    gallery_filenames = []
    gallery_alts = []
    for g in product.gallery:
        value = _resolve_image_value(g.path, g.image_ref, image_filename_map)
        if value:
            gallery_filenames.append(value)
            gallery_alts.append(g.alt)

    return {
        "image_filename": image_filename,
        "gallery_filenames": "|".join(gallery_filenames),
        "gallery_alts": "|".join(gallery_alts),
    }


def _resolve_image_value(local_path: Optional[str], existing_ref: Optional[str], image_filename_map: dict[str, str]) -> str:
    """
    An image column's export value, in priority order:
    1. A newly-picked local file that was just compressed/exported -> its new filename.
    2. No new local file, but there's an existing reference from an earlier
       import (a URL or a filename already on the site) -> keep it as-is,
       so re-exporting without touching this image doesn't blank it out.
    3. Neither -> empty.
    """
    if local_path and local_path in image_filename_map:
        return image_filename_map[local_path]
    if existing_ref:
        return existing_ref
    return ""


def _build_simple_row(product: Product, attribute_names: list[str], custom_field_names: list[str], common: dict) -> list:
    row = [
        product.sku,
        "simple",
        product.name,
        product.description,
        product.short_description,
        product.categories,
        product.tags,
        common["image_filename"],
        product.image_alt,
        common["gallery_filenames"],
        common["gallery_alts"],
    ]
    attr_map = {a.name: a for a in product.attributes}
    for name in attribute_names:
        row.append("|".join(attr_map[name].values) if name in attr_map else "")
    cf_map = {c.name: c.value for c in product.custom_fields}
    for name in custom_field_names:
        row.append(cf_map.get(name, ""))

    row += ["", product.price, product.sale_price, product.stock_qty, "yes" if product.manage_stock else "no", "", "", ""]
    return row


def _build_variation_row(
    product: Product, variation: Variation, attribute_names: list[str],
    custom_field_names: list[str], common: dict, image_filename_map: dict[str, str],
) -> list:
    row = [
        product.sku,
        "variable",
        product.name,
        product.description,
        product.short_description,
        product.categories,
        product.tags,
        common["image_filename"],
        product.image_alt,
        common["gallery_filenames"],
        common["gallery_alts"],
    ]
    for name in attribute_names:
        row.append(variation.attribute_values.get(name, ""))
    cf_map = {c.name: c.value for c in product.custom_fields}
    for name in custom_field_names:
        row.append(cf_map.get(name, ""))

    var_image_value = _resolve_image_value(variation.image_path, variation.image_ref, image_filename_map)
    row += [
        variation.sku, variation.price, variation.sale_price, variation.stock_qty,
        "yes" if variation.manage_stock else "no", var_image_value, variation.image_alt, variation.description,
    ]
    return row


# ---------------------------------------------------------------------- #
# Import
# ---------------------------------------------------------------------- #

def _normalize_header(col: str) -> str:
    col = col.strip()
    m = _ATTR_RE.match(col)
    if m:
        return f"attribute:{m.group(1).strip()}"
    m = _CUSTOMF_RE.match(col)
    if m:
        return f"customf:{m.group(1).strip()}"
    return col.strip().lower().replace(" ", "_").replace("-", "_")


def import_from_csv(csv_path: str | Path) -> tuple[list[Product], list[str]]:
    """
    Returns (products, warnings). Mirrors the plugin's VPCI_CSV_Parser
    behavior: groups rows by parent_sku, defaults product_type to
    "variable" if the column is absent (backward compatible with files that
    predate simple-product support), rejects negative/non-numeric prices,
    and reverses the export-side formula-injection escape.
    """
    warnings: list[str] = []

    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            raw_header = next(reader)
        except StopIteration:
            raise CsvFormatError("CSV file appears to be empty.")

        header = [_normalize_header(c) for c in raw_header]
        missing = REQUIRED_COLUMNS - set(header)
        if missing:
            raise CsvFormatError(f"CSV is missing required column(s): {', '.join(sorted(missing))}")

        has_product_type_column = "product_type" in header
        attribute_columns = {c: c.split(":", 1)[1] for c in header if c.startswith("attribute:")}
        custom_field_columns = {c: c.split(":", 1)[1] for c in header if c.startswith("customf:")}

        groups: dict[str, dict] = {}
        row_number = 1

        for raw_row in reader:
            row_number += 1
            if len(raw_row) == 1 and raw_row[0].strip() == "":
                continue

            assoc = {header[i]: strip_formula_escape(v) for i, v in enumerate(raw_row) if i < len(header)}

            parent_sku = assoc.get("parent_sku", "").strip()
            price = assoc.get("variation_price", "").strip()

            if not parent_sku or not price:
                warnings.append(f"Row {row_number} skipped: parent_sku and variation_price are required.")
                continue

            if not _is_number(price) or float(price) < 0:
                warnings.append(f'Row {row_number} ({parent_sku}) skipped: variation_price must be a non-negative number.')
                continue

            if has_product_type_column:
                product_type = assoc.get("product_type", "").strip().lower()
                if product_type not in ("simple", "variable"):
                    warnings.append(f'Row {row_number} ({parent_sku}) skipped: product_type must be "simple" or "variable".')
                    continue
            else:
                product_type = "variable"

            var_sku = assoc.get("variation_sku", "").strip()
            if product_type == "variable" and not var_sku:
                warnings.append(f'Row {row_number} ({parent_sku}) skipped: variation_sku is required for variable product rows.')
                continue

            if parent_sku not in groups:
                groups[parent_sku] = {"product_type": product_type, "meta": {}, "attribute_names": [], "custom_fields": {}, "rows": []}
            elif groups[parent_sku]["product_type"] != product_type:
                warnings.append(f'Row {row_number} ({parent_sku}) skipped: product_type does not match the type already used for this parent_sku.')
                continue

            if product_type == "simple" and groups[parent_sku]["rows"]:
                warnings.append(f'Row {row_number} ({parent_sku}) skipped: simple products only use one row.')
                continue

            for col in ("product_name", "product_description", "product_short_description",
                        "product_categories", "product_tags", "product_image", "product_image_alt",
                        "product_gallery_images", "product_gallery_images_alt"):
                val = assoc.get(col, "")
                if val and not groups[parent_sku]["meta"].get(col):
                    groups[parent_sku]["meta"][col] = val

            for col_key, field_name in custom_field_columns.items():
                val = assoc.get(col_key, "").strip()
                if val and field_name not in groups[parent_sku]["custom_fields"]:
                    groups[parent_sku]["custom_fields"][field_name] = val

            row_attributes = {}
            for col_key, attr_name in attribute_columns.items():
                val = assoc.get(col_key, "").strip()
                if val:
                    row_attributes[attr_name] = val
                    if attr_name not in groups[parent_sku]["attribute_names"]:
                        groups[parent_sku]["attribute_names"].append(attr_name)

            groups[parent_sku]["rows"].append({
                "variation_sku": var_sku,
                "variation_price": price,
                "variation_sale_price": assoc.get("variation_sale_price", "").strip(),
                "variation_stock_qty": assoc.get("variation_stock_qty", "").strip(),
                "variation_manage_stock": assoc.get("variation_manage_stock", "").strip(),
                "variation_image": assoc.get("variation_image", "").strip(),
                "variation_image_alt": assoc.get("variation_image_alt", "").strip(),
                "variation_description": assoc.get("variation_description", "").strip(),
                "attributes": row_attributes,
            })

    products = [_group_to_product(sku, g) for sku, g in groups.items()]
    return products, warnings


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _group_to_product(parent_sku: str, group: dict) -> Product:
    meta = group["meta"]
    manage_stock_yes = {"yes", "1", "true"}

    product = Product(
        sku=parent_sku,
        product_type=group["product_type"],
        name=meta.get("product_name", parent_sku),
        description=meta.get("product_description", ""),
        short_description=meta.get("product_short_description", ""),
        categories=meta.get("product_categories", ""),
        tags=meta.get("product_tags", ""),
        image_path=None,  # imported CSVs reference a filename/URL, not a local file -- see image_ref below
        image_alt=meta.get("product_image_alt", ""),
        image_ref=meta.get("product_image", "") or None,
        custom_fields=[CustomField(name=k, value=v) for k, v in group["custom_fields"].items()],
    )

    gallery_urls = [u for u in meta.get("product_gallery_images", "").split("|") if u]
    gallery_alts = meta.get("product_gallery_images_alt", "").split("|")
    product.gallery = [
        GalleryImage(path=None, alt=gallery_alts[i] if i < len(gallery_alts) else "", position=i, image_ref=url)
        for i, url in enumerate(gallery_urls)
    ]

    if group["attribute_names"]:
        # For a simple product, values across the (usually single) row are
        # already pipe-joined text in row_attributes; for a variable product
        # the palette is the union of values used across all variation rows.
        values_by_attr: dict[str, list[str]] = {name: [] for name in group["attribute_names"]}
        for row in group["rows"]:
            for name, val in row["attributes"].items():
                if group["product_type"] == "simple":
                    for v in val.split("|"):
                        v = v.strip()
                        if v and v not in values_by_attr[name]:
                            values_by_attr[name].append(v)
                else:
                    if val not in values_by_attr[name]:
                        values_by_attr[name].append(val)
        product.attributes = [
            ProductAttribute(name=name, values=values_by_attr[name], position=i)
            for i, name in enumerate(group["attribute_names"])
        ]

    if group["product_type"] == "simple":
        row = group["rows"][0]
        product.price = row["variation_price"]
        product.sale_price = row["variation_sale_price"]
        product.stock_qty = row["variation_stock_qty"]
        product.manage_stock = row["variation_manage_stock"].lower() in manage_stock_yes
    else:
        product.variations = [
            Variation(
                sku=row["variation_sku"],
                price=row["variation_price"],
                sale_price=row["variation_sale_price"],
                stock_qty=row["variation_stock_qty"],
                manage_stock=row["variation_manage_stock"].lower() in manage_stock_yes,
                description=row["variation_description"],
                image_path=None,
                image_alt=row["variation_image_alt"],
                image_ref=row["variation_image"] or None,
                attribute_values=dict(row["attributes"]),
            )
            for row in group["rows"]
        ]

    return product
