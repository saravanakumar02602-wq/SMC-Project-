"""Smart Manufacturer Centre: authenticated API and static application server."""

import json
import logging
import math
import os
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .database import DATABASE, connect_db, initialize_db, load_state, persist_state


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "3000"))
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo123")
SESSION_TTL = 12 * 60 * 60
MAX_BODY_BYTES = 5 * 1024 * 1024
PUBLIC_ASSETS = {"/index.html", "/style.css", "/app.js"}
USERS = {
    "Ravi": "Salesman",
    "Meena": "Factory admin",
    "Karthik": "Supervisor",
    "Subramani": "Owner",
    "Lakshmi": "Auditor",
}
SESSIONS = {}
LOGIN_FAILURES = {}
SESSION_LOCK = threading.Lock()
FAILURE_LOCK = threading.Lock()


def valid_state(state):
    def number(value, minimum=0):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= minimum
        )

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(state, dict):
        return False
    materials = state.get("M")
    products = state.get("P")
    customers = state.get("C")
    orders = state.get("O")
    invoices = state.get("I")
    ledger = state.get("L")
    runs = state.get("R")
    purchases = state.get("PU")
    logs = state.get("LG")
    sequence = state.get("seq")
    if not (
        isinstance(materials, dict) and materials
        and isinstance(products, dict) and products
        and isinstance(customers, list)
        and isinstance(orders, list)
        and isinstance(invoices, list)
        and isinstance(ledger, list)
        and isinstance(runs, list)
        and isinstance(purchases, list)
        and isinstance(logs, list)
        and isinstance(sequence, int)
        and not isinstance(sequence, bool)
    ):
        return False

    for material in materials.values():
        if not (
            isinstance(material, dict)
            and text(material.get("n"))
            and text(material.get("u"))
            and number(material.get("s"))
            and number(material.get("r"), 0.000001)
        ):
            return False
    for product in products.values():
        bom = product.get("bom") if isinstance(product, dict) else None
        if not (
            isinstance(product, dict)
            and text(product.get("n"))
            and number(product.get("pr"), 0.000001)
            and number(product.get("fg"))
            and number(product.get("lab"))
            and number(product.get("ovh"))
            and isinstance(bom, dict)
            and all(key in materials and number(quantity, 0.000001) for key, quantity in bom.items())
        ):
            return False

    customer_ids = [customer.get("id") for customer in customers if isinstance(customer, dict)]
    if len(customer_ids) != len(customers) or len(set(customer_ids)) != len(customer_ids):
        return False
    if any(
        not isinstance(customer.get("id"), int)
        or isinstance(customer.get("id"), bool)
        or not text(customer.get("n"))
        or not text(customer.get("st"))
        for customer in customers
    ):
        return False

    order_ids = [order.get("id") for order in orders if isinstance(order, dict)]
    if len(order_ids) != len(orders) or len(set(order_ids)) != len(order_ids):
        return False
    if any(
        not text(order.get("id"))
        or order.get("c") not in customer_ids
        or not text(order.get("by"))
        or not text(order.get("d"))
        or order.get("st") not in {"Submitted", "Approved", "Rejected", "Invoiced"}
        or not isinstance(order.get("l"), dict)
        or not order["l"]
        or any(
            key not in products
            or not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity <= 0
            for key, quantity in order.get("l", {}).items()
        )
        for order in orders
    ):
        return False

    invoice_numbers = [invoice.get("no") for invoice in invoices if isinstance(invoice, dict)]
    invoice_orders = [invoice.get("o") for invoice in invoices if isinstance(invoice, dict)]
    if (
        len(invoice_numbers) != len(invoices)
        or len(set(invoice_numbers)) != len(invoice_numbers)
        or len(set(invoice_orders)) != len(invoice_orders)
    ):
        return False
    order_by_id = {order["id"]: order for order in orders}
    customer_by_id = {customer["id"]: customer for customer in customers}
    for invoice in invoices:
        if not isinstance(invoice, dict) or invoice.get("o") not in order_by_id:
            return False
        order = order_by_id[invoice["o"]]
        if order.get("st") != "Invoiced":
            return False
        amounts = ("tx", "cg", "sg", "ig", "tot")
        if (
            not text(invoice.get("no"))
            or not text(invoice.get("d"))
            or any(not number(invoice.get(field)) for field in amounts)
            or abs(invoice["tot"] - invoice["tx"] - invoice["cg"] - invoice["sg"] - invoice["ig"]) > 0.02
            or not isinstance(invoice.get("disp"), bool)
            or not isinstance(invoice.get("aud"), bool)
            or not isinstance(invoice.get("pd"), list)
        ):
            return False
        taxable = sum(quantity * products[key]["pr"] for key, quantity in order["l"].items())
        tax = round(taxable * 0.05 + 1e-9, 2)
        if abs(invoice["tx"] - taxable) > 0.01 or abs(invoice["tot"] - taxable - tax) > 0.02:
            return False
        customer = customer_by_id[order["c"]]
        if customer["st"] == "Tamil Nadu":
            expected_cgst = round(tax / 2 + 1e-9, 2)
            if (
                abs(invoice["cg"] - expected_cgst) > 0.01
                or abs(invoice["sg"] - (tax - expected_cgst)) > 0.01
                or invoice["ig"] != 0
            ):
                return False
        elif invoice["cg"] != 0 or invoice["sg"] != 0 or abs(invoice["ig"] - tax) > 0.01:
            return False
        if any(
            not isinstance(payment, dict)
            or not text(payment.get("d"))
            or not number(payment.get("a"), 0.000001)
            or not text(payment.get("m"))
            for payment in invoice["pd"]
        ):
            return False
        if sum(payment["a"] for payment in invoice["pd"]) > invoice["tot"] + 0.01:
            return False

    invoiced_orders = set(invoice_orders)
    if any(
        (order["st"] == "Invoiced") != (order["id"] in invoiced_orders)
        for order in orders
    ):
        return False

    stock_names = {material["n"] for material in materials.values()}
    stock_names.update(product["n"] for product in products.values())
    if any(
        not isinstance(entry, dict)
        or not text(entry.get("d"))
        or entry.get("i") not in stock_names
        or not text(entry.get("k"))
        or not isinstance(entry.get("q"), (int, float))
        or isinstance(entry.get("q"), bool)
        or not math.isfinite(entry.get("q"))
        or not text(entry.get("ref"))
        for entry in ledger
    ):
        return False
    expected_stock = {
        material["n"]: material["s"] for material in materials.values()
    }
    expected_stock.update({product["n"]: product["fg"] for product in products.values()})
    for item_name, current_quantity in expected_stock.items():
        ledger_quantity = sum(
            entry["q"] for entry in ledger if entry["i"] == item_name
        )
        if abs(ledger_quantity - current_quantity) > 0.02:
            return False
    if any(
        not isinstance(run, dict)
        or not text(run.get("id"))
        or not text(run.get("d"))
        or run.get("p") not in products
        or not number(run.get("b"), 0.000001)
        or not number(run.get("good"))
        or not number(run.get("dmg"))
        or not isinstance(run.get("v"), list)
        or any(not text(alert) for alert in run.get("v", []))
        for run in runs
    ):
        return False
    material_names = {material["n"]: key for key, material in materials.items()}
    if any(
        not isinstance(purchase, dict)
        or not text(purchase.get("d"))
        or purchase.get("i") not in material_names
        or not number(purchase.get("q"), 0.000001)
        or not number(purchase.get("r"), 0.000001)
        or not number(purchase.get("v"))
        for purchase in purchases
    ):
        return False
    if any(
        not isinstance(entry, dict)
        or not text(entry.get("t"))
        or not text(entry.get("u"))
        or not text(entry.get("a"))
        for entry in logs
    ):
        return False
    return True


