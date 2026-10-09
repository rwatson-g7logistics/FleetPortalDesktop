# FleetPortalDesktop (FPD) — G7 Fleet Command Center

Native cross-platform desktop management workstation built with Python and PySide6 (Qt). Designed to manage fleet asset health, scheduled PM services, parts inventory, compliance tracking, and documentation across multi-user environments with local SQLite caching and asynchronous Google Workspace synchronization.

---

## Architecture & System Design
FleetPortalDesktop/
├── app.py                      # Application entry point, QMainWindow, navigation & view stack
├── config.py                   # Global constants, file paths, Google Workspace IDs, styles
├── db_manager.py               # Local SQLite caching layer & schema migrations
├── cloud_sync.py               # Asynchronous QThread background worker for Google Sheets
├── requirements.txt            # Runtime dependencies
├── data/
│   └── fleet_portal_cache.db   # Local persistent SQLite database cache
├── views/
│   ├── fleet_view.py           # Fleet Command table, filters, inline mileage & QR export
│   ├── vehicle_profile.py      # Unit profile, compliance inspection hub & history log
│   ├── service_view.py         # Service log form, tire position tracker & PDF compiler
│   ├── inventory_view.py       # Parts/tires inventory ledger & inline quantity controls
│   ├── cost_center.py          # Financial ledger, vendor filtering & expense routing
│   └── document_center.py      # Operations SOPs, lot maps, checklists & Drive upload UI
└── utils/
├── platform_helper.py      # Native OS directory resolution & system typography
├── qr_helper.py            # VIN sanitization, 4x4 QR PDF generation & Drive upload
├── pdf_builder.py          # Service report HTML-to-PDF compiler with HEIC image support
└── pave.py                 # PAVE inspection image conversion to standardized PDF

---

## Core Capabilities

* **Offline-First Hybrid Architecture:** Direct UI read/write operations execute against a local SQLite cache (`fleet_portal_cache.db`), eliminating UI lag and preventing Google Sheets API quota saturation (HTTP 429).
* **Asynchronous Cloud Sync:** Non-blocking `QThread` workers execute bi-directional synchronization with upstream Google Sheets (`MasterSheet`).
* **Compliance & Decay Monitoring:** Real-time calculation of rental unit return windows (U-Haul, Budget, Enterprise), PAVE inspections, and 30-day registration/insurance expirations with color-coded status badges.
* **Automated Stock Depletion:** Logging vehicle service records automatically deducts matching tire specs and replacement wear items (wipers, bulbs, fluids) from the parts inventory.
* **Document Compilation & Image Compression:** Form data and attached vendor invoices (supporting Apple HEIC format via `pillow-heif`) compile into single standardized PDF reports.
* **VIN QR Engine:** Sanitizes 17-character VINs (stripping invalid check characters `I`, `O`, `Q` and whitespace) and compiles print-ready 4x4 label sheets uploaded directly to Google Drive.

---

## Installation & Setup

### 1. Prerequisites
* Python 3.9+
* Operating System: Windows 10/11 or macOS 12+

### 2. Environment Setup

# Clone or locate the repository directory
cd FleetPortalDesktop

# Create and activate virtual environment
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows (Command Prompt)
venv\Scripts\activate.bat

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

### 3. Google Workspace Credentials
Place your authorized Google OAuth client credentials file at the project root:

FleetPortalDesktop/token.json

Required OAuth Scopes:

https://www.googleapis.com/auth/spreadsheets

https://www.googleapis.com/auth/drive

https://www.googleapis.com/auth/documents

### 4. Running the Application
python app.py

* Database Schema (Local Cache)
* * master_vehicles: Primary fleet records indexed by vehicle_id, tracking specifications, PM mileage deltas (last_a_service), camera installations, and compliance dates.

* * service_logs: Detailed repair events, parts costs, vendor assignments, invoice numbers, and tire position strings (DF, PF, DR, PR).

* * inventory: Warehouse consumables and tire stock with reorder threshold triggers.

* * vendors: Approved internal and external repair vendors.


---

### Critical Codebase Issues Identified During Ingestion

Auditing the dropped files against `data/fleet_portal_cache.db` revealed several critical blockers preventing the app from launching or saving data:

#### 1. Schema Primary Key Conflict (`vehicle_id` vs `unit_id`)
* **Problem:** In the provided SQLite file `fleet_portal_cache.db`, the table definition is `master_vehicles(vehicle_id TEXT PRIMARY KEY, ...)`[cite: 17]. However, `db_manager.py` defines `CREATE TABLE master_vehicles(unit_id TEXT PRIMARY KEY, ...)`[cite: 5] and attempts `INSERT INTO master_vehicles (unit_id, ...)`[cite: 5]. 
* **Impact:** Any query expecting `vehicle_id` (e.g., `fleet_view.py`[cite: 9], `vehicle_profile.py`[cite: 12], `cloud_sync.py`[cite: 3]) either fails with `no such column: vehicle_id` or returns empty fields.

#### 2. SQL Column Count Mismatch in `db_manager.py`
* **Problem:** In `DatabaseManager.save_vehicles_bulk`:
  * Columns specified: 19 columns (`unit_id`, `provider`, `status`, `restrictions`, `location`, `camera_status`, `make`, `model`, `year`, `vin`, `plate`, `state`, `mileage`, `pave_insp`, `registration`, `insurance`, `size`, `service_interval`, `return_date`)[cite: 5].
  * Value placeholders provided: 18 (`VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)[cite: 5].
* **Impact:** `sqlite3.OperationalError` triggers immediately whenever `SyncWorker` attempts to cache vehicles locally[cite: 3, 5].

#### 3. Uninstantiated Widgets & NameErrors in `AddUnitDialog` (`fleet_view.py`)
* **Problem:** 
  * `AddUnitDialog.init_ui()` references `self.txt_year`, `self.txt_reg`, `self.txt_ins`, `self.txt_ret`, and `self.txt_pave` without initializing them as `QLineEdit` instances[cite: 9].
  * `save_unit()` references an undefined variable `unit_id` (the input was assigned to `uid`)[cite: 9].
  * `save_unit()` calls `self.db.save_vehicles_bulk(new_unit_df)` without defining `new_unit_df`[cite: 9].
* **Impact:** Opening the "Add Unit" dialog crashes the UI with `AttributeError`; attempting to save crashes with `NameError`[cite: 9].

#### 4. Missing Method in `db_manager.py`
* **Problem:** `ServiceFormView.populate_vendors()` calls `self.db.get_vendor_list()`[cite: 11], but `DatabaseManager` does not implement `get_vendor_list()`[cite: 5].
* **Impact:** Launching the service log view crashes with `AttributeError: 'DatabaseManager' object has no attribute 'get_vendor_list'`.

---

### Immediate Execution Verification Checklist

1. **Normalize SQLite Schema & Cache Layer:** Standardize `db_manager.py` column references to `vehicle_id` across all queries to maintain 1:1 parity with `fleet_portal_cache.db`[cite: 5, 17].
2. **Patch SQL Parameter Counts:** Align the `INSERT INTO master_vehicles` query in `db_manager.py` so all 19 columns match 19 values and 19 `?` placeholders[cite: 5].
3. **Add `get_vendor_list()` to `DatabaseManager`:** Implement the fetch method returning a flat list of strings from the `vendors` table[cite: 5, 11].
4. **Repair `AddUnitDialog` Widget Declarations:** Instantiate all missing `QLineEdit` controls in `init_ui()` and wrap the payload into a valid single-row `pd.DataFrame` inside `save_unit()`[cite: 9].