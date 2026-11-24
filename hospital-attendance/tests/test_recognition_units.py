"""Модульные тесты модуля распознавания без нейросетей."""
import numpy as np
import pytest

from recognition.align import ARCFACE_DST, estimate_transform, norm_crop
from recognition.crypto import VectorCipher
from recognition.detectors import RetinaFaceDetector, nms
from recognition.embedder import l2norm
from recognition.engine import EngineConfig, EnrollmentError, FaceEngine
from recognition.liveness import crop_with_margin
from recognition.matcher import Gallery, Thresholds, decide
from recognition.quality import face_quality, frontality
from recognition.types import Decision, Face, Match


def unit(seed, dim=512):
    return l2norm(np.random.default_rng(seed).normal(size=dim))


# ---------- сравнение с эталонами
def test_gallery_finds_nearest_employee():
    g = Gallery()
    g.load([(1, unit(1)), (2, unit(2)), (3, unit(3))])
    probe = l2norm(unit(2) + 0.1 * unit(99))
    m = g.search(probe)
    assert m.employee_id == 2
    assert m.score > 0.9 and m.second_score < 0.2


def test_gallery_uses_best_of_several_templates():
    g = Gallery()
    g.load([(7, unit(10)), (7, unit(11)), (8, unit(12))])
    m = g.search(unit(11))
    assert m.employee_id == 7 and m.score == pytest.approx(1.0, abs=1e-5)


def test_gallery_remove_and_empty():
    g = Gallery()
    assert g.search(unit(1)).employee_id is None
    g.add(5, unit(5)); g.add(6, unit(6))
    g.remove(5)
    assert g.ids == [6] and len(g) == 1


@pytest.mark.parametrize('score,second,expected', [
    (0.80, 0.10, Decision.ACCEPT),
    (0.46, 0.10, Decision.ACCEPT),
    (0.40, 0.10, Decision.REVIEW),        # серая зона – ручная проверка
    (0.50, 0.48, Decision.REVIEW),        # два сотрудника почти одинаково похожи
    (0.20, 0.10, Decision.UNKNOWN),
])
def test_decision_thresholds(score, second, expected):
    th = Thresholds(accept=0.45, review=0.30, margin=0.05)
    assert decide(Match(1, score, second), th) == expected


def test_unknown_when_gallery_empty():
    assert decide(Match(None, -1.0), Thresholds()) == Decision.UNKNOWN


def test_thresholds_validation():
    with pytest.raises(ValueError):
        Thresholds(accept=0.3, review=0.5)


# ---------- шифрование эталонов
def test_cipher_roundtrip_and_no_plain_floats():
    c = VectorCipher(VectorCipher.generate_key())
    v = unit(4)
    token = c.encrypt(v)
    assert v.tobytes() not in token
    assert np.allclose(c.decrypt(token), v)


def test_cipher_wrong_key_rejected():
    token = VectorCipher(VectorCipher.generate_key()).encrypt(unit(1))
    with pytest.raises(ValueError):
        VectorCipher(VectorCipher.generate_key()).decrypt(token)


def test_cipher_requires_key():
    with pytest.raises(ValueError):
        VectorCipher('')


# ---------- выравнивание, качество, детектор
def test_alignment_maps_points_to_template():
    kps = ARCFACE_DST * 2 + np.array([30, 40])          # лицо вдвое крупнее и сдвинуто
    m = estimate_transform(kps)
    mapped = (m[:, :2] @ kps.T).T + m[:, 2]
    assert np.allclose(mapped, ARCFACE_DST, atol=0.5)
    img = np.zeros((400, 400, 3), np.uint8)
    assert norm_crop(img, kps).shape == (112, 112, 3)


def test_frontality():
    front = np.array([[40, 50], [80, 50], [60, 70], [45, 90], [75, 90]], float)
    turned = front.copy(); turned[2, 0] = 76
    assert frontality(front) == pytest.approx(1.0)
    assert frontality(turned) < 0.3


