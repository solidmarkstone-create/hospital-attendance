"""Интеграционные тесты с настоящими моделями (SCRFD, RetinaFace, ArcFace, MiniFASNet) на фото LFW.

Запуск: pytest -m models. Без моделей и набора LFW тесты пропускаются.
"""
import os
import time

import cv2
import numpy as np
import pytest

from recognition.engine import EngineConfig, FaceEngine
from recognition.types import Decision

from .conftest import LFW_DIR, MODELS_DIR

pytestmark = [pytest.mark.models,
              pytest.mark.skipif(not os.path.exists(os.path.join(MODELS_DIR, 'buffalo_l', 'w600k_r50.onnx'))
                                 or not os.path.isdir(LFW_DIR), reason='нет моделей или набора LFW')]


def img(person, i):
    return cv2.imread(os.path.join(LFW_DIR, person, f'{person}_{i:04d}.jpg'))


def frame(person, i):
    """Снимок LFW, вписанный в кадр 640 x 480, как с камеры терминала."""
    f = np.full((480, 640, 3), 90, np.uint8)
    face = cv2.resize(img(person, i), (375, 375))
    f[52:427, 132:507] = face
    return f


@pytest.fixture(scope='module')
def engine():
    # снимки LFW – сами фотографии, поэтому «живость» здесь проверяется отдельным тестом,
    # а узнавание – без нее (иначе часть снимков справедливо считается подделкой)
    eng = FaceEngine(EngineConfig(models_dir=MODELS_DIR, threads=2, use_liveness=False))
    people = ['Azra_Akin', 'Carson_Palmer', 'Arminio_Fraga', 'Candie_Kung', 'Ben_Howland']
    for k, p in enumerate(people, 1):
        vec, _ = eng.enroll([img(p, 1)])
        eng.gallery.add(k, vec)
    eng.people = people
    return eng


def test_known_employees_accepted(engine):
    for k, p in enumerate(engine.people, 1):
        r = engine.identify([frame(p, 2)])
        assert r.decision == Decision.ACCEPT and r.match.employee_id == k, (p, r.as_dict())


def test_stranger_not_accepted(engine):
    for p in ['Bill_Paxton', 'Cate_Blanchett', 'Boris_Becker']:
        r = engine.identify([frame(p, 1)])
        assert r.decision in (Decision.UNKNOWN, Decision.SPOOF), (p, r.as_dict())


def test_response_time_under_one_second(engine):
    engine.identify([frame('Azra_Akin', 2)])            # прогрев
    t = time.perf_counter()
    r = engine.identify([frame('Azra_Akin', 3)])
    assert time.perf_counter() - t < 1.0 and r.decision == Decision.ACCEPT


def test_liveness_score_range(engine):
    from recognition.liveness import MiniFasLiveness
    live = MiniFasLiveness(os.path.join(MODELS_DIR, 'onnx/minifasnet_v2.onnx'))
    f = frame('Allyson_Felix', 2)
    s = live.score(f, engine.main_face(f).bbox)
    assert 0.0 <= s <= 1.0


def test_full_engine_with_liveness_under_one_second():
    eng = FaceEngine(EngineConfig(models_dir=MODELS_DIR, threads=2))
    vec, _ = eng.enroll([img('Allyson_Felix', 1)])
    eng.gallery.add(1, vec)
    eng.identify([frame('Allyson_Felix', 2)])
    t = time.perf_counter()
    r = eng.identify([frame('Allyson_Felix', 2)] * 3)
    assert time.perf_counter() - t < 1.0 and r.decision == Decision.ACCEPT and r.liveness >= 0.6


def test_retinaface_and_scrfd_agree():
    from recognition.detectors import make_detector
    a = make_detector('scrfd', os.path.join(MODELS_DIR, 'buffalo_l/det_10g.onnx'))
    b = make_detector('retinaface', os.path.join(MODELS_DIR, 'onnx/retinaface_mv2.onnx'))
    f = frame('Candie_Kung', 1)
    fa, fb = a.detect(f)[0], b.detect(f)[0]
    assert np.abs(fa.kps - fb.kps).max() < 15            # ключевые точки совпадают в пределах 15 пикселей
