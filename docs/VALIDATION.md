# Validation report

Validated in the Linux x86_64 cloud instance with Python 3.11.17.

* **44 passed, 0 failed, 0 errors, 0 skipped** in the final pytest run.
* `ruff check src tests scripts` and `git diff --check` passed.
* `uv pip check` confirmed installed dependency compatibility, including optional ML/hands.
* `scripts/cloud_setup.sh` ran successfully and can be repeated using `uv.lock`.
* Real Basic Pitch ONNX inference and real Tesseract recognition ran in tests.
* A synthetic MP4 containing E2/A2/D3/G3/B3/E4 was analyzed by the complete
  pipeline, producing six notes and a saved `.gtabproject`.
* Qt tests exercised background analysis and actual video playback, plus editor
  moves, undo/redo, note dialogs, project/export paths and PNG/PDF generation.
* A PyInstaller Linux standalone distribution was built. Its Basic Pitch batch
  analysis of the MP4 succeeded; the saved project was independently loaded and
  checked for all six expected MIDI pitches and valid string/fret positions.
* The packaged runtime includes source-file hooks for librosa/resampy: their JIT
  decorators require real source filenames rather than only archived bytecode.

The third-party resampy/audioread dependencies emit four deprecation warnings;
setuptools is constrained below 81 because resampy currently uses pkg_resources.
TLS verification and package checksums were never disabled.

Additional Windows executable validation:

* Windows CPython 3.11.17 AMD64 and locked Windows wheels were prepared under Wine 10.
  Original package SHA256 hashes were checked. Wine packages came from signed Debian metadata.
* A genuine PE32+ x64 `dist/GuitarTabAI.exe` was produced by Windows PyInstaller
  in single-file GUI mode. Python, the ONNX model, Qt and FFmpeg/ffprobe are embedded.
* FFmpeg's Windows LGPL archive SHA256 matched its publisher's checksum manifest.
* The final `.exe`, independently of the builder Python, successfully analyzed
  the test MP4 through its embedded FFmpeg and Basic Pitch. The resulting project
  was loaded separately and verified to contain E2/A2/D3/G3/B3/E4 on six valid strings.
* The final `.exe` created its native Qt main window, opened the saved project,
  and remained responsive after a playback command under Wine/Xvfb. Required
  Qt platform/multimedia plugins and codec DLLs are explicitly retained in the build.
* The existing 44 tests and lint still pass after Windows console UTF-8 handling was added.

Not validated here: Windows installer/install/uninstall or playback on a
clean Windows host; actual hand-landmark model inference (no local model was
supplied, and the official storage.googleapis.com download received proxy HTTP
403); accuracy on real annotated guitar performances. MediaPipe Tasks API imports
successfully, but that alone does not validate tracking. OCR/CV remain conservative
heuristics. Automatic guitar techniques and the future modules listed in
ARCHITECTURE.md are not advertised as implemented.

The Windows workflow and build scripts are prepared for that platform's checks.
The reusable cloud install/start configuration was saved as a draft. It has not
been published, and fresh-task snapshot restoration has not been independently tested.
