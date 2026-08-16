"""
Local SQLite storage for Zombee Product Manager Desktop.

This is the app's source of truth. CSV import/export (csv_io.py) reads and
writes this database; it never treats a CSV file itself as live data.
Uses the standard library sqlite3 module only -- no ORM dependency, to keep
the packaged .exe small and the logic easy to reason about.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .models import CustomField, GalleryImage, Product, ProductAttribute, Variation


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sku                 TEXT NOT NULL UNIQUE,
    product_type        TEXT NOT NULL CHECK (product_type IN ('simple', 'variable')),
    name                TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    short_description   TEXT NOT NULL DEFAULT '',
    categories          TEXT NOT NULL DEFAULT '',
    tags                TEXT NOT NULL DEFAULT '',
    image_path          TEXT,
    image_alt           TEXT NOT NULL DEFAULT '',
    image_ref            TEXT,
    price               TEXT NOT NULL DEFAULT '',
    sale_price          TEXT NOT NULL DEFAULT '',
    stock_qty           TEXT NOT NULL DEFAULT '',
    manage_stock        INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gallery_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    path        TEXT,
    alt         TEXT NOT NULL DEFAULT '',
    image_ref   TEXT,
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS attributes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    values_json TEXT NOT NULL DEFAULT '[]',
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS variations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku                 TEXT NOT NULL UNIQUE,
    price               TEXT NOT NULL DEFAULT '',
    sale_price          TEXT NOT NULL DEFAULT '',
    stock_qty           TEXT NOT NULL DEFAULT '',
    manage_stock        INTEGER NOT NULL DEFAULT 0,
    description         TEXT NOT NULL DEFAULT '',
    image_path          TEXT,
    image_alt           TEXT NOT NULL DEFAULT '',
    image_ref            TEXT,
    attribute_values_json TEXT NOT NULL DEFAULT '{}',
    position            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS custom_fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    value       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_gallery_product ON gallery_images(product_id);
CREATE INDEX IF NOT EXISTS idx_attributes_product ON attributes(product_id);
CREATE INDEX IF NOT EXISTS idx_variations_product ON variations(product_id);
CREATE INDEX IF NOT EXISTS idx_customfields_product ON custom_fields(product_id);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    def list_products(self) -> list[Product]:
        rows = self.conn.execute("SELECT id FROM products ORDER BY name COLLATE NOCASE").fetchall()
        return [self.get_product(row["id"]) for row in rows]

    def get_product(self, product_id: int) -> Optional[Product]:
        row = self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            return None
        return self._row_to_product(row)

    def get_product_by_sku(self, sku: str) -> Optional[Product]:
        row = self.conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        if not row:
            return None
        return self._row_to_product(row)

    def _row_to_product(self, row: sqlite3.Row) -> Product:
        pid = row["id"]

        gallery = [
            GalleryImage(path=g["path"], alt=g["alt"], position=g["position"], image_ref=g["image_ref"])
            for g in self.conn.execute(
                "SELECT * FROM gallery_images WHERE product_id = ? ORDER BY position", (pid,)
            ).fetchall()
        ]

        attributes = [
            ProductAttribute(name=a["name"], values=json.loads(a["values_json"]), position=a["position"])
            for a in self.conn.execute(
                "SELECT * FROM attributes WHERE product_id = ? ORDER BY position", (pid,)
            ).fetchall()
        ]

        variations = [
            Variation(
                id=v["id"],
                sku=v["sku"],
                price=v["price"],
                sale_price=v["sale_price"],
                stock_qty=v["stock_qty"],
                manage_stock=bool(v["manage_stock"]),
                description=v["description"],
                image_path=v["image_path"],
                image_alt=v["image_alt"],
                image_ref=v["image_ref"],
                attribute_values=json.loads(v["attribute_values_json"]),
            )
            for v in self.conn.execute(
                "SELECT * FROM variations WHERE product_id = ? ORDER BY position", (pid,)
            ).fetchall()
        ]

        custom_fields = [
            CustomField(name=c["name"], value=c["value"])
            for c in self.conn.execute(
                "SELECT * FROM custom_fields WHERE product_id = ? ORDER BY id", (pid,)
            ).fetchall()
        ]

        return Product(
            id=pid,
            sku=row["sku"],
            product_type=row["product_type"],
            name=row["name"],
            description=row["description"],
            short_description=row["short_description"],
            categories=row["categories"],
            tags=row["tags"],
            image_path=row["image_path"],
            image_alt=row["image_alt"],
            image_ref=row["image_ref"],
            price=row["price"],
            sale_price=row["sale_price"],
            stock_qty=row["stock_qty"],
            manage_stock=bool(row["manage_stock"]),
            gallery=gallery,
            attributes=attributes,
            variations=variations,
            custom_fields=custom_fields,
        )

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    def save_product(self, product: Product) -> Product:
        """Insert or update (matched by SKU). Returns the product with `id` populated."""
        errors = product.validate()
        if errors:
            raise ValueError("; ".join(errors))

        existing = self.get_product_by_sku(product.sku)

        with self.conn:
            if existing:
                product.id = existing.id
                self.conn.execute(
                    """UPDATE products SET product_type=?, name=?, description=?, short_description=?,
                       categories=?, tags=?, image_path=?, image_alt=?, image_ref=?, price=?, sale_price=?,
                       stock_qty=?, manage_stock=?, updated_at=datetime('now') WHERE id=?""",
                    (
                        product.product_type, product.name, product.description, product.short_description,
                        product.categories, product.tags, product.image_path, product.image_alt,
                        product.image_ref, product.price, product.sale_price, product.stock_qty,
                        int(product.manage_stock), product.id,
                    ),
                )
                self.conn.execute("DELETE FROM gallery_images WHERE product_id = ?", (product.id,))
                self.conn.execute("DELETE FROM attributes WHERE product_id = ?", (product.id,))
                self.conn.execute("DELETE FROM variations WHERE product_id = ?", (product.id,))
                self.conn.execute("DELETE FROM custom_fields WHERE product_id = ?", (product.id,))
            else:
                cur = self.conn.execute(
                    """INSERT INTO products (sku, product_type, name, description, short_description,
                       categories, tags, image_path, image_alt, image_ref, price, sale_price, stock_qty, manage_stock)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        product.sku, product.product_type, product.name, product.description,
                        product.short_description, product.categories, product.tags, product.image_path,
                        product.image_alt, product.image_ref, product.price, product.sale_price,
                        product.stock_qty, int(product.manage_stock),
                    ),
                )
                product.id = cur.lastrowid

            for i, g in enumerate(product.gallery):
                self.conn.execute(
                    "INSERT INTO gallery_images (product_id, path, alt, image_ref, position) VALUES (?, ?, ?, ?, ?)",
                    (product.id, g.path, g.alt, g.image_ref, i),
                )

            for i, a in enumerate(product.attributes):
                self.conn.execute(
                    "INSERT INTO attributes (product_id, name, values_json, position) VALUES (?, ?, ?, ?)",
                    (product.id, a.name, json.dumps(a.values), i),
                )

            for i, v in enumerate(product.variations):
                self.conn.execute(
                    """INSERT INTO variations (product_id, sku, price, sale_price, stock_qty, manage_stock,
                       description, image_path, image_alt, image_ref, attribute_values_json, position)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        product.id, v.sku, v.price, v.sale_price, v.stock_qty, int(v.manage_stock),
                        v.description, v.image_path, v.image_alt, v.image_ref,
                        json.dumps(v.attribute_values), i,
                    ),
                )

            for cf in product.custom_fields:
                self.conn.execute(
                    "INSERT INTO custom_fields (product_id, name, value) VALUES (?, ?, ?)",
                    (product.id, cf.name, cf.value),
                )

        return product

    def delete_product(self, product_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))

    def delete_product_by_sku(self, sku: str):
        with self.conn:
            self.conn.execute("DELETE FROM products WHERE sku = ?", (sku,))
