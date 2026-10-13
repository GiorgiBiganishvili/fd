"""GUI entry point and optional local batch analysis for reproducible validation."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from guitar_tab_ai.core.config import AppConfig, data_directory
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.storage.project_storage import save_project


def configure_logging(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(root/"app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    # Redirected Windows consoles may use cp1252 while status messages are Russian.
    # pythonw/PyInstaller windowed executables have no standard streams.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Local guitar video transcription")
    parser.add_argument("project", nargs="?", type=Path)
    parser.add_argument("--analyze", type=Path)
    parser.add_argument("--output", type=Path, default=Path("analysis.gtabproject"))
    parser.add_argument("--backend", choices=["spectral", "basic-pitch"], default="spectral")
    parser.add_argument("--audio-only", action="store_true")
    args = parser.parse_args()
    root = data_directory()
    try:
        configure_logging(root)
    except OSError as exc:
        if args.analyze:
            print(f"Папка данных недоступна: {root}: {exc}", file=sys.stderr)
        else:
            from PySide6.QtWidgets import QApplication, QMessageBox
            error_app = QApplication([sys.argv[0]])
            QMessageBox.critical(None, "Папка данных недоступна",
                                 f"Невозможно записать данные в {root}.\n"
                                 "Укажите доступную папку через GTAB_DATA_DIR.\n"+str(exc))
            error_app.quit()
        return 1
    # Tools must also be available in packaged batch analysis, before imports.
    bundled = Path(getattr(sys, "_MEIPASS", ""))/"tools"
    if bundled.is_dir():
        import os
        os.environ["PATH"] = str(bundled)+os.pathsep+os.environ["PATH"]
        if (bundled/"tessdata").is_dir():
            os.environ["TESSDATA_PREFIX"] = str(bundled/"tessdata")
    if args.analyze:
        from guitar_tab_ai.workers.pipeline import analyze
        config = AppConfig(audio_backend=args.backend, ocr_enabled=not args.audio_only,
                           video_enabled=not args.audio_only)
        project = Project(title=args.analyze.stem, video_path=str(args.analyze.resolve()), settings=config)
        try:
            result = analyze(project, threading.Event(), lambda value, text: print(f"{value:.0%} {text}"))
            save_project(result, args.output)
            print(f"Saved {len(result.notes)} notes to {args.output}")
            return 0
        except Exception as exc:
            logging.exception("Batch analysis failed")
            print(str(exc), file=sys.stderr)
            return 1
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from guitar_tab_ai.app.window import MainWindow
    from guitar_tab_ai.app.theme import STYLE
    application = QApplication([sys.argv[0]])
    application.setApplicationName("Guitar Tab AI")
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    missing = [tool for tool in (window.config.ffmpeg, window.config.ffprobe) if shutil.which(tool) is None]
    if missing:
        QTimer.singleShot(0, lambda: QMessageBox.warning(window, "Первый запуск",
            "Не найдены FFmpeg/ffprobe. Установите их и добавьте в PATH либо укажите пути в config.yaml.\n"
            "Редактор и сохранение проектов доступны."))
    if args.project:
        QTimer.singleShot(0, lambda: window.open_project_path(args.project))
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
