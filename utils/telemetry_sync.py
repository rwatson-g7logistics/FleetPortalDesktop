"""
utils/telemetry_sync.py
-----------------------
Reusable two-way telemetry converters and widget synchronizers.
Handles cross-updating spinboxes (Brake MM <-> %) while preventing
recursive Qt signal feedback loops.
"""

from PySide6.QtWidgets import QSpinBox


def link_brake_spinboxes(spin_mm: QSpinBox, spin_pct: QSpinBox, max_usable_mm: float = 12.0) -> None:
    """
    Connects a pad thickness millimeter spinbox and a pad percentage spinbox.
    Changing either one calculates and updates the other without infinite recursion.
    Assumes standard commercial delivery van pad thickness: 12 mm = 100% usable friction material.
    """
    def mm_to_pct() -> None:
        val_mm = spin_mm.value()
        calc_pct = int(min(100, max(0, round((val_mm / max_usable_mm) * 100.0))))
        spin_pct.blockSignals(True)
        spin_pct.setValue(calc_pct)
        spin_pct.blockSignals(False)

    def pct_to_mm() -> None:
        val_pct = spin_pct.value()
        calc_mm = int(min(int(max_usable_mm), max(0, round((val_pct * max_usable_mm) / 100.0))))
        spin_mm.blockSignals(True)
        spin_mm.setValue(calc_mm)
        spin_mm.blockSignals(False)

    spin_mm.valueChanged.connect(mm_to_pct)
    spin_pct.valueChanged.connect(pct_to_mm)