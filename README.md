# Smart Manufacturer Centre

<p>
  <strong>A role-based order-to-audit management system for packaged-food manufacturers.</strong>
</p>

Smart Manufacturer Centre is a complete runnable prototype built with Python, SQLite, HTML, CSS, and JavaScript. It covers sales orders, production, inventory, purchasing, GST invoicing, payments, reporting, and audit activity from a single browser interface.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white)
![Frontend](https://img.shields.io/badge/Frontend-HTML%20%7C%20CSS%20%7C%20JavaScript-E34F26)

## Features

- **Role-based workspaces** for Salesman, Factory Admin, Supervisor, Owner, and Auditor
- **Sales lifecycle** with stock checks, order approval/rejection, dispatch, and invoicing
- **GST tax handling** for CGST/SGST and IGST calculations
- **Production management** using bill-of-material consumption, output, wastage, and variances
- **Inventory and purchasing** with purchase receipts and stock-ledger movements
- **Financial tracking** for payments, invoice allocations, receivable ageing, and packet costing
- **Reporting and audit** with monthly filters, activity logs, CSV exports, and print/save-as-PDF output
- **Transactional persistence** with optimistic revisions and normalized SQLite records

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, and browser JavaScript |
| Backend | Python standard-library HTTP server |
| Database | SQLite |
| Authentication | HttpOnly, SameSite cookie sessions |
| Testing | Python `unittest` |

No Java runtime or third-party Python package is required.

## Getting Started

### Prerequisites

- Windows 10 or later
- Python 3.10 or later
- A modern browser such as Microsoft Edge or Google Chrome

Verify Python installation:

```powershell
py -3 --version
```

### Windows Quick Start

From the project folder:

1. Double-click `start.bat`, or run:

   ```powershell
   py -3 -m backend.server
   ```

2. Open [http://127.0.0.1:3000](http://127.0.0.1:3000).
3. Sign in with any demo account below and the default password `demo123`.

| Demo user | Role | Primary responsibility |
|---|---|---|
| Ravi | Salesman | Create orders and collect payments |
| Meena | Factory Admin | Approve orders and manage inventory |
| Karthik | Supervisor | Record production and wastage |
| Subramani | Owner | Review operations and reset demo data |
| Lakshmi | Auditor | Review financial and operational records |

Press `Ctrl+C` in the terminal to stop the server.

### Demo Password Configuration

Set a shared demo password before starting the server:

```powershell
$env:DEMO_PASSWORD = "change-this-demo-password"
py -3 -m backend.server
```

The server also supports custom host and port values:

```powershell
$env:HOST = "127.0.0.1"
$env:PORT = "3000"
py -3 -m backend.server
```

| Variable | Default | Purpose |
|---|---|---|
| `DEMO_PASSWORD` | `demo123` | Shared password for all demo accounts |
| `HOST` | `127.0.0.1` | HTTP server bind address |
| `PORT` | `3000` | HTTP server port |

## Project Structure

```text
Project/
├── backend/
│   ├── server.py           # HTTP server, API routes, authentication, authorization
│   └── database.py         # SQLite schema, persistence, migrations, and queries
├── frontend/
│   ├── index.html          # Application entry point
│   ├── style.css           # Responsive interface styles
│   └── app.js              # State management and API client
├── tests/
│   ├── test_server.py      # API behavior and role authorization
│   └── test_database.py    # Persistence, migration, and integrity
├── data/
│   └── thread.sqlite       # Runtime database; created automatically
├── start.bat               # Windows application launcher
├── .gitignore
└── README.md
```

## Architecture

```text
Browser
  │
  │ HTML, CSS, JavaScript
  ▼
Python HTTP Server
  ├── Static frontend assets
  ├── JSON API
  ├── Session authentication
  ├── Role authorization
  └── Business validation
  ▼
SQLite
  └── Transactional, normalized application data
```

The frontend and backend run on the same origin. API state changes are sent in JSON and persisted in an SQLite transaction. Cross-origin write requests are rejected, and mutations include optimistic revision checks to reduce conflicting updates.

### Database Model

The database organizes application data into relational tables:

- `materials` and `stock_ledger` — raw materials and stock movements
- `products` and `bill_of_materials` — products and material recipes
- `customers`, `sales_orders`, and `sales_order_lines` — customers and order history
- `invoices` and `payments` — tax invoices and payment allocations
- `production_runs` and `purchases` — manufacturing and receipt records
- `audit_log` — recorded user actions
- `business_meta` — order sequence, revision, and update timestamp
- `benchmark_state` — demo reset snapshot

Existing installations are migrated automatically from the earlier JSON snapshot on server startup. Foreign keys, unique constraints, check constraints, indexes, and transaction boundaries protect persisted data.

## API Overview

All API endpoints are served from the same origin as the frontend.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Return service health status |
| `GET` | `/api/session` | Return the current authenticated user |
| `POST` | `/api/login` | Create a demo session |
| `POST` | `/api/logout` | End the current session |
| `GET` | `/api/state` | Load application state |
| `POST` | `/api/bootstrap` | Initialize application state once |
| `PUT` | `/api/state` | Persist authorized state changes |
| `POST` | `/api/reset` | Restore the owner-defined demo snapshot |

Successful state mutations return an incremented revision. A revision conflict returns `409 Conflict`, prompting the client to reload the latest state before retrying.

## Testing

Run the complete test suite from the project directory:

```powershell
py -3 -m unittest discover -s tests -v
```

The tests cover:

- Authentication and API error handling
- Role and operation authorization
- SQLite persistence and normalized round trips
- Legacy snapshot migration
- Database constraints and integrity

## Demo Reset

An Owner can select **Reset demo data** in the sidebar to restore the benchmark snapshot. The reset is available only after the application state has been initialized and the benchmark has been saved.

## Export and Print Behavior

- CSV exports are Excel-compatible `.csv` files, not native `.xlsx` workbooks.
- Invoice and report printing use the browser print dialog.
- PDF output can be created through **Print > Save as PDF**.

## Production Considerations

This repository is a working business prototype, not a production-deployment package. Before real operational use, complete at least the following:

- Replace demo accounts with individually managed credentials
- Use strong password hashing, HTTPS, and persistent server-side sessions
- Replace illustrative GST, HSN, manufacturer, and tax information
- Review tax rules and perform a qualified accounting validation
- Replace broad state replacement with explicit domain commands and validated DTOs
- Add database backups, restore procedures, monitoring, and audit retention
- Add CSRF protections appropriate to the deployed architecture
- Deploy behind a production-grade reverse proxy or web server

## License

No license file is currently included. Add a license before distributing or publishing this project as open source.
