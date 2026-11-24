"""Движок распознавания: несколько кадров с терминала – одно решение.

Порядок работы (рисунок 1 главы 1):
1) детектор находит лицо в каждом кадре, берется самое крупное;
2) лицо выравнивается по 5 точкам, считается качество кадра;
3) для лучшего кадра проверяется «живость»;
4) ArcFace строит вектор, вектор сравнивается с эталонами;
5) по порогам принимается решение: отметка, ручная проверка или отказ.
Кадры обрабатываются только в памяти и никуда не сохраняются.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .align import norm_crop
from .detectors import BaseDetector, make_detector
from .embedder import ArcFaceEmbedder, l2norm
from .liveness import MiniFasLiveness
from .matcher import Gallery, Thresholds, decide
from .quality import face_quality
from .types import Decision, EngineResult, Face


@dataclass
class EngineConfig:
    models_dir: str
    detector: str = 'scrfd'                       # scrfd | retinaface
    detector_file: str = 'buffalo_l/det_10g.onnx'
    recognizer_file: str = 'buffalo_l/w600k_r50.onnx'
    liveness_file: str = 'onnx/minifasnet_v2.onnx'
    det_size: int = 640
    det_threshold: float = 0.5
    min_face: int = 60                            # минимальная сторона лица, пикселей
    min_quality: float = 0.35
    use_liveness: bool = True
    threads: int = 2
    thresholds: Thresholds = field(default_factory=Thresholds)

    def path(self, rel: str) -> str:
        return rel if os.path.isabs(rel) else os.path.join(self.models_dir, rel)


class EnrollmentError(ValueError):
    pass


class FaceEngine:
    def __init__(self, cfg: EngineConfig, detector: BaseDetector | None = None,
                 embedder: ArcFaceEmbedder | None = None, liveness: MiniFasLiveness | None = None):
        self.cfg = cfg
        self.detector = detector or make_detector(cfg.detector, cfg.path(cfg.detector_file), cfg.det_size,
                                                  cfg.det_threshold, cfg.threads)
        self.embedder = embedder or ArcFaceEmbedder(cfg.path(cfg.recognizer_file), cfg.threads)
        self.liveness = liveness
        if self.liveness is None and cfg.use_liveness:
            self.liveness = MiniFasLiveness(cfg.path(cfg.liveness_file), threads=cfg.threads)
        self.gallery = Gallery()
        self.lock = threading.Lock()   # onnxruntime-сессии и галерея общие для потоков сервера

    # ---------- вспомогательное
    def main_face(self, img: np.ndarray) -> Face | None:
        faces = self.detector.detect(img)
        if not faces:
            return None
        return max(faces, key=lambda f: f.width * f.height)

    def best_frame(self, frames: list[np.ndarray], timings: dict):
        best = None
        t = time.perf_counter()
        for i, img in enumerate(frames):
            face = self.main_face(img)
            if face is None or min(face.width, face.height) < self.cfg.min_face:
                continue
            aligned = norm_crop(img, face.kps)
            q = face_quality(img, face, aligned, self.cfg.min_face)
            if best is None or q > best[0]:
                best = (q, i, face, aligned)
        timings['detect'] = time.perf_counter() - t
        return best

    # ---------- регистрация сотрудника
    def enroll(self, photos: list[np.ndarray]) -> tuple[np.ndarray, float]:
        """Эталон из 1–5 фотографий: средний единичный вектор. Фото после расчета не хранятся."""
        vecs, quals = [], []
        for img in photos:
            face = self.main_face(img)
            if face is None:
                raise EnrollmentError('на одной из фотографий не найдено лицо')
            if min(face.width, face.height) < self.cfg.min_face:
                raise EnrollmentError('лицо на фотографии слишком мелкое, нужен снимок крупнее')
            aligned = norm_crop(img, face.kps)
            quals.append(face_quality(img, face, aligned, self.cfg.min_face))
            vecs.append(self.embedder.embed(aligned))
        if not vecs:
            raise EnrollmentError('не передано ни одной фотографии')
        q = float(np.mean(quals))
        if q < self.cfg.min_quality:
            raise EnrollmentError('низкое качество снимков: нужно ровное освещение и лицо анфас')
        return l2norm(np.mean(vecs, axis=0)), q

    # ---------- обращение к терминалу
    def identify(self, frames: list[np.ndarray]) -> EngineResult:
        timings: dict = {}
        t0 = time.perf_counter()
        with self.lock:
            best = self.best_frame(frames, timings)
            if best is None:
                timings['total'] = time.perf_counter() - t0
                return EngineResult(Decision.NO_FACE, timings=timings,
                                    message='Лицо не найдено. Встаньте ближе к камере.')
            q, idx, face, aligned = best
            live = None
            if self.liveness is not None:
                t = time.perf_counter()
                live = self.liveness.score(frames[idx], face.bbox)
                timings['liveness'] = time.perf_counter() - t
                if live < self.cfg.thresholds.liveness:
                    timings['total'] = time.perf_counter() - t0
                    return EngineResult(Decision.SPOOF, liveness=live, quality=q, frame_index=idx, timings=timings,
                                        message='Проверка не пройдена. Отметку подтвердит администратор.')
            t = time.perf_counter()
            vec = self.embedder.embed(aligned)
            timings['embed'] = time.perf_counter() - t
            t = time.perf_counter()
            match = self.gallery.search(vec)
            timings['match'] = time.perf_counter() - t
        decision = decide(match, self.cfg.thresholds)
        timings['total'] = time.perf_counter() - t0
        msg = {Decision.ACCEPT: 'Отметка принята.',
               Decision.REVIEW: 'Отметка отправлена на подтверждение.',
               Decision.UNKNOWN: 'Сотрудник не узнан. Используйте запасной способ отметки.'}[decision]
        return EngineResult(decision, match=match, liveness=live, quality=q, frame_index=idx,
                            timings=timings, message=msg)
