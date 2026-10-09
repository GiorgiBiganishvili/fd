from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QProgressBar, QPushButton

from main import Window


class StudioWindow(Window):
    """Presentation shell around the existing editing engine.

    Keeps the 0.3 workflow intact while replacing the rough beta chrome with a
    calmer, editor-like interface. All business logic still lives in Window.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Shorts Cutter 0.3.1 Beta')
        self.resize(1440, 920)
        self.setMinimumSize(1120, 760)

    def _build_ui(self):
        self.setObjectName('AppRoot')
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        top = QFrame()
        top.setObjectName('TopBar')
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(18, 14, 18, 14)
        top_lay.setSpacing(14)

        logo = QLabel('SC')
        logo.setObjectName('LogoMark')
        logo.setFixedSize(46, 46)
        logo.setAlignment(Qt.AlignCenter)
        top_lay.addWidget(logo)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title = QLabel('SHORTS CUTTER')
        title.setObjectName('AppTitle')
        subtitle = QLabel('Одна мысль → целостный Short → базовый монтаж')
        subtitle.setObjectName('AppSubtitle')
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        top_lay.addLayout(text_col)
        top_lay.addStretch(1)

        badge = QLabel('0.3.1  BETA')
        badge.setObjectName('VersionBadge')
        top_lay.addWidget(badge)
        root.addWidget(top)

        hint = QLabel('Рабочий процесс: анализ → транскрипт → монтаж → субтитры → экспорт')
        hint.setObjectName('SectionHint')
        root.addWidget(hint)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        self._analysis_tab()
        self._transcript_tab()
        self._montage_tab()
        self._captions_tab()

        # Make the main actions visually obvious without changing the workflow.
        self.analyze_btn.setObjectName('PrimaryButton')
        self.build_btn.setObjectName('PrimaryButton')
        self.analyze_btn.setMinimumHeight(44)
        self.build_btn.setMinimumHeight(44)
        self.cand_list.setMinimumWidth(410)
        self.cand_detail.setPlaceholderText('Здесь появится смысловая структура выбранного Short.')
        self.transcript.setPlaceholderText('После анализа здесь появится транскрипция выпуска.')

        for btn in self.findChildren(QPushButton):
            txt = btn.text().strip().upper()
            if txt == 'EXPORT FINISHED':
                btn.setObjectName('SuccessButton')
            elif txt in {'УДАЛИТЬ ПЕРЕБИВКУ', 'УБРАТЬ МУЗЫКУ'}:
                btn.setObjectName('DangerButton')

        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.status = QLabel('Готов')
        self.status.setObjectName('AppSubtitle')
        footer.addWidget(self.status)
        self.pb = QProgressBar()
        self.pb.setTextVisible(False)
        self.pb.setMaximumHeight(14)
        footer.addWidget(self.pb, 1)
        root.addLayout(footer)
