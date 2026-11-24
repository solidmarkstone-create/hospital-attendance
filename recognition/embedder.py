"""Построение вектора признаков лица моделью ArcFace (ONNX)."""
from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort


def l2norm(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


class ArcFaceEmbedder:
    """Модель w600k_r50 (ResNet-50) или w600k_mbf (MobileFaceNet) из набора InsightFace.

    Вход: выровненное лицо 112 x 112 BGR. Выход: единичный вектор длиной 512.
    """

    def __init__(self, model_path: str, threads: int = 2):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.dim = int(self.session.get_outputs()[0].shape[1])

    def embed(self, aligned: np.ndarray) -> np.ndarray:
        return self.embed_batch([aligned])[0]

    def embed_batch(self, faces: list[np.ndarray]) -> np.ndarray:
        blob = cv2.dnn.blobFromImages(faces, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        out = self.session.run(None, {self.input_name: blob})[0]
        return l2norm(out)
