"""Сравнение детекторов на лицах без маски и в нарисованной медицинской маске (LFW).

Запуск: python -m eval.detect_masks --lfw /путь/к/lfw --models /путь/к/моделям --n 500
Лицо считается найденным, если центр рамки детектора лежит не дальше 25 пикселей
от центра снимка LFW (набор центрирован по лицу) и пять ключевых точек внутри рамки.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
import zlib

import cv2
import numpy as np

from recognition.detectors import make_detector

from .masks import MaskPainter
from .speed import DETECTORS

HERE = os.path.dirname(os.path.abspath(__file__))


def found(faces, img):
    c = np.array(img.shape[1::-1]) / 2
    for f in faces:
        center = (f.bbox[:2] + f.bbox[2:4]) / 2
        if np.linalg.norm(center - c) <= 25:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lfw', required=True)
    ap.add_argument('--models', required=True)
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--out', default=os.path.join(HERE, 'results', 'detect_masks.json'))
    a = ap.parse_args()
    rnd = random.Random(7)
    files = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(a.lfw) for f in fs if f.endswith('.jpg'))
    files = rnd.sample(files, a.n)
    ref = make_detector('scrfd', os.path.join(a.models, 'buffalo_l/det_10g.onnx'), 320)
    painter = MaskPainter(os.path.join(a.models, 'buffalo_l/2d106det.onnx'))
    plain, masked = [], []
    for p in files:
        img = cv2.imread(p)
        faces = ref.detect(img)
        if not faces or not found(faces, img):
            continue                     # опорный детектор не нашел лицо без маски – снимок не используем
        c = np.array(img.shape[1::-1]) / 2
        f = min(faces, key=lambda x: np.linalg.norm((x.bbox[:2] + x.bbox[2:4]) / 2 - c))
        pts = painter.landmarks(img, f.bbox, f.kps)
        color = 'blue' if zlib.crc32(p.encode()) % 2 else 'white'
        plain.append(img)
        masked.append(painter.paint(img, pts, color))
    res = {'images': len(plain), 'detectors': {}}
    for name, kind, path in DETECTORS:
        det = make_detector(kind, os.path.join(a.models, path), 640)
        t0 = time.time()
        ok_p = sum(found(det.detect(i), i) for i in plain)
        ok_m = sum(found(det.detect(i), i) for i in masked)
        res['detectors'][name] = {'plain': ok_p / len(plain), 'mask': ok_m / len(masked),
                                  'seconds': round(time.time() - t0)}
        print(name, res['detectors'][name], flush=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
