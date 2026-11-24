"""Пассивная проверка «живости» лица по одному кадру моделью MiniFASNetV2.

Модель из проекта minivision-ai/Silent-Face-Anti-Spoofing (Apache-2.0) в формате ONNX.
Вход 80 x 80 BGR, область вокруг лица в 2,7 раза больше рамки детектора,
значения пикселей 0–255 без нормировки (как в исходном test.py).
Выход – три класса; класс 1 означает живое лицо, 0 и 2 – подделки.
"""
from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort


def crop_with_margin(img: np.ndarray, bbox: np.ndarray, scale: float, size: int = 80) -> np.ndarray:
    """Вырезает квадрат вокруг лица с запасом scale (логика CropImage исходного проекта)."""
    src_h, src_w = img.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    bw, bh = x2 - x1, y2 - y1
    scale = min((src_h - 1) / bh, (src_w - 1) / bw, scale)
    nw, nh = bw * scale, bh * scale
    cx, cy = x1 + bw / 2, y1 + bh / 2
    l, t, r, b = cx - nw / 2, cy - nh / 2, cx + nw / 2, cy + nh / 2
    if l < 0:
        r -= l; l = 0
    if t < 0:
        b -= t; t = 0
    if r > src_w - 1:
        l -= r - src_w + 1; r = src_w - 1
    if b > src_h - 1:
        t -= b - src_h + 1; b = src_h - 1
    patch = img[int(t):int(b) + 1, int(l):int(r) + 1]
    return cv2.resize(patch, (size, size))


class MiniFasLiveness:
    LIVE_CLASS = 1

    def __init__(self, model_path: str, scale: float = 2.7, threads: int = 2):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.scale = scale

    def score(self, img: np.ndarray, bbox: np.ndarray) -> float:
        """Вероятность того, что перед камерой живой человек (0–1)."""
        patch = crop_with_margin(img, bbox, self.scale).astype(np.float32)
        blob = patch.transpose(2, 0, 1)[None]
        logits = self.session.run(None, {self.input_name: blob})[0][0]
        e = np.exp(logits - logits.max())
        p = e / e.sum()
        return float(p[self.LIVE_CLASS])