def append_only(previous, current):
    return (
        isinstance(previous, list)
        and isinstance(current, list)
        and len(current) >= len(previous)
        and current[:len(previous)] == previous
    )


def valid_new_logs(previous, current, allowed_actors):
    if not isinstance(previous, list) or not isinstance(current, list) or len(current) < len(previous):
        return False
    if current[len(current) - len(previous):] != previous:
        return False
    added = current[:len(current) - len(previous)] if len(current) >= len(previous) else []
    return all(isinstance(item, dict) and item.get("u") in allowed_actors for item in added)


def authorize_update(previous, current, user):
    role = user["role"]
    immutable_keys = ("M", "P", "C", "O", "I", "L", "R", "PU", "LG", "seq")

    if role == "Salesman":
        if any(previous[key] != current[key] for key in ("M", "P", "I", "L", "R", "PU")):
            return False
        if not append_only(previous["C"], current["C"]) or not append_only(previous["O"], current["O"]):
            return False
        additions = current["O"][len(previous["O"]):]
        if any(order.get("by") != user["name"] or order.get("st") != "Submitted" for order in additions):
            return False
        return (
            current["seq"] == previous["seq"] + len(additions)
            and valid_new_logs(previous["LG"], current["LG"], {user["name"], role})
        )

    if role == "Factory admin":
        if any(previous[key] != current[key] for key in ("M", "R", "PU")):
            return False
        if current["seq"] != previous["seq"] or not append_only(previous["C"], current["C"]):
            return False
        old_orders = {item["id"]: item for item in previous["O"]}
        if len(current["O"]) != len(previous["O"]):
            return False
        allowed_status = {
            "Submitted": {"Submitted", "Approved", "Rejected"},
            "Approved": {"Approved", "Invoiced"},
            "Invoiced": {"Invoiced"},
            "Rejected": {"Rejected"},
        }
        for order in current["O"]:
            old = old_orders.get(order.get("id"))
            if not old or any(old.get(key) != value for key, value in order.items() if key != "st"):
                return False
            if order.get("st") not in allowed_status.get(old.get("st"), set()):
                return False
        if len(current["I"]) < len(previous["I"]):
            return False
        for old, new in zip(previous["I"], current["I"]):
            if any(old.get(key) != value for key, value in new.items() if key not in ("pd", "disp")):
                return False
            if not append_only(old.get("pd", []), new.get("pd", [])):
                return False
            if old.get("disp") and not new.get("disp"):
                return False
            if not isinstance(new.get("disp"), bool):
                return False
            if any(
                not isinstance(payment, dict)
                or not isinstance(payment.get("a"), (int, float))
                or payment["a"] <= 0
                for payment in new.get("pd", [])
            ):
                return False
            if sum(payment["a"] for payment in new["pd"]) > new.get("tot", 0) + 0.01:
                return False
        additions = current["I"][len(previous["I"]):]
        if any(not isinstance(invoice, dict) or invoice.get("aud") for invoice in additions):
            return False
        old_products, new_products = previous["P"], current["P"]
        if set(old_products) != set(new_products):
            return False
        expected_sales = {}
        old_invoice_numbers = {invoice.get("no") for invoice in previous["I"]}
        old_order_map = {order["id"]: order for order in previous["O"]}
        for invoice in additions:
            order = old_order_map.get(invoice.get("o"))
            if not order or order.get("st") != "Approved" or invoice.get("no") in old_invoice_numbers:
                return False
            taxable = sum(
                quantity * old_products[key]["pr"]
                for key, quantity in order.get("l", {}).items()
                if key in old_products
            )
            if len(order.get("l", {})) == 0 or any(key not in old_products for key in order.get("l", {})):
                return False
            if abs(invoice.get("tx", -1) - taxable) > 0.01:
                return False
            expected_tax = taxable * 0.05
            if abs(invoice.get("tot", -1) - taxable - expected_tax) > 0.01:
                return False
            customer = next((item for item in previous["C"] if item.get("id") == order.get("c")), None)
            if not customer:
                return False
            if customer.get("st") == "Tamil Nadu":
                if abs(invoice.get("cg", -1) - expected_tax / 2) > 0.01 or abs(invoice.get("sg", -1) - expected_tax / 2) > 0.01 or invoice.get("ig") != 0:
                    return False
            elif abs(invoice.get("ig", -1) - expected_tax) > 0.01 or invoice.get("cg") != 0 or invoice.get("sg") != 0:
                return False
            for key, quantity in order["l"].items():
                expected_sales[key] = expected_sales.get(key, 0) + quantity
        for key, old in old_products.items():
            new = new_products[key]
            if any(old.get(field) != value for field, value in new.items() if field != "fg"):
                return False
            expected_fg = old.get("fg", 0) - expected_sales.get(key, 0)
            if new.get("fg") != expected_fg:
                return False
        for order in current["O"]:
            old = old_orders[order["id"]]
            if old["st"] == "Approved" and order["st"] == "Invoiced":
                if not any(invoice.get("o") == order["id"] for invoice in additions):
                    return False
        return (
            append_only(previous["L"], current["L"])
            and valid_new_logs(previous["LG"], current["LG"], {role})
        )

    if role == "Supervisor":
        if any(previous[key] != current[key] for key in ("C", "O", "I")):
            return False
        if current["seq"] != previous["seq"] or not append_only(previous["PU"], current["PU"]):
            return False
        if set(previous["M"]) != set(current["M"]) or set(previous["P"]) != set(current["P"]):
            return False
        for key, old in previous["M"].items():
            new = current["M"][key]
            if any(old.get(field) != value for field, value in new.items() if field not in ("s", "r")):
                return False
            if new.get("s", -1) < 0 or new.get("r", -1) <= 0:
                return False
        for key, old in previous["P"].items():
            new = current["P"][key]
            if any(old.get(field) != value for field, value in new.items() if field != "fg"):
                return False
            if new.get("fg", -1) < 0:
                return False
        return (
            append_only(previous["R"], current["R"])
            and append_only(previous["L"], current["L"])
            and valid_new_logs(previous["LG"], current["LG"], {role})
        )

    if role == "Auditor":
        if any(previous[key] != current[key] for key in ("M", "P", "C", "O", "L", "R", "PU", "seq")):
            return False
        if len(previous["I"]) != len(current["I"]):
            return False
        for old, new in zip(previous["I"], current["I"]):
            if any(old.get(key) != value for key, value in new.items() if key != "aud"):
                return False
            if old.get("aud") and not new.get("aud"):
                return False
            if not isinstance(new.get("aud"), bool):
                return False
        return valid_new_logs(previous["LG"], current["LG"], {role})

    if role == "Owner":
        return all(previous[key] == current[key] for key in immutable_keys)
    return False


