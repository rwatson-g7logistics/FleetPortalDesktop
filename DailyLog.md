# EOD Logger

## Pending Next Sprints

- [ ] User session timeout and role-based signature verification.
- [ ] Decouple `views/vehicle_profile.py` layout into `utils/profile_card_builder.py`.
- [ ] Streamline `views/service_view.py` to route invoice attachments into `Unit Records / <vehicle_id> / Invoices`.

## End of Day (EOD) Build Summary — October 16, 2026

### Completed Milestones

* **Dynamic Provider SOP Engine (`utils/provider_sop.py`, `db_manager.py`):**
  * Decoupled hardcoded maintenance intervals into a customizable SQLite lookup table (`lookup_provider_sops`).
  * Built `ProviderSOPEditDialog` modal accessible from the Fleet Overview header ("⚙️ Provider SOPs") to adjust PM intervals, tire reimbursement targets, alert windows, and brake inspection cycles per vendor on the fly.
  * Added `get_provider_sop()` with alias normalization (`AMZN` vs `Amazon`, `U-Haul` vs `UHaul`) to prevent unlisted vendor fallbacks.
  * Implemented project-wide standard `auto_size_combobox` helper in `utils/platform_helper.py` using Qt font metrics to dynamically size dropdown widths to the longest string without text clipping.
* **Fleet Overview Dashboard & Telemetry (`views/fleet_view.py`):**
  * Rebranded "Fleet Command Center" to "📊 Fleet Overview" across header titles and sidebar navigation.
  * Built live KPI telemetry banner calculating real-time ratios: Fleet Health (Active/Total ratio and percentage), Camera Compliance (Installed/Active percentage), and Active Rental counts.
  * Locked table inline editing triggers (`NoEditTriggers`), enforcing modal-only odometer adjustments.
* **4-Corner Service Status Hub & Wear Tracking (`views/unit_service_view.py`, `utils/service_tracker.py`):**
  * Routed Column 7 (Service Status) single-click to a dedicated `UnitServiceView` hub.
  * Built 2×2 physical wheel position layout ("🛞 Tire Wear & Provider SOP Matrix") tracking individual corners (DF, PF, DR, PR) for both Provider SOP reimbursement mileage and physical tread wear depth ($32\text{nds}$).
  * Created `TireInspectionDialog` on individual tire cards supporting direct yard tread audits and single-tire replacements with automatic shop inventory deduction.
  * Built `BrakeInspectionDialog` and created `utils/telemetry_sync.py` with `link_brake_spinboxes()` to provide non-recursive, two-way bi-directional synchronization between pad millimeters ($mm$) and usable wear percentage ($\%$).
  * Integrated multi-point milestone monitoring for Engine Oil, Brake friction/rotors, and Chassis Alignment with datestamps and invoice numbers.
* **Unified Compliance & Document Enforcement (`utils/rental_lifecycle.py`, `cloud_sync.py`):**
  * Upgraded `ExtendRentalDialog` into a comprehensive Compliance & Expiration Manager handling Registration, Insurance, and Return Date simultaneously across all units (Fleet and Temp).
  * Enforced mandatory document attachments when adding or updating any expiration date, blocking date changes without supporting paperwork.
  * Eliminated duplicate form rows and locked dialog geometry to an optimized 5-field layout.
* **Self-Healing Cloud Sync & Drive Hierarchy (`cloud_sync.py`, `app.py`):**
  * Built `upload_unit_file_to_drive_sync()` to organize vehicle documentation into isolated Google Drive folders: `Unit Records / <vehicle_id> / <sub_category>` (`Compliance`, `Invoices`, `PAVE`).
  * Implemented self-healing sheet reconciliation (`push_unsynced_vehicles_to_cloud()` and activated `PushWorker`), automatically pushing offline-created vehicles to `FPD_Master_Sheet` on reconnect and protecting local cache during cloud pulls.
  * Resolved silent OAuth failures: added `RefreshError` handling to purge stale `token.json` files and forced explicit `prompt='consent'` to ensure refresh tokens are issued on re-authentication.
  * Bound startup sidebar connection badges strictly to verified OAuth session validity.
