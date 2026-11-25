"""Normalized SQLite storage and migration helpers for the manufacturer system."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / "data" / "thread.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS business_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL,
    order_sequence INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS materials (
    material_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity_on_hand REAL NOT NULL,
    unit_cost REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    product_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    selling_price REAL NOT NULL,
    finished_quantity REAL NOT NULL,
    labour_cost REAL NOT NULL,
    overhead_cost REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bill_of_materials (
    product_key TEXT NOT NULL REFERENCES products(product_key) ON DELETE CASCADE,
    material_key TEXT NOT NULL REFERENCES materials(material_key),
    quantity_per_batch REAL NOT NULL,
    PRIMARY KEY (product_key, material_key)
);
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sales_orders (
    order_id TEXT PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    salesman TEXT NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Submitted', 'Approved', 'Rejected', 'Invoiced'))
);
CREATE TABLE IF NOT EXISTS sales_order_lines (
    order_id TEXT NOT NULL REFERENCES sales_orders(order_id) ON DELETE CASCADE,
    product_key TEXT NOT NULL REFERENCES products(product_key),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, product_key)
);
CREATE TABLE IF NOT EXISTS invoices (
    invoice_number TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES sales_orders(order_id),
    invoice_date TEXT NOT NULL,
    taxable_amount REAL NOT NULL,
    cgst REAL NOT NULL,
    sgst REAL NOT NULL,
    igst REAL NOT NULL,
    total_amount REAL NOT NULL,
    dispatched INTEGER NOT NULL CHECK (dispatched IN (0, 1)),
    audited INTEGER NOT NULL CHECK (audited IN (0, 1))
);
CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY,
    invoice_number TEXT NOT NULL REFERENCES invoices(invoice_number) ON DELETE CASCADE,
    payment_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    method TEXT NOT NULL,
    entry_order INTEGER NOT NULL,
    UNIQUE (invoice_number, entry_order)
);
CREATE TABLE IF NOT EXISTS stock_ledger (
    ledger_id INTEGER PRIMARY KEY,
    entry_date TEXT NOT NULL,
    item_name TEXT NOT NULL,
    movement TEXT NOT NULL,
    quantity REAL NOT NULL,
    reference TEXT NOT NULL,
    entry_order INTEGER NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS production_runs (
    run_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    product_key TEXT NOT NULL REFERENCES products(product_key),
    batches REAL NOT NULL,
    good_packets REAL NOT NULL,
    damaged_packets REAL NOT NULL,
    variance_alerts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchases (
    purchase_id INTEGER PRIMARY KEY,
    purchase_date TEXT NOT NULL,
    material_key TEXT NOT NULL REFERENCES materials(material_key),
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL,
    total_cost REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY,
    event_time TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entry_order INTEGER NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS benchmark_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_customer_date ON sales_orders(customer_id, order_date);
CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_payments_invoice_date ON payments(invoice_number, payment_date);
CREATE INDEX IF NOT EXISTS idx_ledger_item_date ON stock_ledger(item_name, entry_date);
CREATE INDEX IF NOT EXISTS idx_production_date ON production_runs(run_date);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(event_time);
"""


