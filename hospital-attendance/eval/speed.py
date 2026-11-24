"""Замер скорости этапов распознавания на сервере без видеокарты.

Запуск: python -m eval.speed --models /путь/к/моделям --lfw /путь/к/lfw
Кадр 640 x 480, как с камеры терминала; каждый замер – медиана 30 повторов после 3 прогревочных.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time

import cv2
import numpy as np

from recognition.align import norm_crop
from recognition.detectors import make_detector
from recognition.embedder import ArcFaceEmbedder
from recognition.engine import EngineConfig, FaceEngine
from recognition.liveness import MiniFasLiveness

HERE = os.path.dirname(os.path.abspath(__file__))
DETECTORS = [
    ('SCRFD-10G (buffalo_l)', 'scrfd', 'buffalo_l/det_10g.onnx'),
    ('SCRFD-0.5G (buffalo_s)', 'scrfd', 'buffalo_s/det_500m.onnx'),
    ('RetinaFace ResNet-34', 'retinaface', 'onnx/retinaface_r34.onnx'),
    ('RetinaFace MobileNetV2', 'retinaface', 'onnx/retinaface_mv2.onnx'),
    ('RetinaFace MobileNet-0.25', 'retinaface', 'onnx/retinaface_mv1_0.25.onnx'),
]
RECOGNIZERS = [('ArcFace ResNet-50 (w600k_r50)', 'buffalo_l/w600k_r50.onnx'),
               ('ArcFace MobileFaceNet (w600k_mbf)', 'buffalo_s/w600k_mbf.onnx')]


def timeit(fn, n=30, warm=3):
    for _ in range(warm):
        fn()
    ts = []
    for _ in range(n):
        t = time.perf_counter(); fn(); ts.append(time.perf_counter() - t)
    return round(statistics.median(ts) * 1000, 1)


def make_frame(lfw, person='Azra_Akin', i=2):
    f = np.full((480, 640, 3), 90, np.uint8)
    face = cv2.resize(cv2.imread(os.path.join(lfw, person, f'{person}_{i:04d}.jpg')), (375, 375))
    f[52:427, 132:507] = face
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', required=True)
    ap.add_argument('--lfw', required=True)
    ap.add_argument('--out', default=os.path.join(HERE, 'results', 'speed.json'))
    a = ap.parse_args()
    frame = make_frame(a.lfw)
    res = {'cpu': platform.processor() or platform.machine(), 'cores': os.cpu_count(), 'detectors': {},
           'recognizers': {}}
    with open('/proc/cpuinfo') as f:
        for line in f:
            if line.startswith('model name'):
                res['cpu'] = line.split(':', 1)[1].strip(); break
    for name, kind, path in DETECTORS:
        for size in (640, 320):
            det = make_detector(kind, os.path.join(a.models, path), size)
            found = len(det.detect(frame))
            res['detectors'][f'{name} @{size}'] = {'ms': timeit(lambda: det.detect(frame)), 'faces': found,
                                                   'file_mb': round(os.path.getsize(os.path.join(a.models, path)) / 2**20, 1)}
            print(name, size, res['detectors'][f'{name} @{size}'], flush=True)
    det = make_detector('scrfd', os.path.join(a.models, 'buffalo_l/det_10g.onnx'))
    face = det.detect(frame)[0]
    aligned = norm_crop(frame, face.kps)
    for name, path in RECOGNIZERS:
        emb = ArcFaceEmbedder(os.path.join(a.models, path))
        res['recognizers'][name] = {'ms': timeit(lambda: emb.embed(aligned)),
                                    'file_mb': round(os.path.getsize(os.path.join(a.models, path)) / 2**20, 1)}
        print(name, res['recognizers'][name], flush=True)
    live = MiniFasLiveness(os.path.join(a.models, 'onnx/minifasnet_v2.onnx'))
    res['liveness_ms'] = timeit(lambda: live.score(frame, face.bbox))
    res['align_ms'] = timeit(lambda: norm_crop(frame, face.kps))
    # полный цикл обращения к терминалу: 1 и 3 кадра, галерея 300 сотрудников
    eng = FaceEngine(EngineConfig(models_dir=a.models))
    rng = np.random.default_rng(0)
    eng.gallery.load([(i, rng.normal(size=512).astype(np.float32)) for i in range(1, 301)])
    res['end_to_end_ms'] = {'1 кадр': timeit(lambda: eng.identify([frame]), n=15),
                            '3 кадра': timeit(lambda: eng.identify([frame] * 3), n=10)}
    eng320 = FaceEngine(EngineConfig(models_dir=a.models, det_size=320))
    eng320.gallery = eng.gallery
    res['end_to_end_ms']['3 кадра, детектор 320'] = timeit(lambda: eng320.identify([frame] * 3), n=10)
    print(res['end_to_end_ms'], flush=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
