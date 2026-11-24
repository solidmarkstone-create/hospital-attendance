"""Цифровое нанесение медицинской маски на фотографию лица.

Прием тот же, что в отчете NIST IR 8311: маску рисуют по ключевым точкам лица
поверх обычной фотографии. Используются 106 точек модели 2d106det из InsightFace:
верхний край маски проходит по середине спинки носа, нижний – по контуру подбородка.
"""
from __future__ import annotations

import cv2
import numpy as np

# Номера точек контура лица модели 2d106det: от уровня носа слева вниз к подбородку
# и вверх по правой стороне до уровня носа.
LEFT_DOWN = [11, 12, 13, 14, 15, 16, 2, 3, 4, 5, 6, 7, 8, 0]
RIGHT_UP = [24, 23, 22, 21, 20, 19, 18, 32, 31, 30, 29, 28, 27]
NOSE_MID = 73          # верх спинки носа: маска надета правильно, закрывает нос

COLORS = {
    'blue': (235, 206, 150),    # голубая медицинская маска (BGR)
    'white': (238, 238, 238),
}


class MaskPainter:
    def __init__(self, landmark_model_path: str):
        from insightface.model_zoo import get_model
        self.lm = get_model(landmark_model_path)
        self.lm.prepare(ctx_id=-1)

    def landmarks(self, img: np.ndarray, bbox: np.ndarray, kps: np.ndarray) -> np.ndarray:
        from insightface.app.common import Face
        return self.lm.get(img, Face(bbox=bbox[:4], kps=kps, det_score=1.0))

    def paint(self, img: np.ndarray, pts: np.ndarray, color: str = 'blue') -> np.ndarray:
        nose = pts[NOSE_MID]
        drop = 0.04 * float(np.linalg.norm(pts[0] - nose))          # маска чуть ниже подбородка
        chin = {5, 6, 7, 8, 0, 24, 23, 22, 21}

        def p(i):
            return pts[i] + np.array([0.0, drop]) if i in chin else pts[i]

        # по часовой стрелке: нос, правая щека вниз, подбородок, левая щека вверх
        poly = np.array([nose] + [p(i) for i in RIGHT_UP[::-1]] + [p(i) for i in LEFT_DOWN[::-1]])
        lower = list(poly[1:])
        out = img.copy()
        cv2.fillPoly(out, [poly.astype(np.int32)], COLORS[color], lineType=cv2.LINE_AA)
        # складки медицинской маски – три горизонтальные линии
        top, bottom = nose[1], max(p[1] for p in lower)
        for frac in (0.35, 0.55, 0.75):
            y = int(top + (bottom - top) * frac)
            xs = [int(p[0]) for p in poly if abs(p[1] - y) < (bottom - top) * 0.2]
            if len(xs) >= 2:
                cv2.line(out, (min(xs) + 3, y), (max(xs) - 3, y), tuple(int(c * 0.85) for c in COLORS[color]), 1,
                         cv2.LINE_AA)
        return out
