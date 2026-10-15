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

## Clone or locate the repository directory

cd FleetPortalDesktop

## Create and activate virtual environment

python -m venv venv

## macOS / Linux

source venv/bin/activate

## Windows (Command Prompt)

venv\Scripts\activate.bat

## Install dependencies

pip install --upgrade pip
pip install -r requirements.txt

### 3. Google Workspace Credentials

Place your authorized Google OAuth client credentials file at the project root:

FleetPortalDesktop/token.json

Required OAuth Scopes:

<https://www.googleapis.com/auth/spreadsheets>

<https://www.googleapis.com/auth/drive>

<https://www.googleapis.com/auth/documents>

### 4. Running the Application

python app.py

* Database Schema (Local Cache)
* * master_vehicles: Primary fleet records indexed by vehicle_id, tracking specifications, PM mileage deltas (last_a_service), camera installations, and compliance dates.

* * service_logs: Detailed repair events, parts costs, vendor assignments, invoice numbers, and tire position strings (DF, PF, DR, PR).

* * inventory: Warehouse consumables and tire stock with reorder threshold triggers.

* * vendors: Approved internal and external repair vendors.

---

### 5. Terminal Command Lines

### 1. Terminal Git Commit & Push

git add .
git commit -m "[placeholder for update comment]"
git push origin main
git status

### 2. Database Administration & CLI Utilities (Temporary)

Use these one-line commands in your terminal to inspect and purge test metadata until UI management dialogs are implemented.

## 1. Provider Lookup Table (`lookup_providers`)

* Inspect Provider List
python -c "from db_manager import DatabaseManager; db = DatabaseManager(); print('Fleet:', db.get_providers('Fleet')); print('Temp:', db.get_providers('Temp'))"
* Scrub Provider List
python -c "from db_manager import DatabaseManager; db = DatabaseManager(); conn = db.get_connection(); conn.cursor().execute(\"DELETE FROM lookup_providers WHERE name IN ('DummyFleet', 'DummyTemp')\"); conn.commit(); print('Cleaned lookup_providers.')"

## 2. Make & Model Lookup Table (lookup_make_models)

* Inspect Registered Makes:
python -c "from db_manager import DatabaseManager; db = DatabaseManager(); print('Makes:', db.get_makes())"
* Inspect Models for a Specific Make:
python -c "from db_manager import DatabaseManager; db = DatabaseManager(); print('RAM Models:', db.get_models_for_make('RAM'))"
* Purge Specific Test Make/Model Combinations:
python -c "from db_manager import DatabaseManager; db = DatabaseManager(); conn = db.get_connection(); conn.cursor().execute(\"DELETE FROM lookup_make_models WHERE make = 'TestMake' AND model = 'TestModel'\"); conn.commit(); print('Cleaned lookup_make_models.')"

---

## Project Status & Development Roadmap

### Active Modules (Phase 1 — Locked In)
* **Fleet Command Center (`views/fleet_view.py`):** Multi-variable search, dynamic status filtering, intake validation (17-char VIN, duplicate safeguards, leading-zero lockout), inline odometer editing with immediate cloud write-through, and compliance decay warnings.
* **Cloud & Persistence Engine (`cloud_sync.py`, `db_manager.py`):** Bidirectional sync between SQLite cache and Google Sheets (`FPD_Master_Sheet` and `FPD_Retired_Sheet`), in-place Google Drive file updating, and PAVE document routing.
* **Label & QR Automation (`utils/qr_helper.py`):** Consolidated 24-up label generator (1.4" × 1.4" badges, 4 columns) outputting to `Master_Fleet_QR_Labels.pdf` and synced to Drive.

### Target Milestone (Year-End Target / Pre-Peak Stability)
- [ ] **Modular Deep Dive Hub (`views/vehicle_profile.py`):** Decouple layout into `utils/profile_card_builder.py`, direct PAVE / invoice PDF launch, and single-unit lifetime maintenance ledger export.
- [ ] **Service Reporting Engine (`views/service_view.py`):** Standardize balanced 6-item service selector, diagnostic logging, tire position tracking, and auto-inventory deduction.
- [ ] **Access & Security:** Role-based retirement signature auditing and idle session auto-lock.

---