"""Подбор порогов допуска и проверки по сохраненным векторам опыта открытой идентификации.

Запуск: python -m eval.thresholds --lfw /путь/к/lfw --rec w600k_r50
Использует кэш векторов из eval.lfw_experiments и то же правило решения, что и движок
(recognition.matcher.decide): допуск при s1 >= accept и s1 - s2 >= margin, проверка при s1 >= review.
"""
from __future__ import annotations

import argparse
import json
import os
import random

import numpy as np

from recognition.matcher import Thresholds, decide
from recognition.types import Decision, Match

HERE = os.path.dirname(os.path.abspath(__file__))


def load(cache, name, i, masked):
    k = f'{name}_{i:04d}_{"m" if masked else "p"}'
    v = cache.get(k)
    return None if v is None or v.size == 0 else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lfw', required=True)
    ap.add_argument('--rec', default='w600k_r50')
    ap.add_argument('--cache', default=os.environ.get('EVAL_CACHE', os.path.join(HERE, 'cache')))
    ap.add_argument('--margin', type=float, default=0.05)
    a = ap.parse_args()
    z = np.load(os.path.join(a.cache, f'emb_{a.rec}.npz'))
    cache = {k: z[k] for k in z.files}
    people = sorted(os.listdir(a.lfw))
    counts = {p: len(os.listdir(os.path.join(a.lfw, p))) for p in people}
    rnd = random.Random(42)                               # тот же отбор, что в lfw_experiments
    gallery = rnd.sample([p for p in people if counts[p] >= 2], 300)
    impostors = rnd.sample([p for p in people if counts[p] == 1], 1000)
    ids = [p for p in gallery if load(cache, p, 1, False) is not None]
    G = np.stack([load(cache, p, 1, False) for p in ids])

    def match(v):
        if v is None:
            return Match(None, -1.0)
        s = G @ v
        o = np.argsort(-s)
        return Match(int(o[0]), float(s[o[0]]), float(s[o[1]]))

    out = {'gallery': len(ids), 'impostors': len(impostors), 'margin': a.margin, 'grid': []}
    for masked in (False, True):
        gm = [(ids.index(p), match(load(cache, p, 2, masked))) for p in ids]
        im = [match(load(cache, p, 1, masked)) for p in impostors]
        for acc in (0.30, 0.35, 0.40, 0.45):
            for rev in (0.20, 0.25, 0.30):
                if rev > acc:
                    continue
                th = Thresholds(accept=acc, review=rev, margin=a.margin)
                g = [(t, m, decide(m, th)) for t, m in gm]
                i = [decide(m, th) for m in im]
                n = len(g)
                out['grid'].append({
                    'mask': masked, 'accept': acc, 'review': rev,
                    'auto_correct': sum(d == Decision.ACCEPT and m.employee_id == t for t, m, d in g) / n,
                    'auto_wrong': sum(d == Decision.ACCEPT and m.employee_id != t for t, m, d in g) / n,
                    'review_share': sum(d == Decision.REVIEW for _, _, d in g) / n,
                    'review_correct': sum(d == Decision.REVIEW and m.employee_id == t for t, m, d in g) / n,
                    'genuine_rejected': sum(d == Decision.UNKNOWN for _, _, d in g) / n,
                    'impostor_auto': sum(d == Decision.ACCEPT for d in i) / len(i),
                    'impostor_review': sum(d == Decision.REVIEW for d in i) / len(i),
                })
    path = os.path.join(HERE, 'results', f'thresholds_{a.rec}.json')
    json.dump(out, open(path, 'w'), ensure_ascii=False, indent=1)
    for r in out['grid']:
        print({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()})


if __name__ == '__main__':
    main()
