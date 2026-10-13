"""Retain packaged resampling filters and real JIT source filenames."""
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

module_collection_mode = "py"
datas = collect_data_files("resampy") + copy_metadata("resampy")
