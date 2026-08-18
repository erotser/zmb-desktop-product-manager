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
    delay_seconds = 0  # artificial per-request delay, for timing-sensitive tests

    def log_message(self, *a):
        pass

    def _send_json(self, status, body):
        if MockHandler.delay_seconds:
            import time
            time.sleep(MockHandler.delay_seconds)
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
    MockHandler.delay_seconds = 0
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


def test_cancel_before_start_processes_nothing(connection, qtbot):
    """
    A fully deterministic case, unlike the mid-run scenario below: if
    cancel() is called before start(), the loop's very first cancellation
    check (before attempting product #1) exits immediately. No cross-
    thread timing is involved at all here, so this is a reliable way to
    confirm the cancellation flag itself works correctly.
    """
    products = make_products(["A", "B", "C"])
    worker = SyncAllWorker(connection, products)
    worker.cancel()

    with qtbot.waitSignal(worker.finished_all, timeout=5000) as blocker:
        worker.start()
    worker.wait()

    succeeded, failed, details = blocker.args
    assert succeeded == 0
    assert failed == 0


def test_cancel_mid_run_stops_before_processing_the_full_list(connection, qtbot):
    """
    Regression: an earlier version of this test cancelled from inside a
    progress callback (or waited for one specific progress signal, then
    cancelled) and asserted an EXACT stopping point (e.g. "C must never be
    attempted"). That's not actually testable reliably: there is no
    synchronization point between "this thread has observed the signal
    for item N" and "the worker thread has or hasn't already started item
    N+1" -- the worker never pauses after emitting a signal, and the
    observation of that signal on this thread is itself delayed by an
    indeterminate amount, during which the worker keeps running freely.
    Both delays are the same rough magnitude and race against each other;
    no amount of added artificial delay makes that deterministic, it only
    changes how often the race is lost, which is exactly why this test
    passed reliably in this sandbox but failed on real Windows CI, then
    still failed intermittently here too once more system load was added
    by the rest of the suite running alongside it.

    The actual guarantee this feature needs is "stops meaningfully soon
    after being cancelled", not "stops at one precise iteration boundary"
    -- cancellation is deliberately best-effort (adding real cross-thread
    synchronization to guarantee an exact stopping point would cost
    responsiveness for no real user-facing benefit). This tests that
    honest guarantee directly: cancelling shortly after a longer run
    starts results in meaningfully fewer than all items being processed.
    """
    MockHandler.delay_seconds = 0.05
    try:
        products = make_products([f"P{i}" for i in range(20)])
        worker = SyncAllWorker(connection, products)

        progress_calls = []
        worker.progress.connect(lambda index, total, sku, success, message: progress_calls.append(sku))

        results = {}
        worker.finished_all.connect(lambda s, f, d: results.update(succeeded=s, failed=f, details=d))

        worker.start()
        qtbot.waitUntil(lambda: len(progress_calls) >= 1, timeout=8000)
        worker.cancel()

        qtbot.waitUntil(lambda: "succeeded" in results, timeout=8000)
        worker.wait()

        total_processed = results["succeeded"] + results["failed"]
        assert total_processed < len(products)  # did not process everything
        assert total_processed < len(products) // 2  # stopped meaningfully early, not just "one short"
    finally:
        MockHandler.delay_seconds = 0


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
