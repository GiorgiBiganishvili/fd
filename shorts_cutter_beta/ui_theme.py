from PySide6.QtGui import QFont

APP_STYLESHEET = r'''
QWidget {
    background: #0f1015;
    color: #f4f4f7;
    font-family: "Segoe UI";
    font-size: 13px;
}
QWidget#AppRoot {
    background: #0f1015;
}
QFrame#TopBar {
    background: #151720;
    border: 1px solid #262936;
    border-radius: 18px;
}
QLabel#LogoMark {
    background: #7c5cff;
    color: white;
    border-radius: 13px;
    font-size: 16px;
    font-weight: 900;
    padding: 9px 10px;
}
QLabel#AppTitle {
    font-size: 24px;
    font-weight: 800;
    color: #ffffff;
}
QLabel#AppSubtitle {
    color: #9ea3b2;
    font-size: 12px;
}
QLabel#VersionBadge {
    background: #211d38;
    color: #c7b9ff;
    border: 1px solid #4a3f7c;
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#SectionHint {
    color: #9298a8;
    font-size: 12px;
}
QGroupBox {
    background: #151720;
    border: 1px solid #272a36;
    border-radius: 14px;
    margin-top: 14px;
    padding: 16px 14px 14px 14px;
    font-weight: 700;
    color: #f4f4f7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: #cfd2dc;
}
QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QTableWidget, QSpinBox, QDoubleSpinBox {
    background: #11131a;
    border: 1px solid #2c3040;
    border-radius: 9px;
    padding: 7px 9px;
    selection-background-color: #7c5cff;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QComboBox:focus, QTableWidget:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #7c5cff;
}
QLineEdit[readOnly="true"] {
    color: #aeb3c0;
    background: #12141b;
}
QPushButton {
    background: #262a36;
    color: #f4f4f7;
    border: 1px solid #343948;
    border-radius: 9px;
    padding: 9px 14px;
    font-weight: 650;
}
QPushButton:hover {
    background: #303646;
    border-color: #454c60;
}
QPushButton:pressed {
    background: #20242f;
}
QPushButton:disabled {
    background: #191b22;
    color: #666b78;
    border-color: #22252e;
}
QPushButton#PrimaryButton {
    background: #7c5cff;
    border: 1px solid #8d73ff;
    color: #ffffff;
    font-weight: 800;
    padding: 11px 16px;
}
QPushButton#PrimaryButton:hover {
    background: #8a6aff;
}
QPushButton#SuccessButton {
    background: #1f7a55;
    border-color: #2b9169;
    color: white;
    font-weight: 800;
}
QPushButton#DangerButton {
    background: #43232a;
    border-color: #6d3540;
    color: #ffc6cf;
}
QCheckBox {
    spacing: 9px;
    color: #d8dbe4;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #414758;
    border-radius: 5px;
    background: #11131a;
}
QCheckBox::indicator:checked {
    background: #7c5cff;
    border-color: #7c5cff;
}
QTabWidget::pane {
    border: 1px solid #262936;
    border-radius: 14px;
    background: #12141b;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #8f95a5;
    border: 0;
    padding: 11px 18px;
    margin-right: 5px;
    font-weight: 700;
}
QTabBar::tab:selected {
    color: white;
    background: #242035;
    border-radius: 9px;
}
QTabBar::tab:hover:!selected {
    color: #d6d9e2;
    background: #171923;
    border-radius: 9px;
}
QListWidget::item {
    padding: 10px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget::item:selected {
    background: #27213f;
    color: white;
}
QHeaderView::section {
    background: #1a1d27;
    color: #bfc4d1;
    border: 0;
    border-bottom: 1px solid #303442;
    padding: 8px;
    font-weight: 700;
}
QTableWidget {
    gridline-color: #262a35;
}
QProgressBar {
    background: #171923;
    border: 1px solid #282c38;
    border-radius: 7px;
    min-height: 13px;
    max-height: 13px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #7c5cff;
    border-radius: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #353a49;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #484f62;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}
QToolTip {
    background: #222632;
    color: white;
    border: 1px solid #3b4152;
    padding: 6px;
}
'''


def apply_app_theme(app):
    app.setFont(QFont('Segoe UI', 10))
    app.setStyleSheet(APP_STYLESHEET)
