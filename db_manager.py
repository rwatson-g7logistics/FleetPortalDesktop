"""
db_manager.py
-------------
SQLite database manager for local data persistence and caching.
Prevents Google Sheets API rate-limiting (429 errors) by serving UI read requests
directly from local memory while queuing updates to sync upstream.
"""

import sqlite3
import pandas as pd
from typing import List, Dict, Any, Optional
from config import DB_PATH


class DatabaseManager:
    """Manages local SQLite database operations and schema initializations."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Returns a connection instance to the local SQLite database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initializes database tables for local caching if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Vehicles Master Table
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

            # Service Records Cache
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

            # Parts & Tire Inventory Cache
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

            # Vendor List Cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_name TEXT UNIQUE
                )
            """)

            conn.commit()

    def save_vehicles_bulk(self, vehicles_df: pd.DataFrame) -> None:
        """Saves or updates a batch of vehicle records from Google Sheets into SQLite."""
        if vehicles_df.empty:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for _, row in vehicles_df.iterrows():
                cursor.execute("""
                    INSERT INTO master_vehicles (
                        vehicle_id, provider, status, restrictions, location, camera_status,
                        make, model, year, vin, plate, state, mileage, pave_insp,
                        registration, insurance, size, service_interval, return_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vehicle_id) DO UPDATE SET
                        status=excluded.status,
                        restrictions=excluded.restrictions,
                        location=excluded.location,
                        camera_status=excluded.camera_status,
                        mileage=excluded.mileage,
                        pave_insp=excluded.pave_insp,
                        registration=excluded.registration,
                        insurance=excluded.insurance,
                        return_date=excluded.return_date
                """, (
                    str(row.get('Vehicle_ID', '')), str(row.get('Provider', '')),
                    str(row.get('Status', 'Active')), str(row.get('Restrictions', 'Clear')),
                    str(row.get('Location', 'WNC4')), str(row.get('Camera Status', 'No')),
                    str(row.get('Make', '')), str(row.get('Model', '')),
                    str(row.get('Year', '')), str(row.get('VIN', '')),
                    str(row.get('Plate', '')), str(row.get('State', '')),
                    int(float(row.get('Mileage', 0))) if str(row.get('Mileage', '')).isdigit() else 0,
                    str(row.get('PAVE_Insp', '')), str(row.get('Registration', '')),
                    str(row.get('Insurance', '')), str(row.get('Size', 'L')),
                    int(float(row.get('Service_Interval', 7500))) if str(row.get('Service_Interval', '')).isdigit() else 7500,
                    str(row.get('Return_Date', ''))
                ))
            conn.commit()

    def get_all_vehicles(self) -> pd.DataFrame:
        """Retrieves all active and cached vehicles from the local SQLite database."""
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM master_vehicles", conn)

    def get_inventory(self) -> pd.DataFrame:
        """Retrieves all inventory items from the local SQLite database."""
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM inventory", conn)

    def update_item_quantity(self, item_name: str, new_qty: int) -> None:
        """Updates the stock quantity of a specific inventory item in SQLite."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE inventory SET quantity = ? WHERE item_name = ?",
                (new_qty, item_name)
            )
            conn.commit()

    def update_inventory_item(self, item_data: Dict[str, Any]) -> None:
        """Updates full record details for an existing inventory item in SQLite."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE inventory SET
                    item_name = ?,
                    category = ?,
                    quantity = ?,
                    min_threshold = ?,
                    reorder_link = ?,
                    notes = ?
                WHERE id = ?
            """, (
                item_data['item_name'], item_data['category'], item_data['quantity'],
                item_data['min_threshold'], item_data['reorder_link'],
                item_data['notes'], item_data['id']
            ))
            conn.commit()

    def delete_inventory_item(self, item_id: int) -> None:
        """Deletes an item record from local SQLite inventory by primary key."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
            conn.commit()

    def save_service_record(self, data: Dict[str, Any]) -> None:
        """Persists a new service entry locally in SQLite."""
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
            # Also update vehicle's master mileage if higher
            cursor.execute("""
                UPDATE master_vehicles 
                SET mileage = MAX(mileage, ?) 
                WHERE vehicle_id = ?
            """, (data['mileage'], data['vehicle_id']))
            conn.commit()

    def auto_deduct_inventory(self, service_types: str, repair_text: str, tire_count: int, vehicle_make: str) -> None:
        """
        Scans local SQLite inventory for matching tire specs or keyword parts (bulbs, wipers, oil)
        and automatically deducts stock counts.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, item_name, quantity, min_threshold, reorder_link FROM inventory")
            items = cursor.fetchall()

            for item in items:
                item_id = item['id']
                item_name = str(item['item_name']).lower()
                cur_qty = int(item['quantity'])
                qty_to_deduct = 0

                # 1. Tire Specs Match Logic
                if "tire" in service_types.lower() or "tire" in item_name:
                    if tire_count > 0:
                        if "transit" in item_name or "235/65" in item_name:
                            if vehicle_make.lower() == "ford": qty_to_deduct = tire_count
                        elif "ram" in item_name or "225/75" in item_name:
                            if vehicle_make.lower() == "ram": qty_to_deduct = tire_count
                        elif "sprinter" in item_name or "245/75" in item_name:
                            if "mercedes" in vehicle_make.lower(): qty_to_deduct = tire_count

                # 2. Parts/Fluids Keyword Deduction Logic
                if qty_to_deduct == 0 and repair_text:
                    repair_lower = repair_text.lower()
                    clean_kw = [k for k in item_name.split() if len(k) > 3 and k not in ['stock', 'bulk', 'tires']]
                    if any(kw in repair_lower for kw in clean_kw):
                        qty_to_deduct = 1

                # Apply Deduction
                if qty_to_deduct > 0 and cur_qty > 0:
                    new_q = max(0, cur_qty - qty_to_deduct)
                    cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_q, item_id))

            conn.commit()