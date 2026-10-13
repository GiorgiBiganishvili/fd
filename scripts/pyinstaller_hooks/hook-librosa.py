"""Numba decorators need real source paths, not code inside a PYZ archive."""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

module_collection_mode = {"librosa": "py", "resampy": "py"}
datas = collect_data_files("librosa") + copy_metadata("librosa")
hiddenimports = collect_submodules("librosa")
