"""
utils/service_tracker.py
------------------------
Multi-point maintenance and compliance tracking engine for G7 Fleet Portal Desktop.
Evaluates engine oil delta, 15,000-mile tire reimbursement eligibility, brake life,
and chassis alignment flags. Generates composite status badges and detailed tooltips.
"""

from typing import Dict, Any, List, Tuple


def evaluate_vehicle_health(vehicle_data: Dict[str, Any], db_manager) -> Dict[str, Any]:
    """
    Evaluates comprehensive vehicle maintenance telemetry across 4 subsystems:
    1. Oil / Scheduled PM: Odometer delta against service_interval (7500 / 5000).
    2. Tires: 15,000-mile provider billing threshold and wear limits.
    3. Brakes: 18,000-mile pad wear delta or physical measurement.
    4. Alignment: Event flags in vehicle restrictions or notes.

    Returns:
        dict with keys: 'badge', 'color', 'tooltip', 'critical_types', 'severity'
        (severity: 0 = Clear, 1 = Warning, 2 = Critical)
    """
    vehicle_id = str(vehicle_data.get('vehicle_id', ''))
    raw_uid = str(vehicle_data.get('unit_id') or vehicle_id.split('_')[-1])
    
    raw_mil = str(vehicle_data.get('mileage', 0)).replace(',', '').split('.')[0]
    current_mileage = int(raw_mil) if raw_mil.isdigit() else 0

    raw_int = str(vehicle_data.get('service_interval', 7500)).split('.')[0]
    oil_interval = int(raw_int) if raw_int.isdigit() else 7500

    # Fetch historical service logs from SQLite cache
    logs = []
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT service_type, mileage, notes, date 
            FROM service_logs 
            WHERE vehicle_id = ? OR vehicle_id = ?
            ORDER BY id DESC
        """, (vehicle_id, raw_uid))
        logs = [dict(r) for r in cursor.fetchall()]

    # 1. Engine Oil (A/B Service) Evaluation
    raw_last_a = str(vehicle_data.get('last_a_service', 0)).replace(',', '').split('.')[0]
    last_a_mileage = int(raw_last_a) if raw_last_a.isdigit() else 0

    # Fallback to logs if last_a_service is not set on vehicle
    if last_a_mileage == 0:
        for l in logs:
            st = str(l.get('service_type', '')).lower()
            if 'a service' in st or 'b service' in st:
                last_a_mileage = int(l.get('mileage', 0))
                break

    oil_delta = current_mileage - last_a_mileage
    oil_remaining = oil_interval - oil_delta

    oil_status = "CLEAR"
    if oil_delta >= oil_interval:
        oil_status = "OVERDUE"
        oil_line = f"• Oil PM: 🔴 {abs(oil_remaining):,}m Overdue (Interval: {oil_interval:,}m)"
    elif oil_remaining <= 500:
        oil_status = "DUE_SOON"
        oil_line = f"• Oil PM: 🟡 Due Soon ({oil_remaining:,}m left)"
    else:
        oil_line = f"• Oil PM: 🟢 {oil_remaining:,}m remaining"

    # 2. Tires (15,000-Mile Provider Reimbursement Window)
    last_tire_mileage = 0
    for l in logs:
        if 'tire' in str(l.get('service_type', '')).lower():
            last_tire_mileage = int(l.get('mileage', 0))
            break

    tire_delta = current_mileage - last_tire_mileage if last_tire_mileage > 0 else current_mileage
    tire_status = "CLEAR"

    if tire_delta >= 15000:
        tire_status = "REPLACE_DUE"
        tire_line = f"• Tires: 🔴 {tire_delta:,}m on set (Provider Pay Threshold Reached @ 15k)"
    elif tire_delta >= 14000:
        tire_status = "PROVIDER_WINDOW"
        tire_line = f"• Tires: 🟡 {tire_delta:,}m on set (Eligible for Provider Pay @ 15k)"
    else:
        tire_line = f"• Tires: 🟢 {tire_delta:,}m on set (15k threshold: {15000 - tire_delta:,}m left)"

    # 3. Brakes (18,000-Mile Lifecycle Check)
    last_brake_mileage = 0
    for l in logs:
        if 'brake' in str(l.get('service_type', '')).lower():
            last_brake_mileage = int(l.get('mileage', 0))
            break

    brake_delta = current_mileage - last_brake_mileage if last_brake_mileage > 0 else current_mileage
    brake_status = "CLEAR"

    if brake_delta >= 22000:
        brake_status = "OVERDUE"
        brake_line = f"• Brakes: 🔴 {brake_delta:,}m since last inspection (Exceeds 18k limit)"
    elif brake_delta >= 18000:
        brake_status = "DUE_SOON"
        brake_line = f"• Brakes: 🟡 Pad Inspection Due ({brake_delta:,}m since last service)"
    else:
        brake_line = f"• Brakes: 🟢 Last serviced {brake_delta:,}m ago (OK)"

    # 4. Alignment & Chassis Pulling Check
    restrictions = str(vehicle_data.get('restrictions', '')).lower()
    alignment_status = "CLEAR"
    if 'alignment' in restrictions or 'pulling' in restrictions:
        alignment_status = "FLAGGED"
        align_line = f"• Alignment: ⚠️ Pulling/Inspect Flagged in Vehicle Restrictions"
    else:
        align_line = "• Alignment: 🟢 Clear / Centered"

    # --- COMPOSITE SCORING (HIGHEST SEVERITY WINS) ---
    critical_types = []
    if oil_status == "OVERDUE":
        critical_types.append("A Service")
    if tire_status == "REPLACE_DUE":
        critical_types.append("Tires")
    if brake_status == "OVERDUE":
        critical_types.append("Brakes")

    warning_types = []
    if oil_status == "DUE_SOON" and "A Service" not in critical_types:
        warning_types.append("A Service")
    if tire_status == "PROVIDER_WINDOW" and "Tires" not in critical_types:
        warning_types.append("Tires")
    if brake_status == "DUE_SOON" and "Brakes" not in critical_types:
        warning_types.append("Brakes")
    if alignment_status == "FLAGGED":
        warning_types.append("Diagnostics")

    # Final badge assignment
    if critical_types:
        badge = f"🔴 {critical_types[0]} Overdue" if len(critical_types) == 1 else f"🔴 {len(critical_types)} Critical Svcs"
        color = "#F38BA8"
        severity = 2
    elif warning_types:
        badge = f"🟡 {warning_types[0]} Due Soon" if len(warning_types) == 1 else f"🟡 {len(warning_types)} Svcs Due"
        color = "#F9E2AF"
        severity = 1
    else:
        badge = "🟢 Clear"
        color = "#A6E3A1"
        severity = 0

    tooltip_header = f"🛠️ <b>Maintenance Telemetry: Unit {raw_uid}</b>"
    tooltip_body = "\n".join([oil_line, tire_line, brake_line, align_line])
    tooltip_footer = "\n<i>(Click to open Service Logger for this unit)</i>"

    return {
        'badge': badge,
        'color': color,
        'tooltip': f"{tooltip_header}\n{tooltip_body}{tooltip_footer}",
        'critical_types': critical_types + warning_types,
        'severity': severity
    }

def get_tire_position_telemetry(vehicle_id: str, current_mileage: int, db_manager) -> Dict[str, Any]:
    """
    Parses historical logs to calculate:
    1. Provider SOP: Odometer delta since last install (15,000 mi threshold for reimbursement).
    2. Physical Wear: Latest measured tread depth (32nds) per wheel position with datestamp and invoice.
    """
    positions = {
        'DF': {'name': 'Driver Front (Steer L)', 'last_mileage': None, 'date': 'N/A', 'invoice': 'N/A', 'depth': None},
        'PF': {'name': 'Passenger Front (Steer R)', 'last_mileage': None, 'date': 'N/A', 'invoice': 'N/A', 'depth': None},
        'DR': {'name': 'Driver Rear (Drive L)', 'last_mileage': None, 'date': 'N/A', 'invoice': 'N/A', 'depth': None},
        'PR': {'name': 'Passenger Rear (Drive R)', 'last_mileage': None, 'date': 'N/A', 'invoice': 'N/A', 'depth': None},
    }

    clean_uid = vehicle_id.split('_')[-1]
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT mileage, date, tire_positions, invoice_num, tread_df, tread_pf, tread_dr, tread_pr
            FROM service_logs 
            WHERE (vehicle_id = ? OR vehicle_id = ?) 
              AND service_type LIKE '%Tire%'
            ORDER BY id DESC
        """, (vehicle_id, clean_uid))
        logs = cursor.fetchall()

    depth_map = {'DF': 'tread_df', 'PF': 'tread_pf', 'DR': 'tread_dr', 'PR': 'tread_pr'}

    for row in logs:
        log_mil = row['mileage'] or 0
        log_date = row['date'] or 'N/A'
        log_inv = row['invoice_num'] or 'N/A'
        pos_str = str(row['tire_positions'] or '').upper()

        for pos in ('DF', 'PF', 'DR', 'PR'):
            if pos in pos_str and positions[pos]['last_mileage'] is None:
                positions[pos]['last_mileage'] = log_mil
                positions[pos]['date'] = log_date
                positions[pos]['invoice'] = log_inv
                raw_d = row[depth_map[pos]] if depth_map[pos] in row.keys() else 0
                if raw_d and positions[pos]['depth'] is None:
                    positions[pos]['depth'] = raw_d

    results = {}
    for pos, data in positions.items():
        last_m = data['last_mileage']
        if last_m is not None:
            miles_on_tire = max(0, current_mileage - last_m)
            sop_installed_str = f"Installed: {data['date']} @ {last_m:,} mi"
        else:
            miles_on_tire = current_mileage
            sop_installed_str = "Factory / Pre-tracking"

        # 1. Provider SOP Reimbursement Status
        if miles_on_tire >= 15000:
            sop_badge = "🔴 Provider Pay Due (15k+)"
            sop_color = "#F38BA8"
        elif miles_on_tire >= 14000:
            sop_badge = "🟡 Provider Window (14k+)"
            sop_color = "#F9E2AF"
        else:
            sop_badge = f"🟢 {15000 - miles_on_tire:,}m to 15k SOP"
            sop_color = "#A6E3A1"

        # 2. Physical Tread Depth Status
        depth_val = data['depth'] if data['depth'] is not None else 10
        if depth_val <= 3:
            depth_badge = f"🚨 {depth_val}/32\" — Replace Immediately"
            depth_color = "#F38BA8"
        elif depth_val <= 4:
            depth_badge = f"⚠️ {depth_val}/32\" — Warning (Replace Soon)"
            depth_color = "#F9E2AF"
        else:
            depth_badge = f"🟢 {depth_val}/32\" — Operational"
            depth_color = "#A6E3A1"

        results[pos] = {
            'label': data['name'],
            'miles_on_tire': miles_on_tire,
            'sop_installed_str': sop_installed_str,
            'sop_badge': sop_badge,
            'sop_color': sop_color,
            'tread_depth': depth_val,
            'depth_badge': depth_badge,
            'depth_color': depth_color,
            'date': data['date'],
            'invoice': data['invoice']
        }
    return results


