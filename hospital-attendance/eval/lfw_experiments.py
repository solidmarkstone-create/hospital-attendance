"""Оценка качества распознавания на открытом наборе LFW (Labeled Faces in the Wild).

Запуск:  python -m eval.lfw_experiments --lfw /путь/к/lfw --models /путь/к/моделям --rec buffalo_l/w600k_r50.onnx

Опыт 1 – проверка (verification) по стандартному протоколу LFW: 6000 пар, 10 частей.
          Вариант «маска»: второе фото пары закрыто нарисованной медицинской маской
          (эталон без маски, на проходной – в маске, как в NIST IR 8311).
Опыт 2 – открытая идентификация, как на проходной: в базе 300 «сотрудников»
          (по одному эталонному фото), к камере подходят они же (другое фото)
          и 1000 посторонних людей, которых в базе нет.
Результаты пишутся в eval/results/*.json, векторы кэшируются, чтобы опыт можно было повторить.
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

from recognition.align import norm_crop
from recognition.detectors import make_detector
from recognition.embedder import ArcFaceEmbedder

from .masks import MaskPainter

HERE = os.path.dirname(os.path.abspath(__file__))


def read_pairs(path):
    with open(path) as f:
        n_folds, n = map(int, f.readline().split())
        pairs = []
        for fold in range(n_folds):
            for _ in range(n):
                name, a, b = f.readline().split()
                pairs.append((fold, True, (name, int(a)), (name, int(b))))
            for _ in range(n):
                n1, a, n2, b = f.readline().split()
                pairs.append((fold, False, (n1, int(a)), (n2, int(b))))
    return pairs


class Extractor:
    """Вектор для фото (с маской или без); None – детектор не нашел лицо."""

    def __init__(self, args):
        self.lfw = args.lfw
        self.det = make_detector('scrfd', os.path.join(args.models, 'buffalo_l/det_10g.onnx'), 320, 0.5)
        self.rec = ArcFaceEmbedder(os.path.join(args.models, args.rec))
        self.painter = MaskPainter(os.path.join(args.models, 'buffalo_l/2d106det.onnx'))
        tag = os.path.basename(args.rec).replace('.onnx', '')
        self.cache_path = os.path.join(args.cache, f'emb_{tag}.npz')
        self.cache = {}
        if os.path.exists(self.cache_path):
            z = np.load(self.cache_path, allow_pickle=False)
            for k in z.files:
                self.cache[k] = z[k]

    def path(self, ident):
        name, i = ident
        return os.path.join(self.lfw, name, f'{name}_{i:04d}.jpg')

    def key(self, ident, masked):
        return f'{ident[0]}_{ident[1]:04d}_{"m" if masked else "p"}'

    def vec(self, ident, masked=False):
        k = self.key(ident, masked)
        if k in self.cache:
            v = self.cache[k]
        else:
            img = cv2.imread(self.path(ident))
            v = np.zeros(0, np.float32)
            faces = self.det.detect(img)
            if faces:
                # LFW центрирует снимок по лицу: берем лицо, ближайшее к центру
                c = np.array(img.shape[1::-1]) / 2
                f = min(faces, key=lambda x: np.linalg.norm((x.bbox[:2] + x.bbox[2:]) / 2 - c))
                if masked:
                    pts = self.painter.landmarks(img, f.bbox, f.kps)
                    color = 'blue' if zlib.crc32(k.encode()) % 2 else 'white'   # половина масок голубые, половина белые
                    img = self.painter.paint(img, pts, color)
                    faces = self.det.detect(img)       # на проходной лицо ищут уже в маске
                    f = min(faces, key=lambda x: np.linalg.norm((x.bbox[:2] + x.bbox[2:]) / 2 - c)) if faces else None
                if f is not None:
                    v = self.rec.embed(norm_crop(img, f.kps))
            self.cache[k] = v
        return None if v.size == 0 else v

    def failure_to_acquire(self):
        """Доля снимков, на которых детектор не нашел лицо (отдельно без маски и в маске)."""
        out = {}
        for suf, name in (('_p', 'plain'), ('_m', 'mask')):
            keys = [k for k in self.cache if k.endswith(suf)]
            miss = sum(1 for k in keys if self.cache[k].size == 0)
            out[name] = {'images': len(keys), 'no_face': miss}
        return out

    def save(self):
        np.savez(self.cache_path, **self.cache)


def sim(a, b):
    if a is None or b is None:
        return -1.0          # лицо не найдено – пара считается отклоненной
    return float(np.dot(a, b))


def best_threshold(scores, labels):
    cand = np.unique(scores)
    accs = [((scores >= t) == labels).mean() for t in cand]
    i = int(np.argmax(accs))
    return float(cand[i])


def tar_at_far(scores, labels, far):
    neg = np.sort(scores[~labels])[::-1]
    k = int(np.floor(far * len(neg)))
    thr = neg[k] if k < len(neg) else neg[-1]
    # порог строго выше k-го худшего чужого сходства
    tar = float((scores[labels] > thr).mean())
    return tar, float(thr), float((neg > thr).mean())


def verification(ex, pairs, masked):
    scores, labels, folds = [], [], []
    for fold, same, a, b in pairs:
        scores.append(sim(ex.vec(a, False), ex.vec(b, masked)))
        labels.append(same)
        folds.append(fold)
    scores, labels, folds = np.array(scores), np.array(labels), np.array(folds)
    accs = []
    for f in range(10):
        tr, te = folds != f, folds == f
        t = best_threshold(scores[tr], labels[tr])
        accs.append(((scores[te] >= t) == labels[te]).mean())
    res = {'accuracy_mean': float(np.mean(accs)), 'accuracy_std': float(np.std(accs))}
    for far in (0.01, 0.001):
        tar, thr, real_far = tar_at_far(scores, labels, far)
        res[f'tar_at_far_{far}'] = {'tar': tar, 'threshold': thr, 'far': real_far}
    res['genuine_mean'] = float(scores[labels].mean())
    res['impostor_mean'] = float(scores[~labels].mean())
    res['impostor_max'] = float(scores[~labels].max())
    hist_bins = np.linspace(-0.2, 1.0, 25)
    res['hist_bins'] = hist_bins.tolist()
    res['hist_genuine'] = np.histogram(scores[labels], hist_bins)[0].tolist()
    res['hist_impostor'] = np.histogram(scores[~labels], hist_bins)[0].tolist()
    return res, scores, labels


def identification(ex, lfw, n_gallery=300, n_impostors=1000, seed=42):
    people = sorted(os.listdir(lfw))
    counts = {p: len(os.listdir(os.path.join(lfw, p))) for p in people}
    rnd = random.Random(seed)
    multi = [p for p in people if counts[p] >= 2]
    single = [p for p in people if counts[p] == 1]
    gallery_people = rnd.sample(multi, n_gallery)
    impostors = rnd.sample(single, n_impostors)
    G, ids = [], []
    for p in gallery_people:
        v = ex.vec((p, 1), False)
        if v is not None:
            G.append(v); ids.append(p)
    G = np.stack(G)
    out = {'gallery': len(ids)}
    for masked in (False, True):
        gen_top, gen_ok, imp_top = [], [], []
        for p in ids:
            v = ex.vec((p, 2), masked)
            if v is None:
                gen_top.append(-1.0); gen_ok.append(False); continue
            s = G @ v
            i = int(np.argmax(s))
            gen_top.append(float(s[i])); gen_ok.append(ids[i] == p)
        for p in impostors:
            v = ex.vec((p, 1), masked)
            imp_top.append(-1.0 if v is None else float(np.max(G @ v)))
        gen_top, gen_ok, imp_top = np.array(gen_top), np.array(gen_ok), np.array(imp_top)
        rows = []
        for t in np.round(np.arange(0.20, 0.71, 0.05), 2):
            rows.append({'threshold': float(t),
                         'fnir': float(1 - (gen_ok & (gen_top >= t)).mean()),
                         'wrong_person': float((~gen_ok & (gen_top >= t)).mean()),
                         'fpir': float((imp_top >= t).mean())})
        out['mask' if masked else 'plain'] = {
            'rank1': float(gen_ok.mean()), 'grid': rows,
            'genuine_scores': gen_top.tolist(), 'impostor_scores': imp_top.tolist(),
            'genuine_correct': gen_ok.tolist()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lfw', required=True)
    ap.add_argument('--pairs', required=True)
    ap.add_argument('--models', required=True)
    ap.add_argument('--rec', default='buffalo_l/w600k_r50.onnx')
    ap.add_argument('--cache', default=os.environ.get('EVAL_CACHE', os.path.join(HERE, 'cache')))
    ap.add_argument('--out', default=os.path.join(HERE, 'results'))
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    ex = Extractor(args)
    t0 = time.time()
    pairs = read_pairs(args.pairs)
    result = {'recognizer': args.rec, 'pairs': len(pairs)}
    for masked in (False, True):
        r, _, _ = verification(ex, pairs, masked)
        result['verification_mask' if masked else 'verification_plain'] = r
        ex.save()
        print('verification', 'mask' if masked else 'plain', round(r['accuracy_mean'], 4), r['tar_at_far_0.001'],
              round(time.time() - t0), 'c', flush=True)
    result['identification'] = identification(ex, args.lfw)
    result['failure_to_acquire'] = ex.failure_to_acquire()
    ex.save()
    tag = os.path.basename(args.rec).replace('.onnx', '')
    with open(os.path.join(args.out, f'lfw_{tag}.json'), 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print('готово за', round(time.time() - t0), 'с')


if __name__ == '__main__':
    main()
