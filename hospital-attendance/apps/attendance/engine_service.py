"""Один экземпляр движка распознавания на процесс сервера.

Модели загружаются при первом обращении (около 3 с), эталоны – из базы с расшифровкой.
В тестах вместо настоящего движка подставляется заглушка через set_engine().
"""
from __future__ import annotations

import threading

from django.conf import settings

from recognition.crypto import VectorCipher

_engine = None
_lock = threading.Lock()
_gallery_version = {'loaded': None}


def cipher() -> VectorCipher:
    return VectorCipher(settings.BIOMETRIC_KEY)


def model_name() -> str:
    return settings.FACE['RECOGNIZER_FILE'].split('/')[-1].replace('.onnx', '')


def build_engine():
    from recognition.engine import EngineConfig, FaceEngine
    from recognition.matcher import Thresholds
    f = settings.FACE
    cfg = EngineConfig(
        models_dir=f['MODELS_DIR'], detector=f['DETECTOR'], detector_file=f['DETECTOR_FILE'],
        recognizer_file=f['RECOGNIZER_FILE'], liveness_file=f['LIVENESS_FILE'], det_size=f['DET_SIZE'],
        use_liveness=f['USE_LIVENESS'], threads=f['THREADS'],
        thresholds=Thresholds(accept=f['ACCEPT'], review=f['REVIEW'], margin=f['MARGIN'], liveness=f['LIVENESS']))
    return FaceEngine(cfg)


def set_engine(engine) -> None:
    global _engine
    _engine = engine
    _gallery_version['loaded'] = None


def get_engine():
    global _engine
    with _lock:
        if _engine is None:
            _engine = build_engine()
        if _gallery_version['loaded'] != current_version():
            reload_gallery(_engine)
    return _engine


def current_version():
    from apps.staff.models import FaceTemplate
    from django.db.models import Count, Max
    agg = FaceTemplate.objects.aggregate(n=Count('id'), last=Max('id'))
    return agg['n'], agg['last']


def reload_gallery(engine) -> int:
    """Загрузить в память эталоны сотрудников, которые работают и дали согласие."""
    from apps.staff.models import Employee, FaceTemplate
    c = cipher()
    items = []
    qs = FaceTemplate.objects.filter(employee__is_active=True, employee__consent=Employee.Consent.GIVEN,
                                     model_name=model_name())
    for t in qs:
        items.append((t.employee_id, c.decrypt(t.vector)))
    engine.gallery.load(items)
    _gallery_version['loaded'] = current_version()
    return len(items)