class ThreadHandler(BaseHTTPRequestHandler):
    server_version = "SMC/1.0"

    def log_message(self, format_string, *args):
        print("%s - %s" % (self.address_string(), format_string % args))

    def send_json(self, status, payload, headers=None):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def fail(self, status, message):
        self.send_json(status, {"error": message})

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request body length.") from error
        if length > MAX_BODY_BYTES:
            raise OverflowError("Request body is too large.")
        raw = self.rfile.read(length)
        try:
            result = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(result, dict):
            raise ValueError("Request body must be a JSON object.")
        return result

    def cookie_token(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookies.get("smc_session")
        return morsel.value if morsel else ""

    def current_user(self):
        token = self.cookie_token()
        now = time.time()
        with SESSION_LOCK:
            session = SESSIONS.get(token)
            if not session:
                return None
            if session["expires_at"] <= now:
                SESSIONS.pop(token, None)
                return None
            session["expires_at"] = now + SESSION_TTL
            return {"token": token, "name": session["name"], "role": session["role"]}

    def require_user(self):
        user = self.current_user()
        if not user:
            self.fail(401, "Please sign in again.")
        return user

    def check_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            return urlsplit(origin).netloc == self.headers.get("Host", "")
        except ValueError:
            return False

    def api_request(self, method, path):
        if method in ("POST", "PUT", "DELETE") and not self.check_origin():
            self.fail(403, "Cross-origin requests are not allowed.")
            return

        if method == "GET" and path == "/api/health":
            self.send_json(200, {"ok": True, "service": "smart-manufacturer-centre-api"})
            return

        if method == "GET" and path == "/api/session":
            user = self.current_user()
            self.send_json(
                200,
                {"user": {"name": user["name"], "role": user["role"]} if user else None},
            )
            return

        if method == "POST" and path == "/api/login":
            self.login()
            return

        if method == "POST" and path == "/api/logout":
            user = self.current_user()
            if user:
                with SESSION_LOCK:
                    SESSIONS.pop(user["token"], None)
            self.send_json(
                200,
                {"ok": True},
                {"Set-Cookie": "smc_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"},
            )
            return

        user = self.require_user()
        if not user:
            return

        if method == "GET" and path == "/api/state":
            with closing(connect_db()) as connection:
                state, revision = load_state(connection)
                self.send_json(200, {"state": state, "revision": revision})
            return

        if method == "POST" and path == "/api/bootstrap":
            body = self.read_body()
            if not valid_state(body.get("state")):
                self.fail(400, "The initial business data is incomplete or invalid.")
                return
            payload = json.dumps(body["state"], ensure_ascii=False)
            with closing(connect_db()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                state, _ = load_state(connection)
                if state:
                    connection.rollback()
                    self.fail(409, "The business data has already been initialized.")
                    return
                persist_state(connection, body["state"])
                connection.execute(
                    "UPDATE business_meta SET revision = 1, updated_at = datetime('now') WHERE id = 1"
                )
                connection.execute(
                    "INSERT OR REPLACE INTO benchmark_state (id, payload) VALUES (1, ?)",
                    (payload,),
                )
                connection.commit()
            self.send_json(201, {"revision": 1})
            return

        if method == "PUT" and path == "/api/state":
            body = self.read_body()
            state = body.get("state")
            revision = body.get("revision")
            if not valid_state(state) or not isinstance(revision, int) or isinstance(revision, bool):
                self.fail(400, "The business data or revision is invalid.")
                return
            with closing(connect_db()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                previous, current_revision = load_state(connection)
                if previous is None:
                    connection.rollback()
                    self.fail(409, "Business data has not been initialized.")
                    return
                if current_revision != revision:
                    connection.rollback()
                    self.fail(
                        409,
                        "Business data changed in another session. Reload to avoid overwriting it.",
                    )
                    return
                try:
                    authorized = authorize_update(previous, state, user)
                except (KeyError, TypeError, ValueError, OverflowError):
                    authorized = False
                if not authorized:
                    connection.rollback()
                    self.fail(403, f"{user['role']} is not allowed to make that change.")
                    return
                persist_state(connection, state)
                connection.execute(
                    "UPDATE business_meta SET revision = revision + 1, updated_at = datetime('now') "
                    "WHERE id = 1"
                )
                connection.commit()
            self.send_json(200, {"revision": revision + 1})
            return

        if method == "POST" and path == "/api/reset":
            if user["role"] != "Owner":
                self.fail(403, "Only the owner can reset the demo data.")
                return
            with closing(connect_db()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                baseline = connection.execute(
                    "SELECT payload FROM benchmark_state WHERE id = 1"
                ).fetchone()
                state, revision = load_state(connection)
                if not baseline or state is None:
                    connection.rollback()
                    self.fail(409, "Benchmark data has not been initialized.")
                    return
                baseline_state = json.loads(baseline["payload"])
                persist_state(connection, baseline_state)
                connection.execute(
                    "UPDATE business_meta SET revision = ?, updated_at = datetime('now') WHERE id = 1",
                    (revision + 1,),
                )
                connection.commit()
                restored, restored_revision = load_state(connection)
            self.send_json(
                200,
                {"state": restored, "revision": restored_revision},
            )
            return

        self.fail(404, "API route not found.")

    def login(self):
        address = self.client_address[0]
        now = time.time()
        with FAILURE_LOCK:
            failure = LOGIN_FAILURES.get(address, {"count": 0, "until": 0})
            if failure["until"] > now:
                self.fail(429, "Too many sign-in attempts. Try again in 15 minutes.")
                return
        body = self.read_body()
        name = body.get("name")
        password = body.get("password")
        role = USERS.get(name)
        if not role or not secrets.compare_digest(str(password or ""), DEMO_PASSWORD):
            with FAILURE_LOCK:
                failure["count"] += 1
                failure["until"] = now + 15 * 60 if failure["count"] >= 5 else 0
                LOGIN_FAILURES[address] = failure
            self.fail(401, "Invalid user or password.")
            return
        with FAILURE_LOCK:
            LOGIN_FAILURES.pop(address, None)
        token = secrets.token_urlsafe(32)
        with SESSION_LOCK:
            SESSIONS[token] = {
                "name": name,
                "role": role,
                "expires_at": now + SESSION_TTL,
            }
        self.send_json(
            200,
            {"user": {"name": name, "role": role}},
            {
                "Set-Cookie": (
                    f"smc_session={token}; HttpOnly; SameSite=Lax; Path=/; "
                    f"Max-Age={SESSION_TTL}"
                )
            },
        )

    def serve_static(self, request_path, head_only=False):
        decoded = unquote(request_path)
        if decoded == "/":
            decoded = "/index.html"
        if decoded not in PUBLIC_ASSETS:
            self.send_error(404)
            return
        requested = (FRONTEND / decoded.lstrip("/")).resolve()
        try:
            requested.relative_to(FRONTEND)
        except ValueError:
            self.send_error(404)
            return
        if not requested.is_file():
            self.send_error(404)
            return
        content_type = {
            ".css": "text/css; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(requested.suffix.lower(), "application/octet-stream")
        content = requested.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head_only:
            self.wfile.write(content)

    def dispatch(self, method):
        parsed = urlsplit(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self.api_request(method, parsed.path)
            elif method in ("GET", "HEAD"):
                self.serve_static(parsed.path, head_only=(method == "HEAD"))
            else:
                self.send_error(405, "Method not allowed.")
        except (ValueError, OverflowError) as error:
            self.fail(413 if isinstance(error, OverflowError) else 400, str(error))
        except sqlite3.Error:
            logging.exception("SQLite request failed")
            if not self.wfile.closed:
                self.fail(500, "The database could not complete the request.")
        except Exception:
            logging.exception("Unhandled request error")
            if not self.wfile.closed:
                self.fail(500, "The server could not complete the request.")

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("HEAD")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")


if __name__ == "__main__":
    initialize_db()
    print(f"Smart Manufacturer Centre is running at http://{HOST}:{PORT}")
    print(f"Demo users share the configured demo password (default: {DEMO_PASSWORD}).")
    try:
        ThreadingHTTPServer((HOST, PORT), ThreadHandler).serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
