# Distribution dependencies

No datasets or user media are bundled. Retain notices for every distributed binary.

* PySide6/Qt: LGPLv3/GPLv3 or commercial license. Use dynamic one-directory builds,
  retain notices and satisfy the applicable replacement/relinking obligations.
* Basic Pitch/model: Spotify Apache-2.0; preserve LICENSE/NOTICE.
* ONNX Runtime: MIT. Optional MediaPipe: Apache-2.0, with separately supplied model.
* OpenCV and Tesseract: Apache-2.0, with corresponding traineddata notices.
* FFmpeg: exact build determines LGPL/GPL status. Include its matching license,
  source/source offer and configure information. Do not assume all builds have
  the same redistribution terms. The script copies user-provided tools.
* Preserve included notices from NumPy/SciPy/librosa/soundfile/pretty_midi and all
  transitive packages. The packaging script collects wheel license files in
  `third_party_licenses`; review the actual dependency inventory before release.

GuitarSet/IDMT datasets are not distributed. No automatic model downloads occur.
Use official TLS sources and published checksums for manually supplied models.
Analysis remains local; there is no cloud-upload path.
