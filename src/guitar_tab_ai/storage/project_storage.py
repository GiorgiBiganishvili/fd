"""Atomic ZIP project storage. Media is referenced, never uploaded or duplicated."""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path

from guitar_tab_ai.core.project import Project

MAX_PROJECT_BYTES = 32 * 1024 * 1024


def save_project(project: Project, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = project.model_dump(mode="json")
    if project.video_path:
        try:
            data["video_path"] = os.path.relpath(Path(project.video_path).resolve(), path.parent.resolve())
        except ValueError:  # different Windows drives
            data["video_path"] = str(Path(project.video_path).resolve())
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("project.json", json.dumps(data, ensure_ascii=False, allow_nan=False))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_project(path: Path) -> Project:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("project.json")
            if info.file_size > MAX_PROJECT_BYTES:
                raise ValueError("Project exceeds the 32 MB limit")
            data = json.loads(archive.read(info))
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("Повреждённый файл проекта") from exc
    if not isinstance(data, dict):
        raise ValueError("Invalid project document")
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported project version")
    project = Project.model_validate(data)
    if project.video_path and not Path(project.video_path).is_absolute():
        project.video_path = str((path.parent / project.video_path).resolve())
    return project
