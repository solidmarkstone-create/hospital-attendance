"""Выравнивание лица по 5 ключевым точкам в квадрат 112 x 112 (шаблон ArcFace)."""
import cv2
import numpy as np

# Положение глаз, носа и уголков рта в выровненном изображении 112 x 112,
# на котором обучены модели ArcFace из библиотеки InsightFace.
ARCFACE_DST = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float32)


def estimate_transform(kps: np.ndarray, size: int = 112) -> np.ndarray:
    """Подобие (поворот, масштаб, сдвиг), переводящее точки лица в шаблон."""
    dst = ARCFACE_DST * (size / 112.0)
    m, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), dst, method=cv2.LMEDS)
    if m is None:  # вырожденный случай: точки на одной линии
        raise ValueError('не удалось выровнять лицо по ключевым точкам')
    return m


def norm_crop(img: np.ndarray, kps: np.ndarray, size: int = 112) -> np.ndarray:
    m = estimate_transform(kps, size)
    return cv2.warpAffine(img, m, (size, size), borderValue=0.0)
