"""Интерфейс терминала: распознавание, повторные отметки, запасной способ."""
from datetime import timedelta
from io import BytesIO

import cv2
import numpy as np
import pytest
from django.utils import timezone

from apps.attendance.models import AttendanceEvent as Ev
from recognition.types import Decision

URL = '/api/kiosk/recognize/'
FB = '/api/kiosk/fallback/'


def jpeg():
    ok, buf = cv2.imencode('.jpg', np.full((120, 160, 3), 127, np.uint8))
    f = BytesIO(buf.tobytes()); f.name = 'f.jpg'
    return f


def post(client, token, n=3):
    return client.post(URL, {'frames': [jpeg() for _ in range(n)]}, HTTP_X_KIOSK_KEY=token)


@pytest.mark.django_db
def test_unknown_terminal_rejected(client, org, fake_engine):
    r = post(client, 'not-a-key')
    assert r.status_code == 403 and fake_engine.calls == 0


@pytest.mark.django_db
def test_no_frames(client, org, fake_engine):
    r = client.post(URL, {}, HTTP_X_KIOSK_KEY=org.token)
    assert r.status_code == 400


@pytest.mark.django_db
def test_bad_image(client, org, fake_engine):
    bad = BytesIO(b'not an image'); bad.name = 'x.jpg'
    r = client.post(URL, {'frames': [bad]}, HTTP_X_KIOSK_KEY=org.token)
    assert r.status_code == 400


@pytest.mark.django_db
def test_accept_creates_confirmed_in_event(client, org, fake_engine, make_result):
    fake_engine.result = make_result(Decision.ACCEPT, org.e1, score=0.72)
    d = post(client, org.token).json()
    assert d['decision'] == 'accept' and d['employee'] == 'Иванова А.С.' and d['direction'] == 'Приход'
    assert 'employee_id' not in d                      # служебный идентификатор не уходит на терминал
    ev = Ev.objects.get()
    assert ev.employee == org.e1 and ev.status == Ev.Status.CONFIRMED and ev.method == Ev.Method.FACE
    assert fake_engine.frames_seen == 3


@pytest.mark.django_db
def test_repeat_within_two_minutes_not_duplicated(client, org, fake_engine, make_result):
    fake_engine.result = make_result(Decision.ACCEPT, org.e1)
    post(client, org.token)
    d = post(client, org.token).json()
    assert d['repeated'] is True and Ev.objects.count() == 1


@pytest.mark.django_db
def test_second_mark_after_shift_is_out(client, org, fake_engine, make_result):
    Ev.objects.create(employee=org.e1, point=org.point, direction=Ev.Direction.IN, method=Ev.Method.FACE,
                      timestamp=timezone.now() - timedelta(hours=8))
    fake_engine.result = make_result(Decision.ACCEPT, org.e1)
    assert post(client, org.token).json()['direction'] == 'Уход'


@pytest.mark.django_db
def test_old_open_in_is_not_closed(client, org, fake_engine, make_result):
    """Приход трое суток назад без ухода: новая отметка – снова приход."""
    Ev.objects.create(employee=org.e1, point=org.point, direction=Ev.Direction.IN, method=Ev.Method.FACE,
                      timestamp=timezone.now() - timedelta(hours=72))
    fake_engine.result = make_result(Decision.ACCEPT, org.e1)
    assert post(client, org.token).json()['direction'] == 'Приход'


@pytest.mark.django_db
def test_review_creates_pending_and_hides_name(client, org, fake_engine, make_result):
    fake_engine.result = make_result(Decision.REVIEW, org.e1, score=0.38)
    d = post(client, org.token).json()
    assert d['decision'] == 'review' and d['employee'] is None
    assert Ev.objects.get().status == Ev.Status.PENDING


@pytest.mark.django_db
def test_spoof_creates_anonymous_pending(client, org, fake_engine, make_result):
    fake_engine.result = make_result(Decision.SPOOF, None, liveness=0.12)
    assert post(client, org.token).json()['decision'] == 'spoof'
    ev = Ev.objects.get()
    assert ev.employee is None and ev.status == Ev.Status.PENDING and 'живости' in ev.reason


@pytest.mark.django_db
@pytest.mark.parametrize('decision', [Decision.UNKNOWN, Decision.NO_FACE])
def test_unknown_and_no_face_leave_no_trace(client, org, fake_engine, make_result, decision):
    fake_engine.result = make_result(decision, None, score=0.1)
    assert post(client, org.token).json()['decision'] == decision.value
    assert Ev.objects.count() == 0


@pytest.mark.django_db
def test_dismissed_employee_not_marked(client, org, fake_engine, make_result):
    org.e1.is_active = False
    org.e1.save()
    fake_engine.result = make_result(Decision.ACCEPT, org.e1)
    post(client, org.token)
    assert Ev.objects.count() == 0


@pytest.mark.django_db
def test_fallback_pin(client, org):
    org.e2.set_pin('2468'); org.e2.save()
    bad = client.post(FB, {'personnel_number': '00002', 'pin': '1111'}, HTTP_X_KIOSK_KEY=org.token)
    assert bad.status_code == 400
    ok = client.post(FB, {'personnel_number': '00002', 'pin': '2468'}, HTTP_X_KIOSK_KEY=org.token).json()
    assert ok['ok'] and Ev.objects.get().status == Ev.Status.PENDING
    assert Ev.objects.get().method == Ev.Method.FALLBACK


@pytest.mark.django_db
def test_fallback_lockout_after_five_errors(client, org):
    from django.core.cache import cache
    cache.clear()
    org.e2.set_pin('2468'); org.e2.save()
    for _ in range(5):
        client.post(FB, {'personnel_number': '00002', 'pin': '0000'}, HTTP_X_KIOSK_KEY=org.token)
    r = client.post(FB, {'personnel_number': '00002', 'pin': '2468'}, HTTP_X_KIOSK_KEY=org.token)
    assert r.status_code == 429
    cache.clear()


@pytest.mark.django_db
def test_kiosk_page_open_without_login(client):
    r = client.get('/kiosk/')
    assert r.status_code == 200 and 'Отметиться' in r.content.decode()
