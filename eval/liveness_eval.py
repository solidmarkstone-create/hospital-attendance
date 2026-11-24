"""Проверка модели «живости» MiniFASNetV2 на выборке CelebA-Spoof.

Запуск: python -m eval.liveness_eval --parquet valid-00000-of-00009.parquet --models /путь/к/моделям
Метрики по ГОСТ Р 71414.1-2024 / ISO/IEC 30107-3: APCER – доля атак (фото, экран),
принятых за живое лицо; BPCER – доля живых лиц, ошибочно отвергнутых.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import time

import cv2
import numpy as np
import pyarrow.parquet as pq

from recognition.detectors import make_detector
from recognition.liveness import MiniFasLiveness

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parquet', required=True)
    ap.add_argument('--models', required=True)
    ap.add_argument('--per-class', type=int, default=600)
    ap.add_argument('--out', default=os.path.join(HERE, 'results', 'liveness_celeba_spoof.json'))
    a = ap.parse_args()
    t = pq.read_table(a.parquet)
    labels = t.column('Class').to_pylist()
    rnd = random.Random(42)
    idx = {c: [i for i, x in enumerate(labels) if x == c] for c in ('live', 'spoof')}
    pick = {c: rnd.sample(v, min(a.per_class, len(v))) for c, v in idx.items()}
    det = make_detector('scrfd', os.path.join(a.models, 'buffalo_l/det_10g.onnx'), 640, 0.5)
    live = MiniFasLiveness(os.path.join(a.models, 'onnx/minifasnet_v2.onnx'))
    col = t.column('Filepath')
    scores = {'live': [], 'spoof': []}
    no_face = {'live': 0, 'spoof': 0}
    t0 = time.time()
    for c, ids in pick.items():
        for i in ids:
            raw = col[i].as_py()['bytes']
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            faces = det.detect(img)
            if not faces:
                no_face[c] += 1
                continue
            f = max(faces, key=lambda x: x.width * x.height)
            scores[c].append(live.score(img, f.bbox))
    L, S = np.array(scores['live']), np.array(scores['spoof'])
    grid = []
    for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        grid.append({'threshold': th, 'apcer': float((S >= th).mean()), 'bpcer': float((L < th).mean())})
    # площадь под ROC-кривой через ранги
    allv = np.concatenate([L, S]); y = np.concatenate([np.ones(len(L)), np.zeros(len(S))])
    order = allv.argsort(); ranks = np.empty(len(allv)); ranks[order] = np.arange(1, len(allv) + 1)
    auc = (ranks[y == 1].sum() - len(L) * (len(L) + 1) / 2) / (len(L) * len(S))
    res = {'dataset': os.path.basename(a.parquet), 'live': len(L), 'spoof': len(S), 'no_face': no_face,
           'auc': float(auc), 'grid': grid, 'live_mean': float(L.mean()), 'spoof_mean': float(S.mean()),
           'seconds': round(time.time() - t0)}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