def connect_db(database_path=DATABASE):
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def persist_state(connection, state):
    tables = (
        "payments",
        "invoices",
        "sales_order_lines",
        "sales_orders",
        "bill_of_materials",
        "production_runs",
        "purchases",
        "stock_ledger",
        "audit_log",
        "customers",
        "products",
        "materials",
    )
    for table in tables:
        connection.execute(f"DELETE FROM {table}")

    connection.executemany(
        "INSERT INTO materials VALUES (?, ?, ?, ?, ?)",
        [
            (key, material["n"], material["u"], material["s"], material["r"])
            for key, material in state["M"].items()
        ],
    )
    connection.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
        [
            (key, product["n"], product["pr"], product["fg"], product["lab"], product["ovh"])
            for key, product in state["P"].items()
        ],
    )
    connection.executemany(
        "INSERT INTO bill_of_materials VALUES (?, ?, ?)",
        [
            (product_key, material_key, quantity)
            for product_key, product in state["P"].items()
            for material_key, quantity in product["bom"].items()
        ],
    )
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?, ?)",
        [(customer["id"], customer["n"], customer["st"]) for customer in state["C"]],
    )
    connection.executemany(
        "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?)",
        [
            (order["id"], order["c"], order["by"], order["d"], order["st"])
            for order in state["O"]
        ],
    )
    connection.executemany(
        "INSERT INTO sales_order_lines VALUES (?, ?, ?)",
        [
            (order["id"], product_key, quantity)
            for order in state["O"]
            for product_key, quantity in order["l"].items()
        ],
    )
    connection.executemany(
        "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                invoice["no"],
                invoice["o"],
                invoice["d"],
                invoice["tx"],
                invoice["cg"],
                invoice["sg"],
                invoice["ig"],
                invoice["tot"],
                int(invoice["disp"]),
                int(invoice["aud"]),
            )
            for invoice in state["I"]
        ],
    )
    connection.executemany(
        "INSERT INTO payments (invoice_number, payment_date, amount, method, entry_order) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (invoice["no"], payment["d"], payment["a"], payment["m"], index)
            for invoice in state["I"]
            for index, payment in enumerate(invoice["pd"])
        ],
    )
    connection.executemany(
        "INSERT INTO stock_ledger (entry_date, item_name, movement, quantity, reference, entry_order) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (entry["d"], entry["i"], entry["k"], entry["q"], entry["ref"], index)
            for index, entry in enumerate(state["L"])
        ],
    )
    connection.executemany(
        "INSERT INTO production_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run["id"],
                run["d"],
                run["p"],
                run["b"],
                run["good"],
                run["dmg"],
                json.dumps(run["v"], ensure_ascii=False),
            )
            for run in state["R"]
        ],
    )
    connection.executemany(
        "INSERT INTO purchases (purchase_date, material_key, quantity, unit_cost, total_cost) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (
                purchase["d"],
                next(key for key, item in state["M"].items() if item["n"] == purchase["i"]),
                purchase["q"],
                purchase["r"],
                purchase["v"],
            )
            for purchase in state["PU"]
        ],
    )
    connection.executemany(
        "INSERT INTO audit_log (event_time, actor, action, entry_order) VALUES (?, ?, ?, ?)",
        [
            (entry["t"], entry["u"], entry["a"], index)
            for index, entry in enumerate(state["LG"])
        ],
    )
    connection.execute(
        "INSERT INTO business_meta (id, revision, order_sequence) VALUES (1, 0, ?) "
        "ON CONFLICT(id) DO UPDATE SET order_sequence = excluded.order_sequence",
        (state["seq"],),
    )


