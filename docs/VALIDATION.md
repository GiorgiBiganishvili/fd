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

## TAB readability and candidate filtering correction

The original default spectral mode produced excessive candidates on complex
audio, and duration rectangles made adjacent fret labels unreadable. Auto mode
now selects bundled Basic Pitch; spectral mode remains available. Transcribers
limit detection to the selected tuning/capo/fret range. The spectral baseline
rejects broadband noise using spectral flatness and requires stronger peaks.
Before fingering, candidates below the user threshold, under 100 ms, outside
the guitar range, and overlapping duplicate pitches are excluded. The optional
melody profile selects one concurrent note; the polyphonic profile retains
chords. Raw candidates remain cached; the cache version changed so previous
spectral results cannot silently reappear on reanalysis.

Fret labels sit at attacks on labeled strings, with thin sustain traces.
Uncertainty uses amber text and tooltips. At low zoom densely spaced attacks
become dots; zoom restores digits. Unassigned notes remain in the project and
review controls rather than creating a seventh row of asterisks.

48 tests passed, including actual Basic Pitch inference, synthetic plucked-note
harmonics plus broadband noise, candidate filtering, chord preservation,
monophonic selection, GUI editing/playback, and dense-label geometry. These tests
do not demonstrate accuracy on the user's screenshot recording: its audio and
reference TAB were not supplied. This correction does not implement source
separation or guarantee guitar-only output from a full song mix.

The updated Windows EXE (SHA256 `4a926e3c49de9b330807bc9d00f34c9af18b5bfe9caa050136d6d76901817da0`) independently
analyzed the six-note MP4 using automatic Basic Pitch selection and preserved
the six expected pitches/open-string fingerings. Its GUI opened the result and
remained responsive after playback under Wine/Xvfb.
