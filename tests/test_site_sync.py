"""
These tests run a real local HTTP server (in a background thread) that
mimics the plugin's zombee/v1 REST endpoints, and point the real
site_sync client at it -- exercising actual HTTP request/response
handling (headers, status codes, JSON bodies) rather than mocking urllib
itself, the same approach used for test_image_downloader.py.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.models import CustomField, Product, ProductAttribute, Variation
from app import site_sync
from app.site_sync import SiteConnection, SiteSyncError, build_sync_payload, sync_product

VALID_USER = "admin"
VALID_PASSWORD = "xxxx xxxx xxxx xxxx xxxx xxxx"


class MockPluginHandler(BaseHTTPRequestHandler):
    # Class-level so the test can configure behavior per-test.
    behavior = "success"

    def log_message(self, format, *args):
        pass  # silence default request logging in test output

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        expected = "Basic " + __import__("base64").b64encode(
            f"{VALID_USER}:{VALID_PASSWORD}".encode()
        ).decode()
        return auth == expected

    def _send_json(self, status: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, status: int, html: str):
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self._check_auth():
            self._send_json(401, {"code": "rest_forbidden", "message": "Auth failed"})
            return
        if self.path == "/wp-json/zombee/v1/status":
            if self.behavior == "no_plugin":
                self._send_json(404, {"code": "rest_no_route", "message": "No route"})
                return
            if self.behavior == "no_permission":
                self._send_json(403, {"code": "vpci_rest_forbidden", "message": "No permission"})
                return
            if self.behavior == "no_permission_detailed":
                # Mirrors the real plugin's actual diagnostic 403 response.
                self._send_json(403, {
                    "code": "vpci_rest_forbidden",
                    "message": "This account (roles: administrator) does not have the "
                               "manage_woocommerce capability. Try deactivating and "
                               "reactivating WooCommerce.",
                })
                return
            if self.behavior == "security_plugin_html_block":
                # Simulates a security plugin or hosting firewall
                # intercepting the request BEFORE it reaches our plugin at
                # all, returning its own HTML block page instead of JSON.
                self._send_html(403, "<html><body><h1>403 Forbidden</h1><p>Request blocked by security policy.</p></body></html>")
                return
            self._send_json(200, {
                "plugin": "zombee-product-manager", "plugin_version": "1.4.2",
                "site_name": "Test Site", "woocommerce_active": True, "user": VALID_USER,
            })
            return
        self._send_json(404, {"code": "rest_no_route", "message": "Not found"})

    def do_POST(self):
        if not self._check_auth():
            self._send_json(401, {"code": "rest_forbidden", "message": "Auth failed"})
            return
        if self.path == "/wp-json/zombee/v1/products":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            if self.behavior == "validation_failure":
                self._send_json(422, {
                    "success": False, "product_id": None,
                    "counts": {"products_created": 0, "products_updated": 0, "variations_created": 0,
                               "variations_updated": 0, "rows_failed": 1},
                    "log": [f'FAILED parent {body.get("parent_sku")}: A variable product needs at least one variation.'],
                })
                return

            if self.behavior == "wp_error_shape":
                # This is what WordPress's REST framework actually sends when
                # json_to_group() itself returns a WP_Error (e.g. missing
                # price) -- a completely different shape from our own
                # {success, counts, log} response, NOT the shape above.
                self._send_json(400, {
                    "code": "vpci_rest_missing_price",
                    "message": "price is required.",
                    "data": {"status": 400},
                })
                return

            self._send_json(200, {
                "success": True, "product_id": 4242,
                "counts": {"products_created": 1, "products_updated": 0, "variations_created": 0,
                           "variations_updated": 0, "rows_failed": 0},
                "log": [f'Creating new product {body.get("parent_sku")}'],
                "_received_payload": body,  # test-only, lets us assert on what was actually sent
            })
            return
        self._send_json(404, {"code": "rest_no_route", "message": "Not found"})


@pytest.fixture
def mock_server():
    MockPluginHandler.behavior = "success"
    server = HTTPServer(("127.0.0.1", 0), MockPluginHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=2)


@pytest.fixture
def connection(mock_server):
    return SiteConnection(site_url=mock_server, username=VALID_USER, application_password=VALID_PASSWORD)


def test_connection_success(connection):
    result = site_sync.test_connection(connection)
    assert result["plugin"] == "zombee-product-manager"
    assert result["plugin_version"] == "1.4.2"


def test_site_url_missing_scheme_is_normalized_to_https():
    connection = SiteConnection(site_url="example.com", username="admin", application_password="x")
    assert connection.site_url == "https://example.com"
    assert connection.base_api_url() == "https://example.com/wp-json/zombee/v1"


def test_site_url_with_scheme_is_left_alone():
    connection = SiteConnection(site_url="http://example.com", username="admin", application_password="x")
    assert connection.site_url == "http://example.com"


def test_site_url_trailing_slash_still_handled_correctly():
    connection = SiteConnection(site_url="example.com/", username="admin", application_password="x")
    assert connection.base_api_url() == "https://example.com/wp-json/zombee/v1"


def test_connection_wrong_credentials(mock_server):
    bad_connection = SiteConnection(site_url=mock_server, username=VALID_USER, application_password="wrong")
    with pytest.raises(SiteSyncError, match="Authentication failed"):
        site_sync.test_connection(bad_connection)


def test_connection_plugin_not_installed(connection):
    MockPluginHandler.behavior = "no_plugin"
    with pytest.raises(SiteSyncError, match="installed and active"):
        site_sync.test_connection(connection)


def test_connection_no_permission(connection):
    MockPluginHandler.behavior = "no_permission"
    with pytest.raises(SiteSyncError, match="permission"):
        site_sync.test_connection(connection)


def test_connection_shows_server_detailed_message_not_generic_fallback(connection):
    """
    Regression: test_connection() previously ignored the server's actual
    response body entirely for any HTTPError and always substituted a
    hardcoded generic message. This meant the plugin's diagnostic 403
    message (naming the account's actual roles and the real cause) never
    reached the user -- they saw the same generic "no permission" text
    regardless of what the server actually said.
    """
    MockPluginHandler.behavior = "no_permission_detailed"
    with pytest.raises(SiteSyncError) as exc_info:
        site_sync.test_connection(connection)
    assert "administrator" in str(exc_info.value)
    assert "manage_woocommerce" in str(exc_info.value)
    assert str(exc_info.value) != "This account doesn't have permission to manage products."


def test_connection_shows_raw_body_when_response_is_not_json(connection):
    """
    If something OTHER than our plugin intercepts the request (a security
    plugin or hosting firewall returning its own HTML block page instead
    of our JSON), the raw response must still be surfaced -- not silently
    swallowed in favor of a generic message that hides what's really
    happening.
    """
    MockPluginHandler.behavior = "security_plugin_html_block"
    with pytest.raises(SiteSyncError) as exc_info:
        site_sync.test_connection(connection)
    message = str(exc_info.value)
    assert "raw response" in message
    assert "Request blocked by security policy" in message


def test_connection_unreachable_host():
    unreachable = SiteConnection(site_url="http://127.0.0.1:1", username="x", application_password="y")
    with pytest.raises(SiteSyncError, match="Could not reach"):
        site_sync.test_connection(unreachable, timeout=2)


def test_sync_simple_product_success(connection):
    product = Product(sku="MUG-001", product_type="simple", name="Mug", price="10.00")
    result = sync_product(connection, product)
    assert result["success"] is True
    assert result["product_id"] == 4242
    assert result["_warnings"] == []


def test_sync_sends_correct_payload_shape(connection):
    product = Product(
        sku="MUG-001", product_type="simple", name="Ceramic Mug", price="12.50",
        categories="Home > Kitchen", tags="Bestseller",
        custom_fields=[CustomField(name="material_origin", value="Portugal")],
        attributes=[ProductAttribute(name="Material", values=["Ceramic", "Stoneware"])],
    )
    result = sync_product(connection, product)
    sent = result["_received_payload"]
    assert sent["parent_sku"] == "MUG-001"
    assert sent["product_type"] == "simple"
    assert sent["price"] == "12.50"
    assert sent["product_categories"] == "Home > Kitchen"
    assert sent["custom_fields"] == {"material_origin": "Portugal"}
    assert sent["attributes"] == {"Material": ["Ceramic", "Stoneware"]}


def test_sync_variable_product_sends_variations(connection):
    product = Product(
        sku="TSHIRT-001", product_type="variable", name="Tee",
        variations=[
            Variation(sku="TSHIRT-001-RED-S", price="19.99", attribute_values={"Color": "Red", "Size": "S"}),
        ],
    )
    result = sync_product(connection, product)
    sent = result["_received_payload"]
    assert len(sent["variations"]) == 1
    assert sent["variations"][0]["sku"] == "TSHIRT-001-RED-S"
    assert sent["variations"][0]["attribute_values"] == {"Color": "Red", "Size": "S"}


def test_sync_reports_validation_failure_from_server(connection):
    MockPluginHandler.behavior = "validation_failure"
    product = Product(sku="X-001", product_type="variable", name="X")
    result = sync_product(connection, product)
    assert result["success"] is False
    assert "at least one variation" in result["log"][0]


def test_sync_normalizes_raw_wp_error_response_shape(connection):
    """Regression: json_to_group() rejecting a request (missing price,
    duplicate SKU, etc) makes WordPress return its standard {code,
    message, data} error shape, completely different from our own
    {success, counts, log} shape. Without normalizing this, the actual
    error message was silently dropped and the user saw nothing useful."""
    MockPluginHandler.behavior = "wp_error_shape"
    product = Product(sku="X-001", product_type="simple", name="X", price="1")
    result = sync_product(connection, product)
    assert result["success"] is False
    assert result["log"] == ["price is required."]


def test_sync_unreachable_host_raises():
    unreachable = SiteConnection(site_url="http://127.0.0.1:1", username="x", application_password="y")
    product = Product(sku="X", product_type="simple", name="X", price="1")
    with pytest.raises(SiteSyncError, match="Could not reach"):
        sync_product(unreachable, product, timeout=2)


def test_build_payload_skips_local_only_image_with_warning():
    product = Product(
        sku="X", product_type="simple", name="X", price="1",
        image_path="/local/only/photo.jpg", image_ref=None,
    )
    payload, warnings = build_sync_payload(product)
    assert "product_image" not in payload
    assert len(warnings) == 1
    assert "isn't uploaded to the site yet" in warnings[0]


def test_build_payload_includes_image_with_existing_ref():
    product = Product(
        sku="X", product_type="simple", name="X", price="1",
        image_path=None, image_ref="https://example.com/photo.jpg",
    )
    payload, warnings = build_sync_payload(product)
    assert payload["product_image"] == "https://example.com/photo.jpg"
    assert warnings == []


def test_build_payload_prefers_ref_over_local_path_when_both_present():
    """A downloaded image has both a local path (for preview) and the
    original ref -- the ref (already-live URL) should be sent, not treated
    as a local-only image needing a warning."""
    product = Product(
        sku="X", product_type="simple", name="X", price="1",
        image_path="/cache/downloaded.jpg", image_ref="https://example.com/photo.jpg",
    )
    payload, warnings = build_sync_payload(product)
    assert payload["product_image"] == "https://example.com/photo.jpg"
    assert warnings == []
