"""
utils/provider_sop.py
---------------------
Dynamic Provider SOP Management Module.
Provides runtime lookup of vendor maintenance thresholds and an interactive
management dialog for configuring PM intervals, tire reimbursement windows,
and brake inspection cycles on the fly.
"""

from typing import Dict, Any, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QSpinBox, QTextEdit, QPushButton, QFormLayout, QMessageBox, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from utils.platform_helper import get_default_font_family, auto_size_combobox
from db_manager import DatabaseManager


def get_sop_for_provider(provider_name: str, db_manager: DatabaseManager) -> Dict[str, Any]:
    """Retrieves current operational thresholds for any provider."""
    return db_manager.get_provider_sop(provider_name)


class ProviderSOPEditDialog(QDialog):
    """Modal dialog allowing fleet managers to customize vendor SOP mileage requirements."""

    def __init__(self, db_manager: DatabaseManager, default_provider: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.default_provider = default_provider

        self.setWindowTitle("⚙️ Configure Provider SOP Requirements")
        self.setFixedSize(520, 520)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl_hdr = QLabel("⚙️ <b>Vendor Maintenance & Reimbursement SOPs</b><br><span style='color:#A6ADC8;'>Modify mileage metrics when leasing companies change coverage rules.</span>")
        lbl_hdr.setFont(QFont(get_default_font_family(), 11))
        lbl_hdr.setWordWrap(True)
        layout.addWidget(lbl_hdr)

        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: #181825; border: 1px solid #313244; border-radius: 8px;")
        form_layout = QFormLayout(form_frame)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setVerticalSpacing(12)

        # 1. Vendor Selection
        self.cmb_prov = QComboBox()
        sops = self.db.get_all_provider_sops()
        prov_names = [s['provider_name'] for s in sops]
        self.cmb_prov.addItems(prov_names)
        auto_size_combobox(self.cmb_prov)
        if self.default_provider and self.default_provider in prov_names:
            self.cmb_prov.setCurrentText(self.default_provider)
        combo_style = """
            QComboBox {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 6px;
                padding: 4px 10px;
                padding-right: 25px;
                min-height: 34px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left: 1px solid #45475A;
            }
            QComboBox QAbstractItemView {
                background-color: #181825;
                color: #CDD6F4;
                selection-background-color: #45475A;
                selection-color: #89B4FA;
                border: 1px solid #45475A;
                padding: 4px;
                outline: 0;
            }
            QComboBox QAbstractItemView::item {
                min-height: 32px;
                padding: 6px 10px;
            }
        """
        self.cmb_prov.setStyleSheet(combo_style)
        self.cmb_prov.setFixedHeight(36)
        self.cmb_prov.setMaxVisibleItems(10)
        self.cmb_prov.currentTextChanged.connect(self.load_selected_sop)

        spin_style = "background-color: #313244; color: #CDD6F4; border: 1px solid #45475A; border-radius: 6px; padding: 4px 8px; font-size: 13px;"

        # 2. Engine PM Interval
        self.spin_pm = QSpinBox()
        self.spin_pm.setRange(1000, 25000)
        self.spin_pm.setSingleStep(500)
        self.spin_pm.setSuffix(" mi")
        self.spin_pm.setFixedHeight(32)
        self.spin_pm.setStyleSheet(spin_style)

        # 3. Tire Reimbursement Threshold
        self.spin_tire_reimburse = QSpinBox()
        self.spin_tire_reimburse.setRange(5000, 50000)
        self.spin_tire_reimburse.setSingleStep(1000)
        self.spin_tire_reimburse.setSuffix(" mi")
        self.spin_tire_reimburse.setFixedHeight(32)
        self.spin_tire_reimburse.setStyleSheet(spin_style)

        # 4. Tire Reimbursement Alert Window
        self.spin_tire_window = QSpinBox()
        self.spin_tire_window.setRange(250, 5000)
        self.spin_tire_window.setSingleStep(250)
        self.spin_tire_window.setSuffix(" mi before")
        self.spin_tire_window.setFixedHeight(32)
        self.spin_tire_window.setStyleSheet(spin_style)

        # 5. Brake Lifecycle Interval
        self.spin_brakes = QSpinBox()
        self.spin_brakes.setRange(5000, 40000)
        self.spin_brakes.setSingleStep(1000)
        self.spin_brakes.setSuffix(" mi")
        self.spin_brakes.setFixedHeight(32)
        self.spin_brakes.setStyleSheet(spin_style)

        # 6. Notes / Policy Details
        self.txt_notes = QTextEdit()
        self.txt_notes.setFixedHeight(50)
        self.txt_notes.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 5px;")

        form_layout.addRow("Select Provider:", self.cmb_prov)
        form_layout.addRow("Oil PM Interval:", self.spin_pm)
        form_layout.addRow("Tire Reimburse Target:", self.spin_tire_reimburse)
        form_layout.addRow("Tire Early Alert Window:", self.spin_tire_window)
        form_layout.addRow("Brake Check Interval:", self.spin_brakes)
        form_layout.addRow("SOP Terms / Notes:", self.txt_notes)

        layout.addWidget(form_frame)

        # Action Buttons
        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 Update Provider SOP")
        btn_save.setFixedHeight(36)
        btn_save.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px;")
        btn_save.clicked.connect(self.save_sop)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

        # Initial load
        self.load_selected_sop(self.cmb_prov.currentText())

    def load_selected_sop(self, provider_name: str) -> None:
        """Populates form controls with the selected provider's active rules."""
        if not provider_name:
            return
        sop = self.db.get_provider_sop(provider_name)
        self.spin_pm.setValue(int(sop.get('oil_pm_interval', 7500)))
        self.spin_tire_reimburse.setValue(int(sop.get('tire_reimburse_miles', 15000)))
        self.spin_tire_window.setValue(int(sop.get('tire_warning_window', 1000)))
        self.spin_brakes.setValue(int(sop.get('brake_check_interval', 18000)))
        self.txt_notes.setPlainText(str(sop.get('notes', '')))

    def save_sop(self) -> None:
        """Commits updated metrics to SQLite."""
        prov = self.cmb_prov.currentText().strip()
        data = {
            "provider_name": prov,
            "oil_pm_interval": self.spin_pm.value(),
            "tire_reimburse_miles": self.spin_tire_reimburse.value(),
            "tire_warning_window": self.spin_tire_window.value(),
            "brake_check_interval": self.spin_brakes.value(),
            "alignment_interval": 15000,
            "notes": self.txt_notes.toPlainText().strip()
        }
        if self.db.save_provider_sop(data):
            QMessageBox.information(
                self, 
                "SOP Updated", 
                f"✅ SOP metrics updated for {prov}!\n\n"
                f"• Oil Interval: {data['oil_pm_interval']:,} mi\n"
                f"• Tire Target: {data['tire_reimburse_miles']:,} mi (Alert @ {data['tire_reimburse_miles'] - data['tire_warning_window']:,} mi)\n"
                f"• Brake Inspection: {data['brake_check_interval']:,} mi"
            )
            self.accept()
        else:
            QMessageBox.warning(self, "Save Failed", "Could not write SOP changes to local database.")