def get_subsystem_milestones(vehicle_id: str, current_mileage: int, db_manager) -> Dict[str, Any]:
    """Retrieves milestone records for Oil, Brakes (mm, %, Rotors), and Alignment with datestamps and invoices."""
    clean_uid = vehicle_id.split('_')[-1]
    milestones = {
        'oil': {'name': 'Engine Oil (PM)', 'last_mileage': 0, 'date': 'N/A', 'invoice': 'N/A'},
        'brakes': {
            'name': 'Brake System', 
            'last_mileage': 0, 
            'date': 'N/A', 
            'invoice': 'N/A',
            'front_mm': 0,
            'front_pct': 0,
            'rear_mm': 0,
            'rear_pct': 0,
            'rotors': 'Good'
        },
        'alignment': {'name': 'Chassis Alignment', 'last_mileage': 0, 'date': 'N/A', 'invoice': 'N/A'}
    }

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT service_type, mileage, date, invoice_num,
                   brake_front_mm, brake_front_pct, brake_rear_mm, brake_rear_pct, rotor_condition
            FROM service_logs 
            WHERE vehicle_id = ? OR vehicle_id = ?
            ORDER BY id DESC
        """, (vehicle_id, clean_uid))
        logs = cursor.fetchall()

    for row in logs:
        st = str(row['service_type'] or '').lower()
        mil = row['mileage'] or 0
        date_str = row['date'] or 'N/A'
        inv = row['invoice_num'] or 'N/A'

        if ('a service' in st or 'b service' in st) and milestones['oil']['last_mileage'] == 0:
            milestones['oil'] = {'name': 'Engine Oil (PM)', 'last_mileage': mil, 'date': date_str, 'invoice': inv}
        if 'brake' in st and milestones['brakes']['last_mileage'] == 0:
            keys = row.keys()
            milestones['brakes'] = {
                'name': 'Brake System',
                'last_mileage': mil,
                'date': date_str,
                'invoice': inv,
                'front_mm': row['brake_front_mm'] if 'brake_front_mm' in keys else 0,
                'front_pct': row['brake_front_pct'] if 'brake_front_pct' in keys else 0,
                'rear_mm': row['brake_rear_mm'] if 'brake_rear_mm' in keys else 0,
                'rear_pct': row['brake_rear_pct'] if 'brake_rear_pct' in keys else 0,
                'rotors': row['rotor_condition'] if 'rotor_condition' in keys and row['rotor_condition'] else 'Good'
            }
        if 'alignment' in st and milestones['alignment']['last_mileage'] == 0:
            milestones['alignment'] = {'name': 'Chassis Alignment', 'last_mileage': mil, 'date': date_str, 'invoice': inv}

    return milestones