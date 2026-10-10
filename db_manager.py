"""
FleetPortalDesktop/db_manager.py
-------------
SQLite database manager for local data persistence, caching, and HIVE mirror ingestion.
"""

import json
import sqlite3
import pandas as pd

from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from config import DB_PATH

from utils.platform_helper import get_app_data_directory

class DatabaseManager:
    """Manages local SQLite database operations and sync queuing."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = get_app_data_directory() / "data" / "fleet_portal_cache.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()
        self.init_lookup_tables()

    def get_connection(self) -> sqlite3.Connection:
        """Returns a connection instance to the local SQLite database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initializes database tables for local caching and HIVE queue if missing."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS master_vehicles (
                    vehicle_id TEXT PRIMARY KEY,
                    provider TEXT,
                    status TEXT,
                    restrictions TEXT,
                    location TEXT,
                    camera_status TEXT,
                    make TEXT,
                    model TEXT,
                    year TEXT,
                    vin TEXT,
                    plate TEXT,
                    state TEXT,
                    mileage INTEGER,
                    last_a_service INTEGER,
                    last_b_service INTEGER,
                    pave_insp TEXT,
                    registration TEXT,
                    insurance TEXT,
                    last_mile_update TEXT,
                    last_mile_name TEXT,
                    size TEXT,
                    service_interval INTEGER DEFAULT 7500,
                    return_date TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS service_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vehicle_id TEXT,
                    vin TEXT,
                    date TEXT,
                    service_type TEXT,
                    mileage INTEGER,
                    vendor TEXT,
                    invoice_num TEXT,
                    cost REAL,
                    notes TEXT,
                    doc_type TEXT,
                    payment_route TEXT,
                    tire_count INTEGER DEFAULT 0,
                    tire_positions TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT UNIQUE,
                    category TEXT,
                    quantity INTEGER DEFAULT 0,
                    min_threshold INTEGER DEFAULT 2,
                    reorder_link TEXT,
                    notes TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_name TEXT UNIQUE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    target_id TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    synced_at TIMESTAMP
                )
            """)

            conn.commit()

    # --- LOOKUP TABLES FOR PROVIDERS, MAKES, AND MODELS ---
    def init_lookup_tables(self) -> None:
        """Initializes and migrates lookup tables for Providers, Makes, and Models."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 1. Ensure unit_type column exists on master_vehicles
            cursor.execute("PRAGMA table_info(master_vehicles)")
            columns = [row[1] for row in cursor.fetchall()]
            if "unit_type" not in columns:
                cursor.execute("ALTER TABLE master_vehicles ADD COLUMN unit_type TEXT DEFAULT 'Fleet'")
            if "size" not in columns:
                cursor.execute("ALTER TABLE master_vehicles ADD COLUMN size TEXT DEFAULT ''")

            # 2. Providers Lookup Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lookup_providers (
                    name TEXT PRIMARY KEY,
                    provider_type TEXT NOT NULL DEFAULT 'Fleet'
                )
            """)

            # Ensure provider_type column exists if table was previously created without it
            cursor.execute("PRAGMA table_info(lookup_providers)")
            prov_cols = [row[1] for row in cursor.fetchall()]
            if "provider_type" not in prov_cols:
                cursor.execute("ALTER TABLE lookup_providers ADD COLUMN provider_type TEXT DEFAULT 'Fleet'")

            # PURGE LEGACY PREFIXES: Remove old 'Temp-*' records from cache
            cursor.execute("DELETE FROM lookup_providers WHERE name LIKE 'Temp-%'")

            # Clean seed data with strict type separation
            clean_providers = [
                # Fleet Providers (Dedicated / Long-term)
                ("Merchants", "Fleet"),
                ("AMZN", "Fleet"),
                ("Kingbee", "Fleet"),
                # Temp Providers (Rentals / Short-term)
                ("U-Haul", "Temp"),
                ("Budget", "Temp"),
                ("Enterprise", "Temp"),
                ("LMR", "Temp"),
                ("Hertz", "Temp")
            ]
            cursor.executemany(
                "INSERT OR REPLACE INTO lookup_providers (name, provider_type) VALUES (?, ?)",
                clean_providers
            )

            # 3. Cascading Make & Model Lookup Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lookup_vehicle_models (
                    make TEXT NOT NULL,
                    model TEXT NOT NULL,
                    PRIMARY KEY (make, model)
                )
            """)

            # Purge pruned models if previously seeded in local cache
            cursor.execute("""
                DELETE FROM lookup_vehicle_models 
                WHERE (make = 'Chevrolet' AND model IN ('Express 2500', 'Express 3500'))
                   OR (make = 'Rivian' AND model IN ('EDV 500', 'EDV 700'))
            """)

            # Streamlined Delivery Fleet Defaults
            default_vehicles = [
                ("Ford", "Transit 150"),
                ("Ford", "Transit 250"),
                ("Ford", "Transit 350"),
                ("Ford", "E-Transit"),
                ("Ram", "ProMaster 1500"),
                ("Ram", "ProMaster 2500"),
                ("Ram", "ProMaster 3500"),
                ("Mercedes-Benz", "Sprinter 2500"),
                ("Mercedes-Benz", "Sprinter 3500"),
                ("Freightliner", "MT45 Step Van"),
                ("Freightliner", "MT55 Step Van")
            ]
            cursor.executemany(
                "INSERT OR IGNORE INTO lookup_vehicle_models (make, model) VALUES (?, ?)",
                default_vehicles
            )
            conn.commit()

    def get_providers(self, provider_type: Optional[str] = None) -> list:
        """Retrieves registered providers, filtered strictly by provider_type ('Fleet' or 'Temp')."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if provider_type:
                cursor.execute(
                    "SELECT name FROM lookup_providers WHERE provider_type = ? ORDER BY name ASC",
                    (provider_type,)
                )
            else:
                cursor.execute("SELECT name FROM lookup_providers ORDER BY name ASC")
            return [row[0] for row in cursor.fetchall()]

    def add_provider(self, name: str, provider_type: str = "Fleet") -> bool:
        """Adds or updates a provider in the lookup cache with its designated unit type."""
        clean_name = name.strip()
        if not clean_name:
            return False
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO lookup_providers (name, provider_type) VALUES (?, ?)",
                (clean_name, provider_type)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_makes(self) -> list:
        """Retrieves unique vehicle makes."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT make FROM lookup_vehicle_models ORDER BY make ASC")
            return [row[0] for row in cursor.fetchall()]

    def get_models_for_make(self, make: str) -> list:
        """Retrieves models associated with a specific make."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT model FROM lookup_vehicle_models WHERE make = ? ORDER BY model ASC", (make,))
            return [row[0] for row in cursor.fetchall()]

    def add_make_model(self, make: str, model: str) -> bool:
        """Adds a new Make/Model combination."""
        clean_make = make.strip()
        clean_model = model.strip()
        if not clean_make or not clean_model:
            return False
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO lookup_vehicle_models (make, model) VALUES (?, ?)", (clean_make, clean_model))
            conn.commit()
            return cursor.rowcount > 0

    # --- VEHICLE QUERIES & CACHING ---

    def save_vehicles_bulk(self, vehicles_df: pd.DataFrame) -> None:
        """Saves or updates a batch of vehicle records from Google Sheets into SQLite."""
        if vehicles_df.empty:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for _, row in vehicles_df.iterrows():
                vid = str(row.get('Vehicle_ID', row.get('vehicle_id', row.get('Unit_ID', '')))).strip()
                if not vid:
                    continue

                raw_mileage = str(row.get('Mileage', row.get('mileage', 0))).replace(',', '').split('.')[0]
                mileage = int(raw_mileage) if raw_mileage.isdigit() else 0

                raw_interval = str(row.get('Service_Interval', row.get('service_interval', 7500))).split('.')[0]
                interval = int(raw_interval) if raw_interval.isdigit() else 7500

                cursor.execute("""
                    INSERT INTO master_vehicles (
                        vehicle_id, provider, status, restrictions, location, camera_status,
                        make, model, year, vin, plate, state, mileage, pave_insp,
                        registration, insurance, size, service_interval, return_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vehicle_id) DO UPDATE SET
                        provider=excluded.provider,
                        status=excluded.status,
                        restrictions=excluded.restrictions,
                        location=excluded.location,
                        camera_status=excluded.camera_status,
                        make=excluded.make,
                        model=excluded.model,
                        year=excluded.year,
                        vin=excluded.vin,
                        plate=excluded.plate,
                        state=excluded.state,
                        mileage=excluded.mileage,
                        pave_insp=excluded.pave_insp,
                        registration=excluded.registration,
                        insurance=excluded.insurance,
                        size=excluded.size,
                        service_interval=excluded.service_interval,
                        return_date=excluded.return_date
                """, (
                    vid,
                    str(row.get('Provider', row.get('provider', ''))),
                    str(row.get('Status', row.get('status', 'Active'))),
                    str(row.get('Restrictions', row.get('restrictions', 'Clear'))),
                    str(row.get('Location', row.get('location', 'WNC4'))),
                    str(row.get('Camera Status', row.get('camera_status', 'No'))),
                    str(row.get('Make', row.get('make', ''))),
                    str(row.get('Model', row.get('model', ''))),
                    str(row.get('Year', row.get('year', ''))),
                    str(row.get('VIN', row.get('vin', ''))),
                    str(row.get('Plate', row.get('plate', ''))),
                    str(row.get('State', row.get('state', ''))),
                    mileage,
                    str(row.get('PAVE_Insp', row.get('pave_insp', ''))),
                    str(row.get('Registration', row.get('registration', ''))),
                    str(row.get('Insurance', row.get('insurance', ''))),
                    str(row.get('Size', row.get('size', 'L'))),
                    interval,
                    str(row.get('Return_Date', row.get('return_date', '')))
                ))
            conn.commit()

    def get_all_vehicles(self) -> pd.DataFrame:
        """Retrieves all cached vehicles from SQLite."""
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM master_vehicles", conn)

    def update_vehicle_mileage(self, vehicle_id: str, new_mileage: int) -> None:
        """Updates vehicle mileage in SQLite and logs mutation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE master_vehicles SET mileage = ? WHERE vehicle_id = ?",
                (new_mileage, vehicle_id)
            )
            conn.commit()

        self.enqueue_mutation(
            action_type="UPDATE_MILEAGE",
            target_id=vehicle_id,
            payload={"vehicle_id": vehicle_id, "mileage": new_mileage}
        )

    def save_single_vehicle(self, vehicle_data: Dict[str, Any]) -> None:
        """Inserts a new unit into SQLite and enqueues sync."""
        df = pd.DataFrame([vehicle_data])
        self.save_vehicles_bulk(df)
        self.enqueue_mutation(
            action_type="ADD_UNIT",
            target_id=str(vehicle_data.get('vehicle_id', '')),
            payload=vehicle_data
        )

    # --- VEHICLE PURGE & RETIREMENT ---
    def replace_all_vehicles(self, df: pd.DataFrame) -> None:
        """
        Reconciles local cache with Google Sheets:
        Purges cached records and overwrites with authoritative cloud data.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM master_vehicles")
            conn.commit()

        if not df.empty:
            self.save_vehicles_bulk(df)

    def retire_vehicle(self, unit_id: str) -> None:
        """Removes a retired unit from the active roster in SQLite."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM master_vehicles WHERE vehicle_id = ?", (unit_id,))
            conn.commit()

    # --- QUEUE MANAGEMENT ---

    def enqueue_mutation(self, action_type: str, target_id: str, payload: Dict[str, Any]) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sync_queue (action_type, target_id, payload_json, status)
                VALUES (?, ?, ?, 'PENDING')
            """, (action_type, str(target_id), json.dumps(payload)))
            conn.commit()

    def get_pending_mutations(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sync_queue WHERE status = 'PENDING' ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def mark_mutation_synced(self, queue_id: int) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sync_queue 
                SET status = 'SYNCED', synced_at = ? 
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), queue_id))
            conn.commit()

    # --- INVENTORY & VENDORS ---

    def get_vendor_list(self) -> List[str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT vendor_name FROM vendors ORDER BY vendor_name ASC")
            vendors = [row['vendor_name'] for row in cursor.fetchall()]
            if not vendors:
                default_vendors = ["In-House Shop", "Mavis Tire & Auto", "Take 5", "Safelite"]
                cursor.executemany("INSERT OR IGNORE INTO vendors (vendor_name) VALUES (?)", [(v,) for v in default_vendors])
                conn.commit()
                return default_vendors
            return vendors

    def get_inventory(self) -> pd.DataFrame:
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM inventory", conn)

    def update_item_quantity(self, item_name: str, new_qty: int) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE inventory SET quantity = ? WHERE item_name = ?", (new_qty, item_name))
            conn.commit()

    def update_inventory_item(self, item_data: Dict[str, Any]) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE inventory SET
                    item_name = ?, category = ?, quantity = ?,
                    min_threshold = ?, reorder_link = ?, notes = ?
                WHERE id = ?
            """, (
                item_data['item_name'], item_data['category'], item_data['quantity'],
                item_data['min_threshold'], item_data['reorder_link'],
                item_data['notes'], item_data['id']
            ))
            conn.commit()

    def delete_inventory_item(self, item_id: int) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
            conn.commit()

    def save_service_record(self, data: Dict[str, Any]) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO service_logs (
                    vehicle_id, vin, date, service_type, mileage, vendor,
                    invoice_num, cost, notes, tire_count, tire_positions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['vehicle_id'], data['vin'], data['date'], data['service_type'],
                data['mileage'], data['vendor'], data['invoice_num'], data['cost'],
                data['notes'], data['tire_count'], data['tire_positions']
            ))
            cursor.execute("""
                UPDATE master_vehicles 
                SET mileage = MAX(mileage, ?) 
                WHERE vehicle_id = ?
            """, (data['mileage'], data['vehicle_id']))
            conn.commit()

        self.enqueue_mutation(
            action_type="LOG_SERVICE",
            target_id=str(data.get('vehicle_id', '')),
            payload=data
        )

    def auto_deduct_inventory(self, service_types: str, repair_text: str, tire_count: int, vehicle_make: str) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, item_name, quantity FROM inventory")
            items = cursor.fetchall()

            for item in items:
                item_id = item['id']
                item_name = str(item['item_name']).lower()
                cur_qty = int(item['quantity'])
                qty_to_deduct = 0

                if "tire" in service_types.lower() or "tire" in item_name:
                    if tire_count > 0:
                        if ("transit" in item_name or "235/65" in item_name) and vehicle_make.lower() == "ford":
                            qty_to_deduct = tire_count
                        elif ("ram" in item_name or "225/75" in item_name) and vehicle_make.lower() == "ram":
                            qty_to_deduct = tire_count
                        elif ("sprinter" in item_name or "245/75" in item_name) and "mercedes" in vehicle_make.lower():
                            qty_to_deduct = tire_count

                if qty_to_deduct == 0 and repair_text:
                    repair_lower = repair_text.lower()
                    clean_kw = [k for k in item_name.split() if len(k) > 3 and k not in ['stock', 'bulk', 'tires']]
                    if any(kw in repair_lower for kw in clean_kw):
                        qty_to_deduct = 1

                if qty_to_deduct > 0 and cur_qty > 0:
                    new_q = max(0, cur_qty - qty_to_deduct)
                    cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_q, item_id))

            conn.commit()

    def export_hive_training_snapshot(self) -> Dict[str, Any]:
        """Direct extraction hook for HIVE agent mirror ingestion."""
        with self.get_connection() as conn:
            vehicles = pd.read_sql_query("SELECT * FROM master_vehicles", conn).to_dict(orient="records")
            services = pd.read_sql_query("SELECT * FROM service_logs ORDER BY id DESC", conn).to_dict(orient="records")
            inventory = pd.read_sql_query("SELECT * FROM inventory", conn).to_dict(orient="records")
            mutations = pd.read_sql_query("SELECT * FROM sync_queue ORDER BY id DESC LIMIT 500", conn).to_dict(orient="records")

        return {
            "snapshot_timestamp": datetime.utcnow().isoformat(),
            "vehicles": vehicles,
            "services": services,
            "inventory": inventory,
            "recent_mutations": mutations
        }