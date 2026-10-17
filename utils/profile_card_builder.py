"""
utils/profile_card_builder.py
-----------------------------
Modular UI builder for Vehicle Deep Dive specifications and telemetry cards.
Extracts complex card layout logic away from views/vehicle_profile.py to keep
the profile controller clean and maintainable.
"""

from typing import Dict, Any
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from utils.platform_helper import get_default_font_family
from utils.provider_sop import get_sop_for_provider
from utils.rental_lifecycle import evaluate_rental_compliance


def build_specs_card(vehicle_data: Dict[str, Any]) -> QFrame:
    """Constructs the left-hand vehicle specifications card with selectable text."""
    card = QFrame()
    card.setStyleSheet("background-color: #1E1E2E; border-radius: 10px; border: 1px solid #313244;")
    grid = QGridLayout(card)
    grid.setContentsMargins(18, 16, 18, 16)
    grid.setVerticalSpacing(10)
    grid.setHorizontalSpacing(16)

    lbl_header = QLabel("Vehicle Specifications")
    lbl_header.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
    lbl_header.setStyleSheet("color: #89B4FA; border: none; padding-bottom: 4px;")
    grid.addWidget(lbl_header, 0, 0, 1, 2)

    prov = str(vehicle_data.get('provider', 'Fleet'))
    u_type = str(vehicle_data.get('unit_type', 'Fleet'))
    make_model = f"{vehicle_data.get('make', '')} {vehicle_data.get('model', '')}".strip() or "Unknown"

    spec_fields = [
        ("Provider / Type:", f"{prov} ({u_type})"),
        ("Make / Model:", make_model),
        ("Model Year:", str(vehicle_data.get('year', 'N/A'))),
        ("Vehicle Size:", str(vehicle_data.get('size', 'Standard'))),
        ("VIN Number:", str(vehicle_data.get('vin', 'N/A'))),
        ("License Plate:", f"{vehicle_data.get('plate', 'N/A')} ({vehicle_data.get('state', '')})"),
        ("Camera Installed:", str(vehicle_data.get('camera_status', 'No')))
    ]

    for i, (k_text, v_text) in enumerate(spec_fields, start=1):
        lbl_k = QLabel(k_text)
        lbl_k.setStyleSheet("color: #A6ADC8; font-weight: bold; border: none;")
        lbl_v = QLabel(str(v_text))
        lbl_v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl_v.setStyleSheet("color: #CDD6F4; font-size: 13px; border: none;")
        grid.addWidget(lbl_k, i, 0)
        grid.addWidget(lbl_v, i, 1)

    return card


def build_telemetry_card(vehicle_data: Dict[str, Any], db_manager) -> QFrame:
    """Constructs the right-hand operational status and dynamic PM countdown card."""
    card = QFrame()
    card.setStyleSheet("background-color: #1E1E2E; border-radius: 10px; border: 1px solid #313244;")
    grid = QGridLayout(card)
    grid.setContentsMargins(18, 16, 18, 16)
    grid.setVerticalSpacing(10)
    grid.setHorizontalSpacing(16)

    lbl_header = QLabel("Operational Telemetry & Status")
    lbl_header.setFont(QFont(get_default_font_family(), 12, QFont.Weight.Bold))
    lbl_header.setStyleSheet("color: #89B4FA; border: none; padding-bottom: 4px;")
    grid.addWidget(lbl_header, 0, 0, 1, 2)

    # 1. Dynamic Odometer & PM Countdown Math
    raw_mil = str(vehicle_data.get('mileage', 0)).replace(',', '').split('.')[0]
    mileage = int(raw_mil) if raw_mil.isdigit() else 0

    raw_last_a = str(vehicle_data.get('last_a_service', 0)).replace(',', '').split('.')[0]
    last_a = int(raw_last_a) if raw_last_a.isdigit() else 0

    prov = str(vehicle_data.get('provider', 'Fleet'))
    prov_sop = get_sop_for_provider(prov, db_manager)
    interval = int(prov_sop.get('oil_pm_interval', 7500))

    diff = mileage - last_a
    if diff >= interval:
        pm_text = f"🔴 {diff - interval:,}m Overdue"
    elif diff >= (interval - 500):
        pm_text = f"🟡 {interval - diff:,}m Due Soon"
    else:
        pm_text = f"🟢 {interval - diff:,}m Remaining"

    # 2. Rental / Universal Return Date Formatting
    ret_date_str = str(vehicle_data.get('return_date', '')).strip()
    if ret_date_str and ret_date_str not in ['None', 'N/A', 'Clear', '', 'Unknown']:
        eval_res = evaluate_rental_compliance(ret_date_str)
        ret_display = f"{ret_date_str} ({eval_res['badge']})"
    else:
        ret_display = "N/A (Fleet Permanent)"

    status_fields = [
        ("Roster Status:", str(vehicle_data.get('status', 'Active'))),
        ("Operating Base:", str(vehicle_data.get('location', 'WNC4'))),
        ("Current Odometer:", f"{mileage:,} mi"),
        ("Service Schedule:", pm_text),
        ("Registration:", str(vehicle_data.get('registration', 'Clear'))),
        ("Insurance Card:", str(vehicle_data.get('insurance', 'Clear'))),
        ("Return Schedule:", ret_display)
    ]

    for i, (k_text, v_text) in enumerate(status_fields, start=1):
        lbl_k = QLabel(k_text)
        lbl_k.setStyleSheet("color: #A6ADC8; font-weight: bold; border: none;")
        lbl_v = QLabel(str(v_text))
        lbl_v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if "Overdue" in v_text or "Expired" in v_text:
            lbl_v.setStyleSheet("color: #F38BA8; font-weight: bold; font-size: 13px; border: none;")
        elif "Due Soon" in v_text or "Due Tomorrow" in v_text or "Left" in v_text:
            lbl_v.setStyleSheet("color: #F9E2AF; font-weight: bold; font-size: 13px; border: none;")
        else:
            lbl_v.setStyleSheet("color: #CDD6F4; font-size: 13px; border: none;")

        grid.addWidget(lbl_k, i, 0)
        grid.addWidget(lbl_v, i, 1)

    return card