"""Compact native-widget desktop theme."""
STYLE = """
QMainWindow, QDialog, QWidget { background: #182332; color: #dce6ef; }
QMenuBar, QMenu { background: #202e40; color: #dce6ef; }
QMenuBar::item:selected, QMenu::item:selected { background: #355267; }
QLabel { background: transparent; }
QPushButton { background: #2b4154; border: 1px solid #3d566b; padding: 7px 11px; border-radius: 4px; }
QPushButton:hover { background: #36596e; }
QPushButton:disabled { color: #728092; background: #202d3b; border-color: #2a3a4b; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {
    background: #101c29; border: 1px solid #3a4c5e; padding: 4px; border-radius: 3px;
    selection-background-color: #347e86;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { min-height: 22px; }
QProgressBar { border: 1px solid #3a4c5e; border-radius: 4px; text-align: center; background: #101c29; }
QProgressBar::chunk { background: #318b82; }
QSlider::groove:horizontal { height: 4px; background: #3a4c5e; border-radius: 2px; }
QSlider::handle:horizontal { background: #65cab4; width: 12px; margin: -5px 0; border-radius: 5px; }
QScrollBar:horizontal { height: 12px; background: #101c29; }
QScrollBar::handle:horizontal { background: #435c70; min-width: 30px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #51687d; background: #101c29; }
QCheckBox::indicator:checked { background: #45a48e; }
QToolTip { color: #e1ebef; background: #22384a; border: 1px solid #486579; }
"""
