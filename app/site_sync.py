"""
HTTP client for the Zombee Product Manager WordPress plugin's REST API
(zombee/v1), used for the "Sync to Site" feature -- pushing a single
product from the local database straight to the live WooCommerce site, as
a faster alternative to the CSV export/import workflow.

Authenticates with WordPress's built-in Application Passwords (HTTP Basic
Auth using a WP username + application password). No custom auth code here
-- leaning entirely on WordPress core's own, already-audited implementation
rather than building a new one.

Deliberately stdlib-only (urllib), matching image_downloader.py's choice
not to add `requests` for what's fundamentally simple request/response
traffic.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .models import Product
from . import __version__

# Without a distinctive User-Agent, Python's urllib sends its own default
# ("Python-urllib/3.x"), which is one of the most commonly blocked strings
# on the internet -- security plugins (Wordfence, etc.) and hosting-level
# firewalls routinely block it by default as an obvious automated-script
# signature, with zero site-specific configuration needed to trigger it.
USER_AGENT = f"ZombeeProductManager/{__version__}"


class SiteSyncError(Exception):
    """Raised for transport-level failures (can't reach the site, response
    wasn't JSON at all, etc) where there's no structured server response to
    show the user. A structured failure FROM the server (e.g. "this
    product failed validation") is returned normally as a dict, not raised
    -- see sync_product()."""
    pass


@dataclass
class SiteConnection:
    site_url: str  # e.g. "https://example.com" -- trailing slash tolerated
    username: str
    application_password: str

    def __post_init__(self):
        self.site_url = _normalize_site_url(self.site_url)

    def base_api_url(self) -> str:
        return self.site_url.rstrip("/") + "/wp-json/zombee/v1"

    def _auth_header(self) -> str:
        token = base64.b64encode(
            f"{self.username}:{self.application_password}".encode("utf-8")
        ).decode("ascii")
        return f"Basic {token}"


def _normalize_site_url(url: str) -> str:
    """A user is likely to type just "example.com" instead of
    "https://example.com" -- without a scheme, urllib raises a raw
    ValueError ("unknown url type") that's neither caught by our error
    handling nor meaningful to show someone. Default to https, which is
    what the overwhelming majority of WordPress sites use today; anyone on
    plain http can still type the scheme explicitly."""
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


def _describe_http_error(e: urllib.error.HTTPError, site_url: str) -> str:
    if e.code == 401:
        return "Authentication failed -- check the username and application password."
    if e.code == 403:
        return "This account doesn't have permission to manage products."
    if e.code == 404:
        return (
            "Could not find the sync endpoint -- is Zombee Product Manager "
            "installed and active on that site?"
        )
    return f"Site returned an error ({e.code})."


def _read_error_detail(e: urllib.error.HTTPError) -> Optional[str]:
    """
    Tries to extract the server's own error message from an HTTPError's
    response body (WordPress serializes both WP_Error responses and our
    own custom error responses as JSON with a "message" field). If the
    body isn't JSON, or is JSON but has no usable "message" field, this
    still surfaces a raw snippet of whatever WAS returned rather than
    discarding it -- an unexpected response shape (e.g. a security
    plugin's own HTML block page, or a hosting firewall's challenge page)
    is itself a critical diagnostic clue, and silently hiding it just
    turns a solvable problem into a mystery.
    """
    try:
        raw = e.read().decode("utf-8", errors="replace")
    except AttributeError:
        return None

    try:
        body = json.loads(raw)
        if isinstance(body, dict) and body.get("message"):
            return str(body["message"])
    except json.JSONDecodeError:
        pass

    raw = raw.strip()
    if not raw:
        return None
    snippet = raw[:300] + ("..." if len(raw) > 300 else "")
    return f"(raw response) {snippet}"


def test_connection(connection: SiteConnection, timeout: int = 15) -> dict:
    """
    Calls the /status endpoint to verify the URL, credentials, and that the
    plugin is actually present -- before attempting a real sync. Returns
    the parsed response dict (plugin_version, site_name, etc) on success.
    Raises SiteSyncError with a specific, actionable reason on failure.
    """
    url = connection.base_api_url() + "/status"
    request = urllib.request.Request(
        url, headers={"Authorization": connection._auth_header(), "User-Agent": USER_AGENT}
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        fallback = _describe_http_error(e, connection.site_url)
        detail = _read_error_detail(e)
        if detail and detail.strip() and detail.strip() != fallback.strip():
            message = f'{fallback} Server said: "{detail}"'
        else:
            message = fallback
        raise SiteSyncError(message) from e
    except urllib.error.URLError as e:
        raise SiteSyncError(f"Could not reach {connection.site_url}: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise SiteSyncError(
            "Site responded, but not with valid JSON -- check the site URL is correct."
        ) from e
    except ValueError as e:
        raise SiteSyncError(f"\"{connection.site_url}\" doesn't look like a valid URL.") from e

    if not isinstance(data, dict) or "plugin" not in data:
        raise SiteSyncError("Unexpected response -- is Zombee Product Manager installed on that site?")

    return data


def build_sync_payload(product: Product) -> tuple[dict, list[str]]:
    """
    Converts a local Product into the JSON shape the plugin's /products
    endpoint expects. Returns (payload, warnings).

    Images: only images that already have a live reference (image_ref --
    from a prior CSV import, or a Download that was then re-uploaded) are
    included. A LOCAL-ONLY image (freshly picked in this app, never
    uploaded anywhere) has no URL the site could use, so sync can't include
    it -- syncing doesn't upload new media. Those get reported as warnings
    so the user knows that specific image still needs the CSV export +
    manual upload path.
    """
    warnings: list[str] = []

    def resolve_image(local_path: Optional[str], ref: Optional[str], label: str) -> Optional[str]:
        if ref:
            return ref
        if local_path:
            warnings.append(
                f'{label}: this image was picked locally but isn\'t uploaded to the site yet, '
                f'so sync will skip it. Use CSV export for this image instead.'
            )
        return None

    payload: dict = {
        "parent_sku": product.sku,
        "product_type": product.product_type,
        "product_name": product.name,
        "product_description": product.description,
        "product_short_description": product.short_description,
        "product_categories": product.categories,
        "product_tags": product.tags,
        "product_image_alt": product.image_alt,
        "attributes": {a.name: a.values for a in product.attributes},
        "custom_fields": {c.name: c.value for c in product.custom_fields},
    }

    main_image = resolve_image(product.image_path, product.image_ref, "Main image")
    if main_image:
        payload["product_image"] = main_image

    gallery_urls, gallery_alts = [], []
    for g in product.gallery:
        url = resolve_image(g.path, g.image_ref, "Gallery image")
        if url:
            gallery_urls.append(url)
            gallery_alts.append(g.alt)
    if gallery_urls:
        payload["product_gallery_images"] = gallery_urls
        payload["product_gallery_images_alt"] = gallery_alts

    if product.is_simple():
        payload["price"] = product.price
        payload["sale_price"] = product.sale_price
        payload["stock_qty"] = product.stock_qty
        payload["manage_stock"] = product.manage_stock
    else:
        variations = []
        for v in product.variations:
            var_image = resolve_image(v.image_path, v.image_ref, f'Variation "{v.sku}" image')
            variation_data = {
                "sku": v.sku,
                "price": v.price,
                "sale_price": v.sale_price,
                "stock_qty": v.stock_qty,
                "manage_stock": v.manage_stock,
                "image_alt": v.image_alt,
                "description": v.description,
                "attribute_values": v.attribute_values,
            }
            if var_image:
                variation_data["image"] = var_image
            variations.append(variation_data)
        payload["variations"] = variations

    return payload, warnings


def sync_product(connection: SiteConnection, product: Product, timeout: int = 30) -> dict:
    """
    Pushes `product` to the live site. Returns the parsed response dict
    (with 'success', 'counts', 'log', 'product_id', plus a locally-added
    '_warnings' key for skipped local-only images) for ANY response the
    server gave, including a structured success=false response -- so the
    caller can show the server's own explanation for a validation failure.

    Raises SiteSyncError only when there's no server response to show at
    all (network failure, non-JSON response, etc).
    """
    payload, warnings = build_sync_payload(product)
    body = json.dumps(payload).encode("utf-8")

    url = connection.base_api_url() + "/products"
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": connection._auth_header(),
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # The server may return one of two different shapes here:
        #   1. Our own {success, product_id, counts, log} shape, if
        #      json_to_group() succeeded and VPCI_Importer actually ran
        #      (even a partial/total import failure still comes back in
        #      this shape).
        #   2. WordPress's standard WP_Error shape ({code, message, data}),
        #      if the request was rejected before that point -- auth
        #      failure, or json_to_group() itself returning a WP_Error
        #      (missing price, duplicate variation SKU, invalid
        #      product_type, no variations, etc). Without normalizing this
        #      to look like shape 1, the actual reason ends up nowhere the
        #      UI looks for it, and the user just sees "no details".
        try:
            data = json.loads(e.read().decode("utf-8"))
            if "success" not in data and "message" in data:
                data = {
                    "success": False,
                    "product_id": None,
                    "counts": {},
                    "log": [str(data["message"])],
                }
            data["_http_status"] = e.code
        except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
            raise SiteSyncError(_describe_http_error(e, connection.site_url)) from e
    except urllib.error.URLError as e:
        raise SiteSyncError(f"Could not reach {connection.site_url}: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise SiteSyncError("Site responded, but not with valid JSON.") from e
    except ValueError as e:
        raise SiteSyncError(f"\"{connection.site_url}\" doesn't look like a valid URL.") from e

    data["_warnings"] = warnings
    return data
