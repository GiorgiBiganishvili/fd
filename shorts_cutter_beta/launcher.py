import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui_shell import StudioWindow
from ui_theme import apply_app_theme


def resource_path(*parts):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    return base.joinpath(*parts)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Shorts Cutter')
    app.setOrganizationName('Shorts Cutter')
    apply_app_theme(app)

    icon_path = resource_path('assets', 'shorts_cutter.svg')
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    w = StudioWindow()
    if icon_path.exists():
        w.setWindowIcon(QIcon(str(icon_path)))
    w.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
