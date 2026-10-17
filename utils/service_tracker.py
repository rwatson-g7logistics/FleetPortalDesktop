"""
utils/service_tracker.py
------------------------
Multi-point maintenance and compliance tracking engine for a Fleet Portal Desktop edition.
Evaluates engine oil delta, 15,000-mile tire reimbursement eligibility, brake life,
and chassis alignment flags. Generates composite status badges and detailed tooltips.
"""

from typing import Dict, Any, List, Tuple

# imports from Utils
from utils.provider_sop import get_sop_for_provider


def evaluate_vehicle_health(vehicle_data: Dict[Any, Any], db_manager) -> Dict[str, Any]:
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

    # Fetch vendor's dynamic SOP profile
    prov_name = str(vehicle_data.get('provider', 'Other')).strip()
    sop = get_sop_for_provider(prov_name, db_manager)
    # Defaults if SOP is missing
    oil_interval = int(sop.get('oil_pm_interval', 7500))
    tire_target = int(sop.get('tire_reimburse_miles', 15000))
    tire_alert_window = int(sop.get('tire_warning_window', 1000))
    tire_early_alert = max(0, tire_target - tire_alert_window)
    brake_interval = int(sop.get('brake_check_interval', 18000))

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

    # 2. Tires: Dual-Clock Tracking (Provider Pay Reimbursement vs. Physical Safety)
    # A. Provider SOP Reimbursement Clock: Only resets when Provider paid!
    last_provider_tire_mileage = 0
    for l in logs:
        st = str(l.get('service_type', '')).lower()
        pr = str(l.get('payment_route', '')).lower()
        if 'tire' in st and pr == 'provider':
            last_provider_tire_mileage = int(l.get('mileage', 0))
            break

    # Miles accumulated toward the Provider's reimbursement threshold
    provider_sop_delta = current_mileage - last_provider_tire_mileage if last_provider_tire_mileage > 0 else current_mileage

    # B. Physical Safety Clock: Check latest recorded tread depth across any corner
    min_tread_depth = 10
    for l in logs:
        for pos_key in ('tread_df', 'tread_pf', 'tread_dr', 'tread_pr'):
            raw_depth = l.get(pos_key, 0)
            if raw_depth and int(raw_depth) > 0:
                min_tread_depth = min(min_tread_depth, int(raw_depth))

    # Evaluate statuses independently
    tire_status = "CLEAR"
    if min_tread_depth <= 3:
        tire_status = "TREAD_CRITICAL"
        tire_line = f"• Tires: 🚨 Physical Tread Critical ({min_tread_depth}/32\" — Ground/Replace)"
    elif provider_sop_delta >= tire_target:
        tire_status = "PROVIDER_DUE"
        tire_line = f"• Tires: 🔴 {provider_sop_delta:,}m on provider clock ({prov_name} Pay Due @ {tire_target:,}m)"
    elif min_tread_depth <= 4:
        tire_status = "TREAD_WARNING"
        tire_line = f"• Tires: ⚠️ Physical Tread Low ({min_tread_depth}/32\" — Replace Soon)"
    elif provider_sop_delta >= tire_early_alert:
        tire_status = "PROVIDER_WINDOW"
        tire_line = f"• Tires: 🟡 {provider_sop_delta:,}m on provider clock (Eligible for {prov_name} Pay @ {tire_target:,}m)"
    else:
        tire_line = f"• Tires: 🟢 {tire_target - provider_sop_delta:,}m to {tire_target:,}m {prov_name} Pay (Min Tread: {min_tread_depth}/32\")"

    # 3. Brakes (Vendor-Specific Lifecycle Check)
    last_brake_mileage = 0
    for l in logs:
        if 'brake' in str(l.get('service_type', '')).lower():
            last_brake_mileage = int(l.get('mileage', 0))
            break

    brake_delta = current_mileage - last_brake_mileage if last_brake_mileage > 0 else current_mileage
    brake_status = "CLEAR"

    if brake_delta >= (brake_interval + 3000):
        brake_status = "OVERDUE"
        brake_line = f"• Brakes: 🔴 {brake_delta:,}m since last inspection (Exceeds {brake_interval:,}m SOP)"
    elif brake_delta >= brake_interval:
        brake_status = "DUE_SOON"
        brake_line = f"• Brakes: 🟡 Pad Inspection Due ({brake_delta:,}m on pads; {brake_interval:,}m SOP)"
    else:
        brake_line = f"• Brakes: 🟢 Last checked {brake_delta:,}m ago (OK)"

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
    Parses historical logs using the Two-Clock Tire Model:
    1. Provider SOP Reimbursement Clock:
       Accumulates miles toward the 15k threshold. ONLY resets when payment_route == 'Provider'.
       Out-of-pocket replacements do NOT reset this clock.
    2. Physical Tire Clock:
       Tracks the actual tire currently on the hub (physical miles on tire, tread depth, install date).
       Resets whenever a new tire is mounted (Out of Pocket OR Provider).
    """
    positions = {
        'DF': {'name': 'Driver Front (Steer L)', 'last_provider_m': None, 'last_physical_m': None, 'install_date': 'N/A', 'install_route': 'Factory', 'depth': None, 'depth_date': 'N/A'},
        'PF': {'name': 'Passenger Front (Steer R)', 'last_provider_m': None, 'last_physical_m': None, 'install_date': 'N/A', 'install_route': 'Factory', 'depth': None, 'depth_date': 'N/A'},
        'DR': {'name': 'Driver Rear (Drive L)', 'last_provider_m': None, 'last_physical_m': None, 'install_date': 'N/A', 'install_route': 'Factory', 'depth': None, 'depth_date': 'N/A'},
        'PR': {'name': 'Passenger Rear (Drive R)', 'last_provider_m': None, 'last_physical_m': None, 'install_date': 'N/A', 'install_route': 'Factory', 'depth': None, 'depth_date': 'N/A'},
    }

    clean_uid = vehicle_id.split('_')[-1]
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT mileage, date, tire_positions, invoice_num, payment_route, service_type,
                   tread_df, tread_pf, tread_dr, tread_pr
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
        pos_str = str(row['tire_positions'] or '').upper()
        st = str(row['service_type'] or '').lower()
        pr = str(row['payment_route'] or '').lower()
        is_replacement = ('replacement' in st) or ('replaced' in st) or ('new tire' in st)

        for pos in ('DF', 'PF', 'DR', 'PR'):
            if pos in pos_str:
                # 1. Provider SOP Clock: ONLY resets if Provider paid for it
                if is_replacement and pr == 'provider' and positions[pos]['last_provider_m'] is None:
                    positions[pos]['last_provider_m'] = log_mil

                # 2. Physical Tire Clock: Resets on ANY replacement (Out of Pocket or Provider)
                if is_replacement and positions[pos]['last_physical_m'] is None:
                    positions[pos]['last_physical_m'] = log_mil
                    positions[pos]['install_date'] = log_date
                    positions[pos]['install_route'] = 'Provider Paid' if pr == 'provider' else 'Out of Pocket'

                # 3. Physical Tread Depth: Latest measurement (Audit or Replacement)
                raw_d = row[depth_map[pos]] if depth_map[pos] in row.keys() else 0
                if raw_d and positions[pos]['depth'] is None:
                    positions[pos]['depth'] = int(raw_d)
                    positions[pos]['depth_date'] = log_date

    # Resolve active vendor SOP rule
    with db_manager.get_connection() as conn:
        v_cur = conn.cursor()
        v_cur.execute("SELECT provider FROM master_vehicles WHERE vehicle_id = ? OR vehicle_id LIKE ?", (vehicle_id, f"%_{clean_uid}"))
        v_row = v_cur.fetchone()
        prov_tag = v_row['provider'] if v_row else 'Other'

    from utils.provider_sop import get_sop_for_provider
    v_sop = get_sop_for_provider(prov_tag, db_manager)
    t_target = int(v_sop.get('tire_reimburse_miles', 15000))
    t_early = max(0, t_target - int(v_sop.get('tire_warning_window', 1000)))

    results = {}
    for pos, data in positions.items():
        # A. Provider Reimbursement Clock Math
        last_prov = data['last_provider_m']
        sop_miles = max(0, current_mileage - last_prov) if last_prov is not None else current_mileage

        if sop_miles >= t_target:
            sop_badge = f"🔴 {prov_tag} Pay Due ({t_target // 1000}k+)"
            sop_color = "#F38BA8"
        elif sop_miles >= t_early:
            sop_badge = f"🟡 {prov_tag} Window ({t_early // 1000}k+)"
            sop_color = "#F9E2AF"
        else:
            sop_badge = f"🟢 {t_target - sop_miles:,}m to {t_target // 1000}k SOP"
            sop_color = "#A6E3A1"

        # B. Physical Tire Wear Math
        last_phys = data['last_physical_m']
        physical_miles = max(0, current_mileage - last_phys) if last_phys is not None else current_mileage

        depth_val = data['depth'] if data['depth'] is not None else 10
        if depth_val <= 3:
            depth_badge = f"🚨 {depth_val}/32\" — Replace"
            depth_color = "#F38BA8"
        elif depth_val <= 4:
            depth_badge = f"⚠️ {depth_val}/32\" — Warning"
            depth_color = "#F9E2AF"
        else:
            depth_badge = f"🟢 {depth_val}/32\" — OK"
            depth_color = "#A6E3A1"

        # C. Metadata string showing install type
        if data['last_physical_m'] is not None:
            install_info = f"{data['install_date']} ({data['install_route']})"
        else:
            install_info = "Pre-tracking / Initial"

        results[pos] = {
            'label': data['name'],
            'sop_miles': sop_miles,
            'sop_badge': sop_badge,
            'sop_color': sop_color,
            'tread_depth': depth_val,
            'depth_badge': depth_badge,
            'depth_color': depth_color,
            'physical_miles': physical_miles,
            'install_info': install_info,
            'meta_str': f"Tire: {install_info} | Checked: {data['depth_date']}"
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