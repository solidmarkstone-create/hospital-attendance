"""Оценка качества кадра для выбора лучшего из нескольких снимков."""
from __future__ import annotations

import cv2
import numpy as np

from .types import Face


def sharpness(gray: np.ndarray) -> float:
    """Резкость: дисперсия лапласиана (чем больше, тем меньше смаз)."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def frontality(kps: np.ndarray) -> float:
    """1 – лицо смотрит прямо в камеру, 0 – сильный поворот.

    Нос в анфас лежит посередине между глазами; смещение носа к одному из глаз
    говорит о повороте головы.
    """
    le, re, nose = kps[0], kps[1], kps[2]
    eye_dist = float(np.linalg.norm(re - le))
    if eye_dist < 1e-6:
        return 0.0
    mid = (le + re) / 2
    shift = abs(float(nose[0] - mid[0])) / eye_dist
    return float(max(0.0, 1.0 - 2.0 * shift))


def face_quality(img: np.ndarray, face: Face, aligned: np.ndarray, min_size: int = 60) -> float:
    """Итоговая оценка 0–1: размер лица, резкость, поворот и уверенность детектора."""
    size = min(face.width, face.height)
    size_q = min(1.0, size / (2.0 * min_size)) if size >= min_size else 0.0
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    sharp_q = min(1.0, sharpness(gray) / 300.0)
    front_q = frontality(face.kps)
    return float(0.35 * size_q + 0.25 * sharp_q + 0.25 * front_q + 0.15 * min(1.0, face.score))
