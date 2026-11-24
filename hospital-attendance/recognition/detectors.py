"""Детекторы лиц: SCRFD (InsightFace) и RetinaFace (ONNX).

Оба детектора возвращают одинаковый список Face, поэтому движок распознавания
не зависит от того, какой из них выбран в настройках (решение ADR-0003).
"""
from __future__ import annotations

from itertools import product
from math import ceil

import cv2
import numpy as np
import onnxruntime as ort

from .types import Face


def _session(path: str, threads: int) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(path, sess_options=opts, providers=['CPUExecutionProvider'])


def nms(boxes: np.ndarray, scores: np.ndarray, thr: float) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[1:][iou <= thr]
    return keep


class BaseDetector:
    name = 'base'

    def detect(self, img: np.ndarray) -> list[Face]:  # pragma: no cover - интерфейс
        raise NotImplementedError


class ScrfdDetector(BaseDetector):
    """SCRFD из набора buffalo_l / buffalo_s библиотеки InsightFace."""

    def __init__(self, model_path: str, input_size: int = 640, threshold: float = 0.5, threads: int = 2):
        from insightface.model_zoo.scrfd import SCRFD
        self.name = 'scrfd'
        self.model = SCRFD(model_file=model_path, session=_session(model_path, threads))
        self.model.prepare(ctx_id=-1, input_size=(input_size, input_size), det_thresh=threshold)

    def detect(self, img: np.ndarray) -> list[Face]:
        boxes, kps = self.model.detect(img)
        faces = [Face(bbox=b[:4], score=float(b[4]), kps=k) for b, k in zip(boxes, kps)]
        return sorted(faces, key=lambda f: -f.score)


class RetinaFaceDetector(BaseDetector):
    """RetinaFace (Deng et al., 2020) в экспорте ONNX проекта yakhyo/retinaface-pytorch (MIT)."""

    MIN_SIZES = [[16, 32], [64, 128], [256, 512]]
    STEPS = [8, 16, 32]
    VARIANCE = (0.1, 0.2)
    MEAN = np.array([104, 117, 123], dtype=np.float32)   # BGR

    def __init__(self, model_path: str, input_size: int = 640, threshold: float = 0.5,
                 nms_threshold: float = 0.4, threads: int = 2):
        self.name = 'retinaface'
        self.session = _session(model_path, threads)
        self.input_size = input_size
        self.threshold = threshold
        self.nms_threshold = nms_threshold
        self._priors: dict[tuple[int, int], np.ndarray] = {}

    def priors(self, h: int, w: int) -> np.ndarray:
        key = (h, w)
        if key not in self._priors:
            anchors = []
            for k, step in enumerate(self.STEPS):
                fh, fw = ceil(h / step), ceil(w / step)
                for i, j in product(range(fh), range(fw)):
                    for ms in self.MIN_SIZES[k]:
                        anchors.append([(j + 0.5) * step / w, (i + 0.5) * step / h, ms / w, ms / h])
            self._priors[key] = np.array(anchors, dtype=np.float32)
        return self._priors[key]

    def detect(self, img: np.ndarray) -> list[Face]:
        h0, w0 = img.shape[:2]
        scale = self.input_size / max(h0, w0)
        nh, nw = int(round(h0 * scale)), int(round(w0 * scale))
        canvas = np.zeros((self.input_size, self.input_size, 3), dtype=np.float32)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh)).astype(np.float32)
        blob = (canvas - self.MEAN).transpose(2, 0, 1)[None]
        loc, conf, lmk = self.session.run(None, {'input': blob})
        loc, conf, lmk = loc[0], conf[0][:, 1], lmk[0]
        pr = self.priors(self.input_size, self.input_size)
        mask = conf > self.threshold
        if not mask.any():
            return []
        loc, conf, lmk, pr = loc[mask], conf[mask], lmk[mask], pr[mask]
        v0, v1 = self.VARIANCE
        centers = pr[:, :2] + loc[:, :2] * v0 * pr[:, 2:]
        sizes = pr[:, 2:] * np.exp(loc[:, 2:] * v1)
        boxes = np.hstack([centers - sizes / 2, centers + sizes / 2]) * self.input_size / scale
        pts = np.stack([pr[:, :2] + lmk[:, 2 * i:2 * i + 2] * v0 * pr[:, 2:] for i in range(5)], axis=1)
        pts = pts * self.input_size / scale
        keep = nms(boxes, conf, self.nms_threshold)
        return [Face(bbox=boxes[i], score=float(conf[i]), kps=pts[i]) for i in keep]


def make_detector(kind: str, model_path: str, input_size: int = 640, threshold: float = 0.5,
                  threads: int = 2) -> BaseDetector:
    if kind == 'scrfd':
        return ScrfdDetector(model_path, input_size, threshold, threads)
    if kind == 'retinaface':
        return RetinaFaceDetector(model_path, input_size, threshold, threads=threads)
    raise ValueError(f'неизвестный детектор: {kind}')
