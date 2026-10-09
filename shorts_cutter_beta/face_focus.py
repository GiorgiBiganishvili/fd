import sys
from pathlib import Path

import cv2
import numpy as np


def _base_dir():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).parent))


def model_path(name):
    p = _base_dir() / 'models' / name
    if not p.exists():
        raise RuntimeError(f'Не найдена модель распознавания лица: {p.name}')
    return str(p)


class TargetFaceAnalyzer:
    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(
            model_path('face_detection_yunet_2023mar_int8.onnx'),
            '', (320, 320), 0.72, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            model_path('face_recognition_sface_2021dec_int8.onnx'), ''
        )

    def _prepare(self, frame, max_width=960):
        h, w = frame.shape[:2]
        if w <= max_width:
            return frame, 1.0
        scale = max_width / float(w)
        resized = cv2.resize(frame, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
        return resized, scale

    def _detect(self, frame):
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        return [f for f in faces if float(f[14]) >= 0.72]

    def _feature(self, frame, face):
        try:
            aligned = self.recognizer.alignCrop(frame, face)
            feat = self.recognizer.feature(aligned)
            return feat, aligned
        except Exception:
            return None, None

    def reference_feature(self, photo_path):
        image = cv2.imread(str(photo_path))
        if image is None:
            raise RuntimeError('Не удалось открыть фотографию для распознавания лица.')
        image, _ = self._prepare(image, max_width=1400)
        faces = self._detect(image)
        if not faces:
            raise RuntimeError('На выбранной фотографии лицо не найдено. Выбери фото, где лицо видно прямо и достаточно крупно.')
        face = max(faces, key=lambda f: float(f[2] * f[3]))
        feat, _ = self._feature(image, face)
        if feat is None:
            raise RuntimeError('Не удалось построить отпечаток лица по фотографии.')
        return feat

    def _best_match(self, frame, ref_feature):
        faces = self._detect(frame)
        best = None
        second = -1.0
        for face in faces:
            feat, aligned = self._feature(frame, face)
            if feat is None:
                continue
            sim = float(self.recognizer.match(ref_feature, feat, cv2.FaceRecognizerSF_FR_COSINE))
            if best is None or sim > best['similarity']:
                if best is not None:
                    second = max(second, best['similarity'])
                best = {'face': face, 'similarity': sim, 'aligned': aligned}
            else:
                second = max(second, sim)
        if best is None:
            return None
        best['margin'] = best['similarity'] - second if second >= 0 else 1.0
        if best['similarity'] < 0.30:
            return None
        if second >= 0 and best['margin'] < 0.035 and best['similarity'] < 0.42:
            return None
        return best

    def scan(self, video_path, photo_path, start=0.0, end=None, sample_fps=2.5, progress=None):
        ref = self.reference_feature(photo_path)
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError('Не удалось открыть видео для поиска выбранного лица.')
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
        if end is None:
            end = duration
        end = max(start, float(end or duration))
        step = 1.0 / max(0.5, float(sample_fps))
        total = max(1, int((end - start) / step) + 1)
        samples = []
        prev_mouth = None
        prev_t = None
        visible_motion = []

        t = float(start)
        idx = 0
        while t <= end + 1e-6:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                samples.append({'t': t, 'visible': False, 'motion': 0.0})
                t += step
                idx += 1
                continue
            small, _ = self._prepare(frame)
            match = self._best_match(small, ref)
            if match is None:
                samples.append({'t': t, 'visible': False, 'motion': 0.0})
                prev_mouth = None
                prev_t = None
            else:
                face = match['face']
                x, y, w, h = [float(v) for v in face[:4]]
                aligned = match['aligned']
                gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
                mouth = cv2.resize(gray[56:108, 18:94], (76, 52), interpolation=cv2.INTER_AREA)
                motion = 0.0
                if prev_mouth is not None and prev_t is not None and (t - prev_t) <= step * 1.8:
                    motion = float(np.mean(cv2.absdiff(mouth, prev_mouth))) / 255.0
                    visible_motion.append(motion)
                prev_mouth = mouth
                prev_t = t
                sh, sw = small.shape[:2]
                samples.append({
                    't': t,
                    'visible': True,
                    'similarity': float(match['similarity']),
                    'motion': motion,
                    'cx': (x + w * 0.5) / sw,
                    'cy': (y + h * 0.5) / sh,
                    'fw': w / sw,
                    'fh': h / sh,
                })
            idx += 1
            if progress and idx % 10 == 0:
                progress(min(1.0, idx / total))
            t += step

        cap.release()
        motions = np.asarray(visible_motion, dtype=np.float32)
        if motions.size:
            p55 = float(np.percentile(motions, 55))
            p75 = float(np.percentile(motions, 75))
            threshold = max(0.010, min(0.060, p55 * 0.70 + p75 * 0.30))
        else:
            threshold = 0.018
        coverage = sum(1 for s in samples if s.get('visible')) / max(1, len(samples))
        return {
            'source_width': src_w,
            'source_height': src_h,
            'duration': duration,
            'motion_threshold': threshold,
            'coverage': coverage,
            'samples': samples,
        }


def mark_target_words(words, scan):
    samples = scan.get('samples') or []
    if not samples:
        return [dict(w, target_score=0.0, target_speaker=False) for w in words]
    times = np.array([float(s['t']) for s in samples], dtype=np.float32)
    threshold = float(scan.get('motion_threshold', 0.018))
    out = []
    for w in words:
        mid = (float(w['start']) + float(w['end'])) * 0.5
        lo = int(np.searchsorted(times, mid - 0.65, side='left'))
        hi = int(np.searchsorted(times, mid + 0.65, side='right'))
        near = samples[lo:hi]
        visible = [s for s in near if s.get('visible')]
        if not visible:
            score = 0.0
        else:
            max_motion = max(float(s.get('motion', 0.0)) for s in visible)
            best_sim = max(float(s.get('similarity', 0.0)) for s in visible)
            if threshold <= 1e-6:
                motion_score = 0.0
            else:
                motion_score = (max_motion - threshold * 0.55) / (threshold * 1.15)
            motion_score = max(0.0, min(1.0, motion_score))
            sim_score = max(0.0, min(1.0, (best_sim - 0.28) / 0.18))
            score = motion_score * (0.65 + 0.35 * sim_score)
        nw = dict(w)
        nw['target_score'] = round(float(score), 3)
        nw['target_speaker'] = bool(score >= 0.45)
        out.append(nw)
    return out


def target_ratio(words, start, end):
    seg = [w for w in words if float(w['end']) >= start and float(w['start']) <= end]
    if not seg:
        return 0.0
    vals = [float(w.get('target_score', 0.0)) for w in seg]
    return float(sum(vals) / len(vals))


def estimate_crop(scan, start, end):
    samples = [
        s for s in (scan.get('samples') or [])
        if s.get('visible') and start - 0.5 <= float(s['t']) <= end + 0.5
    ]
    if len(samples) < 2:
        raise RuntimeError('Не удалось надёжно найти выбранное лицо в этом фрагменте. Попробуй другое фото или другой отрезок.')
    src_w = int(scan.get('source_width') or 0)
    src_h = int(scan.get('source_height') or 0)
    if src_w <= 0 or src_h <= 0:
        raise RuntimeError('Не удалось определить размер исходного видео.')

    cx = float(np.median([s['cx'] for s in samples])) * src_w
    cy = float(np.median([s['cy'] for s in samples])) * src_h
    face_h = float(np.median([s['fh'] for s in samples])) * src_h
    similarity = float(np.median([s.get('similarity', 0.0) for s in samples]))

    crop_h = max(360.0, face_h * 4.2)
    crop_h = min(float(src_h), crop_h)
    crop_w = crop_h * 9.0 / 16.0
    if crop_w > src_w:
        crop_w = float(src_w)
        crop_h = crop_w * 16.0 / 9.0
    crop_w = max(180.0, min(float(src_w), crop_w))
    crop_h = max(320.0, min(float(src_h), crop_h))

    x = cx - crop_w * 0.5
    y = cy - crop_h * 0.30
    x = max(0.0, min(float(src_w) - crop_w, x))
    y = max(0.0, min(float(src_h) - crop_h, y))

    def even(v):
        return max(2, int(v) // 2 * 2)

    return {
        'x': even(x),
        'y': even(y),
        'w': even(crop_w),
        'h': even(crop_h),
        'similarity': similarity,
        'match_count': len(samples),
    }