def load_state(connection):
    meta = connection.execute(
        "SELECT revision, order_sequence FROM business_meta WHERE id = 1"
    ).fetchone()
    if not meta or not connection.execute("SELECT 1 FROM materials LIMIT 1").fetchone():
        return None, 0

    state = {
        "M": {},
        "P": {},
        "C": [],
        "O": [],
        "I": [],
        "L": [],
        "R": [],
        "PU": [],
        "LG": [],
        "seq": meta["order_sequence"],
    }
    for row in connection.execute("SELECT * FROM materials ORDER BY rowid"):
        state["M"][row["material_key"]] = {
            "n": row["name"],
            "u": row["unit"],
            "s": row["quantity_on_hand"],
            "r": row["unit_cost"],
        }
    for row in connection.execute("SELECT * FROM products ORDER BY rowid"):
        state["P"][row["product_key"]] = {
            "n": row["name"],
            "pr": row["selling_price"],
            "fg": row["finished_quantity"],
            "lab": row["labour_cost"],
            "ovh": row["overhead_cost"],
            "bom": {},
        }
    for row in connection.execute("SELECT * FROM bill_of_materials ORDER BY rowid"):
        state["P"][row["product_key"]]["bom"][row["material_key"]] = row["quantity_per_batch"]
    state["C"] = [
        {"id": row["customer_id"], "n": row["name"], "st": row["state"]}
        for row in connection.execute("SELECT * FROM customers ORDER BY rowid")
    ]

    orders = {}
    for row in connection.execute("SELECT * FROM sales_orders ORDER BY rowid"):
        order = {
            "id": row["order_id"],
            "c": row["customer_id"],
            "l": {},
            "by": row["salesman"],
            "d": row["order_date"],
            "st": row["status"],
        }
        orders[order["id"]] = order
        state["O"].append(order)
    for row in connection.execute("SELECT * FROM sales_order_lines ORDER BY rowid"):
        orders[row["order_id"]]["l"][row["product_key"]] = row["quantity"]

    invoices = {}
    for row in connection.execute("SELECT * FROM invoices ORDER BY rowid"):
        invoice = {
            "no": row["invoice_number"],
            "o": row["order_id"],
            "d": row["invoice_date"],
            "tx": row["taxable_amount"],
            "cg": row["cgst"],
            "sg": row["sgst"],
            "ig": row["igst"],
            "tot": row["total_amount"],
            "pd": [],
            "disp": bool(row["dispatched"]),
            "aud": bool(row["audited"]),
        }
        invoices[invoice["no"]] = invoice
        state["I"].append(invoice)
    for row in connection.execute("SELECT * FROM payments ORDER BY invoice_number, entry_order"):
        invoices[row["invoice_number"]]["pd"].append(
            {"d": row["payment_date"], "a": row["amount"], "m": row["method"]}
        )

    state["L"] = [
        {"d": row["entry_date"], "i": row["item_name"], "k": row["movement"], "q": row["quantity"], "ref": row["reference"]}
        for row in connection.execute("SELECT * FROM stock_ledger ORDER BY entry_order")
    ]
    state["R"] = [
        {
            "id": row["run_id"],
            "d": row["run_date"],
            "p": row["product_key"],
            "b": row["batches"],
            "good": row["good_packets"],
            "dmg": row["damaged_packets"],
            "v": json.loads(row["variance_alerts"]),
        }
        for row in connection.execute("SELECT * FROM production_runs ORDER BY rowid")
    ]
    state["PU"] = [
        {
            "d": row["purchase_date"],
            "i": row["name"],
            "q": row["quantity"],
            "r": row["unit_cost"],
            "v": row["total_cost"],
        }
        for row in connection.execute(
            "SELECT purchases.*, materials.name FROM purchases "
            "JOIN materials USING (material_key) ORDER BY purchase_id"
        )
    ]
    state["LG"] = [
        {"t": row["event_time"], "u": row["actor"], "a": row["action"]}
        for row in connection.execute("SELECT * FROM audit_log ORDER BY entry_order")
    ]
    return state, meta["revision"]


def initialize_db(database_path=DATABASE):
    with closing(connect_db(database_path)) as connection:
        connection.executescript(SCHEMA)
        existing = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'app_state'"
        ).fetchone()
        meta = connection.execute("SELECT id FROM business_meta WHERE id = 1").fetchone()
        if existing and not meta:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(app_state)")
            }
            if "payload" in columns:
                legacy = connection.execute(
                    "SELECT payload, revision FROM app_state WHERE id = 1"
                ).fetchone()
                if legacy:
                    old_state = json.loads(legacy["payload"])
                    with connection:
                        persist_state(connection, old_state)
                        connection.execute(
                            "UPDATE business_meta SET revision = ? WHERE id = 1",
                            (legacy["revision"],),
                        )
                        connection.execute("DROP TABLE app_state")
        connection.execute(
            "INSERT OR IGNORE INTO business_meta (id, revision, order_sequence) VALUES (1, 0, 1000)"
        )