* **Deep Dive & Cost Center Integration (`views/vehicle_profile.py`, `views/service_view.py`):**
  * Aligned Deep Dive PM countdown calculations directly to the active vendor's dynamic SOP interval.
  * Added "📄 Service Ledger" header action compiling lifetime maintenance records into an isolated PDF report via `utils/pdf_builder.py`.
  * Added `Payment Route` selector ("Provider", "Out of Pocket", "Insurance") to `ServiceFormView` and updated `save_service_record()` to persist payment routes to SQLite for accurate `CostCenterView` filtering.

## End of Day (EOD) Build Summary — October 14, 2026

### Completed Milestones - October 14

* **Data Intake Safeguards & Integrity (`views/fleet_view.py`):**
  * Enforced strict 17-character VIN requirement with character limit and validation block.
  * Implemented duplicate entry safeguards preventing duplicate Unit ID under the same provider, duplicate VIN, and duplicate License Plate across the fleet.
  * Added Intake Mileage spinbox, saving starting odometer directly to SQLite and Google Sheets Column M.
  * Layered calendar picker with `ApplicationModal` and `WindowStaysOnTopHint` to prevent popup occlusion on macOS and Windows dialogs.
* **Retirement Engine & Lifecycle Synchronization (`cloud_sync.py` & `views/vehicle_profile.py`):**
  * Locked down canonical 14-column header schema for `FPD_Retired_Sheet` with auto-alignment to eliminate column shift.
  * Integrated `Camera_Uninstalled` (Yes/No) status and PAVE outtake upload into the retirement payload.
  * Built `ExtendRentalDialog` and `restore_unit_from_retirement()` to allow one-click rental extension or full cloud restoration of auto-retired units back to active fleet status.
  * Standardized return date decay flags (`⚠️ 2-3d Left`, `🚨 Due Tomorrow`, `🚨 Return Due Today`) across all units.
* **Real-Time Odometer Sync (`cloud_sync.py`):**
  * Added `update_cloud_vehicle_mileage()` to immediately push inline mileage edits to Column M in `FPD_Master_Sheet`, preventing subsequent cloud refreshes from overwriting local changes.
* **Unified Master QR Label Engine (`utils/qr_helper.py`):**
  * Replaced multi-file generation with consolidated `Master_Fleet_QR_Labels.pdf`.
  * Standardized layout to 4-across (24 labels per sheet) sized at 1.4" × 1.4" with centered Unit ID, scannable QR matrix, and 17-character VIN footer.
  * Upgraded Google Drive sync to overwrite files in-place using `service.files().update()` to eliminate duplicate file sprawl.
  * Resolved Qt rich-text integer parsing warning (`6pt` integer font size).

## End of Day (EOD) Build Summary — October 9, 2026

### Completed Milestones — October 9

* **Cloud Sheet Architecture & Schema Trim:**
  * Standardized `FPD_Master_Sheet` Column A to store display `Unit_ID` (e.g., `1`) while retaining compound `vehicle_id` (`provider_unitid`) internally for SQLite primary key operations.
  * Renamed target retirement archive to `FPD_Retired_Sheet`.
  * Consolidated retirement columns: combined Unit ID and Provider into single Column A (`Vehicle_ID`), trimming redundant headers.
  * Added `Camera_Uninstalled` (Yes/No) operational tracking field to `RetireUnitDialog` and cloud output schema.
* **Intake & Caching Engine:**
  * Restricted vehicle identifiers from starting with `0` to prevent spreadsheet numeric truncation bugs.
  * Synchronized dynamic Provider (`Fleet` vs `Temp`) and Make/Model lookup tables.
  * Wired live status telemetry progress bar and non-blocking background sync loop.
