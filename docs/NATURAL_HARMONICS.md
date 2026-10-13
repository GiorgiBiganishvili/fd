# Natural harmonics: corrected data and notation

A fret number is a touch location, not necessarily a semitone offset. Natural
harmonic nodes 12, 7/19, and 5/24 sound at the second, third, and fourth partial:
12, approximately 19, and 24 semitones above the open/capoed string. Positions
remain relative to the capo. Common nodes only are supported; the third partial
is rounded to MIDI's equal-tempered semitone for MIDI/export purposes.

The high E string's ordinary fret 5 is A4 (69), its natural harmonic at 12 is
E5 (76), and its natural harmonic at 5 is E6 (88). Substituting an ordinary fret
number for a harmonic touch is therefore a data error, not a display choice.

The editor, pitch updates, fingering candidates, fusion, manual moves, and
tuning changes now respect natural harmonic pitch. TXT/PNG/PDF/editor notation
uses `<12>`. MusicXML carries a diamond notehead, `harmonic/natural`, and
`sounding-pitch` with the touching fret; MIDI keeps the actual sounding pitch.
The MusicXML representation was checked against the W3C MusicXML schema:
https://github.com/w3c/musicxml/blob/master/schema/musicxml.xsd

Synchronized OCR can read an explicitly bracketed harmonic. Fusion can use
explicit harmonic evidence when its sounding pitch agrees with audio. A
visible finger near fret 12 alone cannot distinguish a stopped octave from a
natural harmonic, since both have the same pitch. The code does not claim to
automatically classify that technique from uncalibrated hand footage. Ordinary
MediaPipe fingertip observations do not carry harmonic-specific evidence. A
strong conflicting audio pitch remains flagged rather than being arbitrarily
relabelled. The UI explicitly states when video-to-fret tracking is inactive.

These changes do not yet fix or validate the user's specific performance. The
uploaded full MP4 could not be transferred to the executor because it exceeds
the 32 MiB upload-transfer limit. A smaller excerpt or accessible original link
is required to inspect the reported event near 5:22. No new executable release
has been advertised for this correction before that case is investigated.
