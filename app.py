"""
FleetPortalDesktop/app.py
------
Main application window for G7 Fleet Command Center Desktop.
Uses PySide6 (Qt) to provide a responsive, cross-platform interface (macOS & Windows).
"""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from config import APP_TITLE, WINDOW_SIZE, MIN_WINDOW_SIZE, TOKEN_PATH
from db_manager import DatabaseManager
from cloud_sync import PushWorker, SyncWorker, DriveUploadWorker, AuthWorker
from utils.platform_helper import get_default_font_family

from views.fleet_view import FleetView
from views.inventory_view import InventoryView
from views.vehicle_profile import VehicleProfileView
from views.unit_service_view import UnitServiceView
from views.service_view import ServiceFormView
from views.cost_center import CostCenterView
from views.document_center import DocumentCenterView



class FleetPortalApp(QMainWindow):
    """Main Desktop Window managing layout, navigation sidebar, and frame stacking."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.setStyleSheet("background-color: #11111B; color: #CDD6F4;")

        self.db = DatabaseManager()

        self.sync_worker = None
        self.push_worker = None
        self.drive_worker = None
        self.auth_worker = None

        self.dynamic_views = []

        self.init_ui()
        self.start_background_sync()

    def init_ui(self) -> None:
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 1. LEFT NAVIGATION SIDEBAR ---
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("background-color: #181825; color: #CDD6F4; border-right: 1px solid #313244;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 20, 15, 20)
        sidebar_layout.setSpacing(10)

        lbl_title = QLabel("🚀 G7 FLEET\nCOMMAND")
        lbl_title.setFont(QFont(get_default_font_family(), 14, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #89B4FA; margin-bottom: 20px;")
        sidebar_layout.addWidget(lbl_title)

        self.btn_fleet = QPushButton("📊 Fleet Overview")
        self.btn_cost = QPushButton("💰 Cost Center")
        self.btn_inventory = QPushButton("📦 Parts & Inventory")
        self.btn_docs = QPushButton("📁 Document Center")

        nav_buttons = [self.btn_fleet, self.btn_cost, self.btn_inventory, self.btn_docs]
        for idx, btn in enumerate(nav_buttons):
            btn.setFixedHeight(45)
            btn.setFont(QFont(get_default_font_family(), 11, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #CDD6F4;
                    border: none;
                    border-radius: 6px;
                    text-align: left;
                    padding-left: 12px;
                }
                QPushButton:hover {
                    background-color: #313244;
                    color: #89B4FA;
                }
            """)
            btn.clicked.connect(lambda _, i=idx: self.switch_view(i))
            sidebar_layout.addWidget(btn)

        sidebar_layout.addStretch()

        # Connect / Re-Authenticate Button
        self.btn_auth = QPushButton("🔑 Connect Google Account")
        self.btn_auth.setFixedHeight(35)
        self.btn_auth.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auth.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #89B4FA;
                border: 1px solid #45475A;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #45475A;
                color: #A6E3A1;
            }
        """)
        self.btn_auth.clicked.connect(self.trigger_google_login)
        sidebar_layout.addWidget(self.btn_auth)

        # Status & Sync Indicator Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #313244;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #89B4FA;
                border-radius: 3px;
            }
        """)
        sidebar_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Local Cache Ready")
        self.lbl_status.setFont(QFont(get_default_font_family(), 9))
        self.lbl_status.setStyleSheet("color: #A6ADC8; margin-top: 5px;")
        sidebar_layout.addWidget(self.lbl_status)

        main_layout.addWidget(sidebar)

        # --- 2. RIGHT CONTENT AREA ---
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("background-color: #11111B; color: #CDD6F4;")

        self.fleet_view = FleetView(self.db)
        self.fleet_view.vehicle_selected.connect(self.open_vehicle_profile)
        self.fleet_view.service_hub_requested.connect(self.show_unit_service_hub)
        self.fleet_view.data_mutated.connect(self.trigger_upstream_push)

        self.cost_center_view = CostCenterView(self.db)
        self.inventory_view = InventoryView(self.db)
        self.inventory_view.inventory_updated.connect(self.trigger_upstream_push)
        self.document_center_view = DocumentCenterView()

        self.content_stack.addWidget(self.fleet_view)
        self.content_stack.addWidget(self.cost_center_view)
        self.content_stack.addWidget(self.inventory_view)
        self.content_stack.addWidget(self.document_center_view)

        main_layout.addWidget(self.content_stack)
        self.update_nav_styles(0)

    def switch_view(self, index: int) -> None:
        self.content_stack.setCurrentIndex(index)
        self.update_nav_styles(index)
        self.cleanup_dynamic_views()

    def update_nav_styles(self, active_index: int) -> None:
        buttons = [self.btn_fleet, self.btn_cost, self.btn_inventory, self.btn_docs]
        for idx, btn in enumerate(buttons):
            if idx == active_index:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #313244;
                        color: #89B4FA;
                        font-weight: bold;
                        border: none;
                        border-radius: 6px;
                        text-align: left;
                        padding-left: 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #CDD6F4;
                        border: none;
                        border-radius: 6px;
                        text-align: left;
                        padding-left: 12px;
                    }
                    QPushButton:hover {
                        background-color: #313244;
                        color: #89B4FA;
                    }
                """)

    def show_unit_service_hub(self, vehicle_id: str) -> None:
        self.cleanup_dynamic_views()
        service_hub_view = UnitServiceView(self.db, vehicle_id)
        service_hub_view.back_requested.connect(lambda: self.switch_view(0))
        service_hub_view.log_service_requested.connect(self.open_service_form)
        idx = self.content_stack.addWidget(service_hub_view)
        self.dynamic_views.append(service_hub_view)
        self.content_stack.setCurrentIndex(idx)

    def open_vehicle_profile(self, vehicle_id: str) -> None:
        self.cleanup_dynamic_views()
        profile_view = VehicleProfileView(self.db, vehicle_id)
        profile_view.back_requested.connect(lambda: self.switch_view(0))
        profile_view.log_service_requested.connect(self.open_service_form)
        idx = self.content_stack.addWidget(profile_view)
        self.dynamic_views.append(profile_view)
        self.content_stack.setCurrentIndex(idx)

    def open_service_form(self, vehicle_data: dict) -> None:
        service_form = ServiceFormView(self.db, vehicle_data)
        service_form.service_logged.connect(self.on_service_logged_success)
        service_form.cancel_requested.connect(
            lambda: self.open_vehicle_profile(vehicle_data.get('vehicle_id', ''))
        )
        idx = self.content_stack.addWidget(service_form)
        self.dynamic_views.append(service_form)
        self.content_stack.setCurrentIndex(idx)

    def on_service_logged_success(self, vehicle_id: str) -> None:
        self.open_vehicle_profile(vehicle_id)
        self.cost_center_view.refresh_data()
        self.inventory_view.refresh_data()
        self.trigger_upstream_push()

    def cleanup_dynamic_views(self) -> None:
        for view in self.dynamic_views:
            self.content_stack.removeWidget(view)
            view.deleteLater()
        self.dynamic_views.clear()

    # --- 3. CLOUD AUTH & WORKERS ---

    def trigger_google_login(self) -> None:
        """Launches Google OAuth browser flow to generate token.json."""
        self.lbl_status.setText("Awaiting browser sign-in...")
        self.progress_bar.setRange(0, 0)
        self.btn_auth.setEnabled(False)

        self.auth_worker = AuthWorker()
        self.auth_worker.auth_finished.connect(self.on_auth_finished)
        self.auth_worker.start()

    def on_auth_finished(self, success: bool, message: str) -> None:
        self.btn_auth.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        if success:
            self.btn_auth.setText("✅ Google Connected")
            self.btn_auth.setStyleSheet("""
                QPushButton {
                    background-color: #313244;
                    color: #A6E3A1;
                    border: 1px solid #A6E3A1;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 11px;
                }
            """)
            QMessageBox.information(self, "Connected", "Google Workspace account connected successfully!")
            self.start_background_sync()
            self.trigger_upstream_push()
        else:
            self.lbl_status.setText("Sign-In Incomplete")
            QMessageBox.critical(self, "Authentication Failed", message)

    def start_background_sync(self) -> None:
        self.lbl_status.setText("Syncing with Google Cloud...")
        self.progress_bar.setRange(0, 0)

        self.sync_worker = SyncWorker(self.db)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)
        self.sync_worker.vehicles_loaded.connect(self.on_vehicles_loaded)
        self.sync_worker.start()

    def trigger_upstream_push(self) -> None:
        if self.push_worker is not None and self.push_worker.isRunning():
            return

        self.lbl_status.setText("Pushing local updates to Cloud...")
        self.progress_bar.setRange(0, 0)

        self.push_worker = PushWorker(self.db)
        self.push_worker.push_finished.connect(self.on_push_finished)
        self.push_worker.start()

    def on_vehicles_loaded(self, count: int) -> None:
        self.lbl_status.setText(f"Cached {count} vehicles locally.")
        self.fleet_view.refresh_data()
        self.inventory_view.refresh_data()

    def on_sync_finished(self, success: bool, message: str) -> None:
        """Callback when initial cache verification completes."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        
        # Verify physical credential existence before flagging connection
        if success and TOKEN_PATH.exists():
            self.lbl_status.setText("Cloud Sync: Up to Date")
            self.btn_auth.setText("✅ Google Connected")
            self.btn_auth.setStyleSheet("""
                QPushButton {
                    background-color: #313244;
                    color: #A6E3A1;
                    border: 1px solid #A6E3A1;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 11px;
                }
            """)
        else:
            self.lbl_status.setText("Local Cache Active (Offline)")
            self.btn_auth.setText("🔑 Connect Google Account")
            self.btn_auth.setStyleSheet("""
                QPushButton {
                    background-color: #313244;
                    color: #89B4FA;
                    border: 1px solid #45475A;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 11px;
                }
            """)

    def on_push_finished(self, success: bool, message: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        if success:
            self.lbl_status.setText("Cloud Sync: Up to Date")
        else:
            self.lbl_status.setText("Pending Upstream Push (Offline)")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FleetPortalApp()
    window.show()
    sys.exit(app.exec())