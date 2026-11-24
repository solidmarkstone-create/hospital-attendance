"""Сравнение вектора лица с эталонами сотрудников и принятие решения по порогам."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .embedder import l2norm
from .types import Decision, Match


@dataclass
class Thresholds:
    accept: float = 0.40       # от этого сходства отметка ставится автоматически
    review: float = 0.25       # от этого сходства до accept – отметка уходит на проверку
    margin: float = 0.05       # минимальный отрыв лучшего сотрудника от второго
    liveness: float = 0.60     # ниже – попытка обмана камеры

    def __post_init__(self):
        if not (-1.0 <= self.review <= self.accept <= 1.0):
            raise ValueError('порог проверки не может быть выше порога допуска')


class Gallery:
    """База эталонных векторов: у одного сотрудника может быть несколько эталонов."""

    def __init__(self):
        self.ids: list[int] = []
        self.vectors = np.zeros((0, 512), dtype=np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    def load(self, items: list[tuple[int, np.ndarray]]) -> None:
        self.ids = [int(i) for i, _ in items]
        self.vectors = l2norm(np.stack([v for _, v in items])) if items else np.zeros((0, 512), np.float32)

    def add(self, employee_id: int, vector: np.ndarray) -> None:
        self.ids.append(int(employee_id))
        self.vectors = np.vstack([self.vectors, l2norm(vector)[None]])

    def remove(self, employee_id: int) -> None:
        keep = [i for i, e in enumerate(self.ids) if e != employee_id]
        self.ids = [self.ids[i] for i in keep]
        self.vectors = self.vectors[keep]

    def search(self, vector: np.ndarray) -> Match:
        """Ближайший сотрудник по косинусному сходству (векторы единичные)."""
        if not self.ids:
            return Match(employee_id=None, score=-1.0)
        sims = self.vectors @ l2norm(vector)
        best: dict[int, float] = {}
        for emp, s in zip(self.ids, sims):
            if s > best.get(emp, -2.0):
                best[emp] = float(s)
        ranked = sorted(best.items(), key=lambda kv: -kv[1])
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        return Match(employee_id=ranked[0][0], score=ranked[0][1], second_score=second)


def decide(match: Match, th: Thresholds) -> Decision:
    if match.employee_id is None or match.score < th.review:
        return Decision.UNKNOWN
    if match.score >= th.accept and match.score - match.second_score >= th.margin:
        return Decision.ACCEPT
    return Decision.REVIEW
