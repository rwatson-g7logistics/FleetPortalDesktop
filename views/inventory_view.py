"""
views/inventory_view.py
------------------------
Parts & Tire Inventory Management View for G7 Fleet Portal Desktop.
Provides live stock monitoring, low-stock visual badges, batch quantity 
increment/decrement controls, direct reorder links, and item management forms.
"""

from typing import Dict, Any, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QSpinBox,
    QComboBox, QGroupBox, QMessageBox, QHeaderView, QFrame,
    QDialog, QFormLayout
)
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QFont, QColor, QDesktopServices

from db_manager import DatabaseManager
from utils.platform_helper import get_default_font_family


class ItemEditDialog(QDialog):
    """Modal dialog to edit or remove an existing inventory item."""

    def __init__(self, db_manager: DatabaseManager, item_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.item = item_data
        self.init_ui()

    def init_ui(self) -> None:
        """Constructs the edit item modal window."""
        self.setWindowTitle(f"Edit Inventory Item — {self.item.get('item_name', '')}")
        self.setFixedSize(400, 320)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.txt_name = QLineEdit(self.item.get('item_name', ''))
        self.cmb_cat = QComboBox()
        self.cmb_cat.addItems(["Tires", "Fluids", "Parts", "Tools", "General"])
        self.cmb_cat.setCurrentText(self.item.get('category', 'General'))

        self.spin_qty = QSpinBox()
        self.spin_qty.setRange(0, 10000)
        self.spin_qty.setValue(int(self.item.get('quantity', 0)))

        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(1, 1000)
        self.spin_threshold.setValue(int(self.item.get('min_threshold', 2)))

        self.txt_link = QLineEdit(self.item.get('reorder_link', ''))
        self.txt_notes = QLineEdit(self.item.get('notes', ''))

        for widget in [self.txt_name, self.cmb_cat, self.spin_qty, self.spin_threshold, self.txt_link, self.txt_notes]:
            widget.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 4px; padding: 5px;")

        form_layout.addRow("Item Name:", self.txt_name)
        form_layout.addRow("Category:", self.cmb_cat)
        form_layout.addRow("Quantity:", self.spin_qty)
        form_layout.addRow("Min Threshold:", self.spin_threshold)
        form_layout.addRow("Reorder URL:", self.txt_link)
        form_layout.addRow("Notes:", self.txt_notes)

        layout.addLayout(form_layout)

        # Action Buttons
        btn_box = QHBoxLayout()
        btn_save = QPushButton("💾 Update Item")
        btn_save.setStyleSheet("background-color: #89B4FA; color: #11111B; font-weight: bold; padding: 8px;")
        btn_save.clicked.connect(self.save_changes)

        btn_delete = QPushButton("🗑️ Delete")
        btn_delete.setStyleSheet("background-color: #F38BA8; color: #11111B; font-weight: bold; padding: 8px;")
        btn_delete.clicked.connect(self.delete_item)

        btn_box.addWidget(btn_delete)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

    def save_changes(self) -> None:
        """Persists updated item properties to local SQLite."""
        updated_data = {
            "id": self.item['id'],
            "item_name": self.txt_name.text().strip(),
            "category": self.cmb_cat.currentText(),
            "quantity": self.spin_qty.value(),
            "min_threshold": self.spin_threshold.value(),
            "reorder_link": self.txt_link.text().strip(),
            "notes": self.txt_notes.text().strip()
        }
        self.db.update_inventory_item(updated_data)
        self.accept()

    def delete_item(self) -> None:
        """Deletes item from SQLite database after user confirmation."""
        reply = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to permanently remove '{self.item.get('item_name')}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.delete_inventory_item(self.item['id'])
            self.accept()


class InventoryView(QWidget):
    """Main inventory tracking view for managing tires, parts, and consumables."""

    # Signal emitted when inventory stock is modified
    inventory_updated = Signal()

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.init_ui()
        self.refresh_data()

    def init_ui(self) -> None:
        """Constructs the inventory layout, grid, and item creation panel."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- 1. HEADER ---
        header_layout = QHBoxLayout()
        lbl_title = QLabel("📦 Bulk Tires & Parts Inventory Tracker")
        lbl_title.setFont(QFont(get_default_font_family(), 18, QFont.Bold))
        lbl_title.setStyleSheet("color: #CDD6F4;")
        header_layout.addWidget(lbl_title)

        header_layout.addStretch()

        btn_add = QPushButton("➕ Add New Item")
        btn_add.setFixedHeight(35)
        btn_add.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 6px; padding: 0 15px;")
        btn_add.clicked.connect(self.open_add_item_dialog)
        header_layout.addWidget(btn_add)

        main_layout.addLayout(header_layout)

        # --- 2. INVENTORY TABLE ---
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Item Name", "Category", "On Hand", "Min Qty", "Status", "Batch Step", "Actions"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1E1E2E;
                color: #CDD6F4;
                gridline-color: #313244;
                border: none;
                border-radius: 8px;
            }
            QHeaderView::section {
                background-color: #181825;
                color: #89B4FA;
                padding: 8px;
                font-weight: bold;
                border: none;
            }
        """)
        main_layout.addWidget(self.table)

    def refresh_data(self) -> None:
        """Fetches current inventory from local SQLite cache and renders rows."""
        self.inventory_df = self.db.get_inventory()
        self.render_table()

    def render_table(self) -> None:
        """Populates inventory data rows into the table widget."""
        if self.inventory_df.empty:
            self.table.setRowCount(0)
            return

        self.table.setRowCount(len(self.inventory_df))

        for row_idx, (_, item) in enumerate(self.inventory_df.iterrows()):
            item_id = item.get('id')
            item_name = str(item.get('item_name', ''))
            category = str(item.get('category', 'General'))
            quantity = int(item.get('quantity', 0))
            min_threshold = int(item.get('min_threshold', 2))
            reorder_link = str(item.get('reorder_link', ''))

            # Status Badge
            is_low = quantity <= min_threshold
            status_text = "🔴 LOW STOCK" if is_low else "🟢 OK"

            self.table.setItem(row_idx, 0, QTableWidgetItem(item_name))
            self.table.setItem(row_idx, 1, QTableWidgetItem(category))
            
            # Highlight On Hand quantity if low
            qty_item = QTableWidgetItem(str(quantity))
            if is_low:
                qty_item.setForeground(QColor("#F38BA8"))
                qty_item.setFont(QFont(get_default_font_family(), 10, QFont.Bold))
            self.table.setItem(row_idx, 2, qty_item)

            self.table.setItem(row_idx, 3, QTableWidgetItem(str(min_threshold)))
            self.table.setItem(row_idx, 4, QTableWidgetItem(status_text))

            # Batch Step Widget
            spin_step = QSpinBox()
            spin_step.setRange(1, 100)
            spin_step.setValue(1)
            spin_step.setFixedWidth(60)
            spin_step.setStyleSheet("background-color: #313244; color: #CDD6F4; border-radius: 4px;")
            self.table.setCellWidget(row_idx, 5, spin_step)

            # Actions Container (+ / - / Buy / Edit)
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            action_layout.setSpacing(4)

            btn_inc = QPushButton("➕")
            btn_inc.setFixedWidth(30)
            btn_inc.setStyleSheet("background-color: #A6E3A1; color: #11111B; font-weight: bold; border-radius: 4px;")
            btn_inc.clicked.connect(lambda _, i=item_name, q=quantity, s=spin_step: self.adjust_quantity(i, q, s.value()))

            btn_dec = QPushButton("➖")
            btn_dec.setFixedWidth(30)
            btn_dec.setStyleSheet("background-color: #F38BA8; color: #11111B; font-weight: bold; border-radius: 4px;")
            btn_dec.clicked.connect(lambda _, i=item_name, q=quantity, s=spin_step: self.adjust_quantity(i, q, -s.value()))

            action_layout.addWidget(btn_inc)
            action_layout.addWidget(btn_dec)

            if reorder_link and reorder_link.startswith("http"):
                btn_buy = QPushButton("🛒")
                btn_buy.setFixedWidth(30)
                btn_buy.setStyleSheet("background-color: #89B4FA; color: #11111B; border-radius: 4px;")
                btn_buy.clicked.connect(lambda _, url=reorder_link: QDesktopServices.openUrl(QUrl(url)))
                action_layout.addWidget(btn_buy)

            btn_edit = QPushButton("✏️")
            btn_edit.setFixedWidth(30)
            btn_edit.setStyleSheet("background-color: #45475A; color: #CDD6F4; border-radius: 4px;")
            btn_edit.clicked.connect(lambda _, d=item.to_dict(): self.open_edit_item_dialog(d))
            action_layout.addWidget(btn_edit)

            self.table.setCellWidget(row_idx, 6, action_widget)

    def adjust_quantity(self, item_name: str, current_qty: int, delta: int) -> None:
        """Applies batch quantity changes directly to SQLite."""
        new_qty = max(0, current_qty + delta)
        self.db.update_item_quantity(item_name, new_qty)
        self.refresh_data()
        self.inventory_updated.emit()

    def open_add_item_dialog(self) -> None:
        """Opens modal dialog for adding a brand new inventory item."""
        dialog = ItemEditDialog(self.db, {"item_name": "", "category": "Tires", "quantity": 4, "min_threshold": 2}, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_data()

    def open_edit_item_dialog(self, item_dict: Dict[str, Any]) -> None:
        """Opens modal dialog to edit an existing item."""
        dialog = ItemEditDialog(self.db, item_dict, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_data()