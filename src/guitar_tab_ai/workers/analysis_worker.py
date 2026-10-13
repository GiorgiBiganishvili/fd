"""One QThread owns each analysis; errors are returned without closing the app."""
import logging
import threading

from PySide6.QtCore import QThread, Signal

from guitar_tab_ai.audio.extractor import Cancelled
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.workers.pipeline import analyze

log = logging.getLogger(__name__)


class AnalysisWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, project: Project, selection: tuple[float, float] | None = None):
        super().__init__()
        self.project = project.model_copy(deep=True)
        self.selection = selection
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            result = analyze(self.project, self.cancel_event,
                             lambda value, message: self.progress.emit(round(value*100), message),
                             self.selection)
            self.completed.emit(result)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            log.exception("Analysis failed")
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self.cancel_event.set()