def test_quality_prefers_large_sharp_face():
    rng = np.random.default_rng(0)
    sharp = rng.integers(0, 255, (112, 112, 3), dtype=np.uint8)
    blurry = np.full((112, 112, 3), 128, np.uint8)
    kps = np.array([[40, 50], [80, 50], [60, 70], [45, 90], [75, 90]], float)
    big = Face(np.array([0, 0, 150, 150.]), 0.9, kps)
    small = Face(np.array([0, 0, 50, 50.]), 0.9, kps)
    img = np.zeros((200, 200, 3), np.uint8)
    assert face_quality(img, big, sharp) > face_quality(img, big, blurry)
    assert face_quality(img, small, sharp) < face_quality(img, big, sharp)


def test_nms_removes_overlaps():
    boxes = np.array([[0, 0, 100, 100], [5, 5, 105, 105], [200, 200, 260, 260]], float)
    keep = nms(boxes, np.array([0.9, 0.8, 0.7]), 0.4)
    assert keep == [0, 2]


def test_retinaface_priors_count():
    det = RetinaFaceDetector.__new__(RetinaFaceDetector)
    det._priors = {}
    # 640/8=80, 640/16=40, 640/32=20 клеток, по 2 якоря в каждой
    assert len(det.priors(640, 640)) == 2 * (80 * 80 + 40 * 40 + 20 * 20)


def test_liveness_crop_inside_image():
    img = np.zeros((480, 640, 3), np.uint8)
    patch = crop_with_margin(img, np.array([600, 400, 660, 470.]), 2.7)    # лицо у края кадра
    assert patch.shape == (80, 80, 3)


# ---------- движок на заглушках
class FakeDet:
    def __init__(self, faces_per_frame):
        self.faces = list(faces_per_frame)

    def detect(self, img):
        return self.faces.pop(0)


class FakeEmb:
    def __init__(self, vec):
        self.vec = vec

    def embed(self, aligned):
        return self.vec


class FakeLive:
    def __init__(self, value):
        self.value = value

    def score(self, img, bbox):
        return self.value


KPS = np.array([[140, 150], [200, 150], [170, 185], [145, 215], [195, 215]], float)


def face(size=120, score=0.9):
    return Face(np.array([110, 100, 110 + size, 100 + size], float), score, KPS)


def engine(faces, vec, live=0.9):
    cfg = EngineConfig(models_dir='', use_liveness=True)
    return FaceEngine(cfg, detector=FakeDet(faces), embedder=FakeEmb(vec), liveness=FakeLive(live))


FRAME = np.random.default_rng(1).integers(0, 255, (480, 640, 3), dtype=np.uint8)


def test_engine_no_face():
    e = engine([[], []], unit(1))
    assert e.identify([FRAME, FRAME]).decision == Decision.NO_FACE


def test_engine_small_face_is_ignored():
    e = engine([[face(size=30)]], unit(1))
    assert e.identify([FRAME]).decision == Decision.NO_FACE


def test_engine_spoof_stops_before_matching():
    e = engine([[face()]], unit(1), live=0.1)
    e.gallery.load([(1, unit(1))])
    r = e.identify([FRAME])
    assert r.decision == Decision.SPOOF and r.match is None


def test_engine_accept_and_timings():
    e = engine([[face()]], unit(1))
    e.gallery.load([(1, unit(1)), (2, unit(2))])
    r = e.identify([FRAME])
    assert r.decision == Decision.ACCEPT and r.match.employee_id == 1
    assert {'detect', 'liveness', 'embed', 'match', 'total'} <= set(r.timings)


def test_engine_picks_best_frame():
    e = engine([[face(size=70, score=0.6)], [face(size=160, score=0.95)], []], unit(1))
    e.gallery.load([(1, unit(1))])
    assert e.identify([FRAME, FRAME, FRAME]).frame_index == 1


def test_enroll_errors():
    with pytest.raises(EnrollmentError):
        engine([[]], unit(1)).enroll([FRAME])
    with pytest.raises(EnrollmentError):
        engine([[face(size=30)]], unit(1)).enroll([FRAME])
    with pytest.raises(EnrollmentError):
        engine([], unit(1)).enroll([])


def test_enroll_averages_and_normalizes():
    e = engine([[face()], [face()]], unit(3))
    vec, q = e.enroll([FRAME, FRAME])
    assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5) and 0 < q <= 1
