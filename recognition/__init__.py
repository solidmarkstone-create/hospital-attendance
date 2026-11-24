"""Модуль распознавания лиц системы учета посещаемости.

Не зависит от Django: его можно проверять и заменять отдельно (ADR-0002).
"""
from .types import Decision, EngineResult, Face, Match  # noqa: F401
