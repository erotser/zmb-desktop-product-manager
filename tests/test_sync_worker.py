import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.models import Product
from app.site_sync import SiteConnection
from app.sync_worker import SyncAllWorker

VALID_USER = "admin"
VALID_PASSWORD = "xxxx xxxx xxxx xxxx"


class MockHandler(BaseHTTPRequestHandler):
    # Class-level so tests can configure per-SKU behavior.
    fail_skus = set()  # SKUs that should get a structured failure response
    error_skus = set()  # SKUs that should get a transport-level error (connection refused simulation via 500)

    def log_message(self, *a):
        pass

    def _send_json(self, status, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        sku = body.get("parent_sku")

        if sku in MockHandler.error_skus:
            self._send_json(500, {"code": "server_error", "message": "Internal error"})
            return

        if sku in MockHandler.fail_skus:
            self._send_json(422, {
                "success": False, "product_id": None,
                "counts": {"products_created": 0, "products_updated": 0, "variations_created": 0,
                           "variations_updated": 0, "rows_failed": 1},
                "log": [f"FAILED parent {sku}: something was wrong with this one"],
            })
            return

        self._send_json(200, {
            "success": True, "product_id": 1,
            "counts": {"products_created": 1, "products_updated": 0, "variations_created": 0,
                       "variations_updated": 0, "rows_failed": 0},
            "log": [f"Creating new product {sku}"],
        })


@pytest.fixture
def mock_server():
    MockHandler.fail_skus = set()
    MockHandler.error_skus = set()
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=2)


@pytest.fixture
def connection(mock_server):
    return SiteConnection(site_url=mock_server, username=VALID_USER, application_password=VALID_PASSWORD)


def make_products(skus):
    return [Product(sku=sku, product_type="simple", name=sku, price="10") for sku in skus]


def test_all_succeed(connection, qtbot):
    products = make_products(["A", "B", "C"])
    worker = SyncAllWorker(connection, products)

    with qtbot.waitSignal(worker.finished_all, timeout=5000) as blocker:
        worker.start()

    worker.wait()

    succeeded, failed, details = blocker.args
    assert succeeded == 3
    assert failed == 0
    assert details == []


def test_progress_emitted_for_every_product_in_order(connection, qtbot):
    products = make_products(["A", "B", "C"])
    worker = SyncAllWorker(connection, products)

    progress_calls = []
    worker.progress.connect(lambda *args: progress_calls.append(args))

    with qtbot.waitSignal(worker.finished_all, timeout=5000):
        worker.start()

    worker.wait()

    assert len(progress_calls) == 3
    skus_in_order = [call[2] for call in progress_calls]
    assert skus_in_order == ["A", "B", "C"]
    indices = [call[0] for call in progress_calls]
    assert indices == [1, 2, 3]
    totals = [call[1] for call in progress_calls]
    assert totals == [3, 3, 3]


def test_mixed_success_and_structured_failure(connection, qtbot):
    MockHandler.fail_skus = {"B"}
    products = make_products(["A", "B", "C"])
    worker = SyncAllWorker(connection, products)

    with qtbot.waitSignal(worker.finished_all, timeout=5000) as blocker:
        worker.start()

    worker.wait()

    succeeded, failed, details = blocker.args
    assert succeeded == 2
    assert failed == 1
    assert len(details) == 1
    assert "B" in details[0]
    assert "something was wrong" in details[0]


def test_one_transport_failure_does_not_stop_the_rest(connection, qtbot):
    """A network-level failure (not just a structured 'product invalid'
    response) for one product must not abort the whole run -- the
    remaining products should still be attempted."""
    MockHandler.error_skus = {"B"}
    products = make_products(["A", "B", "C"])
    worker = SyncAllWorker(connection, products)

    with qtbot.waitSignal(worker.finished_all, timeout=5000) as blocker:
        worker.start()

    worker.wait()

    succeeded, failed, details = blocker.args
    assert succeeded == 2  # A and C
    assert failed == 1  # B
    assert any("B" in d for d in details)


def test_cancel_stops_before_processing_remaining_products(connection, qtbot):
    products = make_products(["A", "B", "C", "D", "E"])
    worker = SyncAllWorker(connection, products)

    progress_calls = []

    def on_progress(index, total, sku, success, message):
        progress_calls.append(sku)
        if sku == "B":
            worker.cancel()

    worker.progress.connect(on_progress)

    with qtbot.waitSignal(worker.finished_all, timeout=5000) as blocker:
        worker.start()

    worker.wait()

    succeeded, failed, details = blocker.args
    # Cancelled after B was processed -- C, D, E should never have been attempted.
    assert "C" not in progress_calls
    assert "D" not in progress_calls
    assert "E" not in progress_calls
    assert succeeded + failed == 2  # only A and B were actually processed


def test_success_with_image_warnings_reported_in_progress_message(connection, qtbot, monkeypatch):
    """A product that syncs successfully but had a local-only image skipped
    should still count as a success, with the warning surfaced via the
    progress message rather than silently dropped."""
    from app import site_sync

    def fake_sync_product(connection, product, timeout=30):
        return {
            "success": True, "product_id": 1, "counts": {}, "log": [],
            "_warnings": ["Main image: this image was picked locally but isn't uploaded yet."],
        }

    monkeypatch.setattr(site_sync, "sync_product", fake_sync_product)
    # sync_worker imported sync_product directly, so patch it there too.
    import app.sync_worker as sync_worker_module
    monkeypatch.setattr(sync_worker_module, "sync_product", fake_sync_product)

    products = make_products(["A"])
    worker = SyncAllWorker(connection, products)

    progress_calls = []
    worker.progress.connect(lambda *args: progress_calls.append(args))

    with qtbot.waitSignal(worker.finished_all, timeout=5000) as blocker:
        worker.start()

    worker.wait()

    succeeded, failed, details = blocker.args
    assert succeeded == 1
    assert failed == 0
    index, total, sku, success, message = progress_calls[0]
    assert success is True
    assert "isn't uploaded yet" in message


def test_empty_product_list_finishes_immediately(connection, qtbot):
    worker = SyncAllWorker(connection, [])
    with qtbot.waitSignal(worker.finished_all, timeout=5000) as blocker:
        worker.start()
    worker.wait()
    succeeded, failed, details = blocker.args
    assert succeeded == 0
    assert failed == 0
