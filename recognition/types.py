"""Общие структуры данных модуля распознавания."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


@dataclass
class Face:
    """Лицо, найденное детектором: рамка, уверенность, 5 ключевых точек."""
    bbox: np.ndarray          # x1, y1, x2, y2
    score: float
    kps: np.ndarray           # 5 x 2: глаза, нос, уголки рта

    @property
    def width(self) -> float:
        return float(self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return float(self.bbox[3] - self.bbox[1])


class Decision(str, Enum):
    """Итог обработки обращения к терминалу."""
    ACCEPT = 'accept'          # сотрудник узнан, отметка подтверждена
    REVIEW = 'review'          # сходство в серой зоне, отметку проверит человек
    UNKNOWN = 'unknown'        # лицо не похоже ни на один эталон
    SPOOF = 'spoof'            # не пройдена проверка «живости»
    NO_FACE = 'no_face'        # в кадрах нет лица подходящего качества


@dataclass
class Match:
    employee_id: int | None
    score: float               # косинусное сходство с ближайшим эталоном
    second_score: float = -1.0  # сходство со вторым по близости сотрудником


@dataclass
class EngineResult:
    decision: Decision
    match: Match | None = None
    liveness: float | None = None
    quality: float | None = None
    frame_index: int | None = None
    timings: dict = field(default_factory=dict)
    message: str = ''

    def as_dict(self) -> dict:
        return {
            'decision': self.decision.value,
            'employee_id': self.match.employee_id if self.match else None,
            'score': round(self.match.score, 4) if self.match else None,
            'liveness': None if self.liveness is None else round(self.liveness, 4),
            'quality': None if self.quality is None else round(self.quality, 4),
            'frame_index': self.frame_index,
            'timings_ms': {k: round(v * 1000, 1) for k, v in self.timings.items()},
            'message': self.message,
        }
