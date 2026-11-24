"""Права ролей, согласие на биометрию, регистрация эталона, аудит."""
from io import BytesIO

import cv2
import numpy as np
import pytest

from apps.attendance.models import AttendanceEvent as Ev
from apps.core import roles
from apps.core.models import AuditLog
from apps.staff.models import Employee, FaceTemplate

PAGES = ['/', '/journal/', '/timesheet/', '/lateness/', '/review/', '/staff/', '/manual/', '/audit/']
#        ожидаемый ответ для: администратор, отдел кадров, руководитель, работник
MATRIX = {
    '/': (200, 200, 200, 302),            # работника сводка перенаправляет на «Мои отметки»
    '/journal/': (200, 200, 200, 403),
    '/timesheet/': (200, 200, 200, 403),
    '/lateness/': (200, 200, 200, 403),
    '/review/': (200, 200, 200, 403),
    '/staff/': (200, 200, 200, 403),
    '/manual/': (200, 200, 200, 403),
    '/audit/': (200, 403, 403, 403),
}


@pytest.fixture
def users(org, user_factory):
    return [user_factory('a', roles.ADMIN), user_factory('k', roles.HR),
            user_factory('z', roles.HEAD, head_of=org.surg), user_factory('r', roles.EMPLOYEE, employee=org.e1)]


@pytest.mark.django_db
@pytest.mark.parametrize('page', PAGES)
def test_role_matrix(client, users, page):
    for user, expected in zip(users, MATRIX[page]):
        client.force_login(user)
        assert client.get(page).status_code == expected, (page, user.username)


@pytest.mark.django_db
def test_anonymous_redirected_to_login(client, org):
    for page in PAGES:
        r = client.get(page)
        assert r.status_code == 302 and '/login/' in r['Location']


@pytest.mark.django_db
def test_head_sees_only_own_department(client, org, users):
    Ev.objects.create(employee=org.e1, direction='in', method='face')
    Ev.objects.create(employee=org.e2, direction='in', method='face')
    client.force_login(users[2])
    html = client.get('/journal/').content.decode()
    assert 'Иванова' in html and 'Петрова' not in html
    staff = client.get('/staff/').content.decode()
    assert 'Петрова' not in staff
    # карточку чужого и своего сотрудника руководитель не редактирует
    assert client.get(f'/staff/{org.e1.pk}/').status_code == 403


@pytest.mark.django_db
def test_head_cannot_review_other_department(client, org, users):
    ev = Ev.objects.create(employee=org.e2, direction='in', method='fallback', status=Ev.Status.PENDING)
    client.force_login(users[2])
    assert client.post(f'/review/{ev.pk}/', {'decision': 'confirm'}).status_code == 403
    ev.refresh_from_db()
    assert ev.status == Ev.Status.PENDING


@pytest.mark.django_db
def test_head_confirms_own_department_and_audit(client, org, users):
    ev = Ev.objects.create(employee=org.e1, direction='in', method='fallback', status=Ev.Status.PENDING)
    client.force_login(users[2])
    client.post(f'/review/{ev.pk}/', {'decision': 'confirm'})
    ev.refresh_from_db()
    assert ev.status == Ev.Status.CONFIRMED and ev.reviewed_by == users[2]
    assert AuditLog.objects.filter(action=AuditLog.Action.REVIEW).exists()


@pytest.mark.django_db
def test_anonymous_spoof_event_cannot_be_confirmed(client, org, users):
    ev = Ev.objects.create(employee=None, direction='in', method='face', status=Ev.Status.PENDING)
    client.force_login(users[0])
    client.post(f'/review/{ev.pk}/', {'decision': 'confirm'})
    ev.refresh_from_db()
    assert ev.status == Ev.Status.PENDING
    client.post(f'/review/{ev.pk}/', {'decision': 'reject'})
    ev.refresh_from_db()
    assert ev.status == Ev.Status.REJECTED


def photo():
    img = np.random.default_rng(0).integers(0, 255, (200, 200, 3), dtype=np.uint8)
    f = BytesIO(cv2.imencode('.jpg', img)[1].tobytes()); f.name = 'p.jpg'
    return f


@pytest.mark.django_db
def test_enroll_stores_only_encrypted_vector(client, org, users, fake_engine, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(users[1])
    r = client.post(f'/staff/{org.e1.pk}/enroll/', {'photos': [photo()]})
    assert r.status_code == 302
    t = FaceTemplate.objects.get()
    assert fake_engine.vector.tobytes() not in bytes(t.vector)
    from apps.attendance.engine_service import cipher
    assert np.allclose(cipher().decrypt(t.vector), fake_engine.vector)
    assert list(tmp_path.iterdir()) == []           # на диск ничего не записано
    assert AuditLog.objects.filter(action=AuditLog.Action.ENROLL).count() == 1


@pytest.mark.django_db
def test_enroll_requires_consent(client, org, users, fake_engine):
    org.e1.consent = Employee.Consent.REFUSED
    org.e1.save()
    client.force_login(users[1])
    client.post(f'/staff/{org.e1.pk}/enroll/', {'photos': [photo()]})
    assert FaceTemplate.objects.count() == 0


@pytest.mark.django_db
def test_head_cannot_enroll(client, org, users, fake_engine):
    client.force_login(users[2])
    assert client.post(f'/staff/{org.e1.pk}/enroll/', {'photos': [photo()]}).status_code == 403


@pytest.mark.django_db
def test_withdrawal_of_consent_deletes_templates(client, org, users):
    FaceTemplate.objects.create(employee=org.e1, model_name='w600k_r50', vector=b'x')
    client.force_login(users[1])
    client.post(f'/staff/{org.e1.pk}/', {'consent': 'withdrawn', 'consent_date': '2026-11-20', 'consent_doc': ''})
    org.e1.refresh_from_db()
    assert org.e1.consent == 'withdrawn' and FaceTemplate.objects.count() == 0
    assert AuditLog.objects.filter(action=AuditLog.Action.CONSENT).exists()


@pytest.mark.django_db
def test_consent_requires_document(client, org, users):
    org.e2.consent = 'none'; org.e2.save()
    client.force_login(users[1])
    client.post(f'/staff/{org.e2.pk}/', {'consent': 'given', 'consent_date': '2026-11-20', 'consent_doc': ''})
    org.e2.refresh_from_db()
    assert org.e2.consent == 'none'


@pytest.mark.django_db
def test_gallery_excludes_refused_and_dismissed(org, fake_engine):
    from apps.attendance import engine_service
    c = engine_service.cipher()
    v = np.ones(512, np.float32) / np.sqrt(512)
    for e in (org.e1, org.e2):
        FaceTemplate.objects.create(employee=e, model_name=engine_service.model_name(), vector=c.encrypt(v))
    org.e2.is_active = False; org.e2.save()
    assert engine_service.reload_gallery(fake_engine) == 1
    assert fake_engine.gallery.ids == [org.e1.pk]


@pytest.mark.django_db
def test_pin_is_hashed(org):
    org.e1.set_pin('1234')
    assert '1234' not in org.e1.fallback_pin and org.e1.check_pin('1234') and not org.e1.check_pin('4321')


@pytest.mark.django_db
def test_manual_mark_requires_reason_and_is_audited(client, org, users):
    client.force_login(users[2])
    client.post('/manual/', {'employee': org.e1.pk, 'when': '2026-11-20T08:05', 'direction': 'in', 'reason': ''})
    assert Ev.objects.count() == 0
    client.post('/manual/', {'employee': org.e1.pk, 'when': '2026-11-20T08:05', 'direction': 'in',
                             'reason': 'сбой камеры'})
    ev = Ev.objects.get()
    assert ev.method == Ev.Method.MANUAL and ev.created_by == users[2]
    assert AuditLog.objects.filter(action=AuditLog.Action.MANUAL_MARK).exists()


@pytest.mark.django_db
def test_manual_mark_not_for_other_department(client, org, users):
    client.force_login(users[2])
    r = client.post('/manual/', {'employee': org.e2.pk, 'when': '2026-11-20T08:05', 'direction': 'in',
                                 'reason': 'x'})
    assert r.status_code == 404 and Ev.objects.count() == 0


@pytest.mark.django_db
def test_employee_sees_only_own_marks(client, org, users):
    Ev.objects.create(employee=org.e1, direction='in', method='face')
    Ev.objects.create(employee=org.e2, direction='in', method='face')
    client.force_login(users[3])
    html = client.get('/my/').content.decode()
    assert 'Иванова Анна Сергеевна' in html and 'Петрова' not in html


@pytest.mark.django_db
def test_login_is_audited(client, org, users):
    client.post('/login/', {'username': 'k', 'password': 'Test-pass-2026'})
    assert AuditLog.objects.filter(action=AuditLog.Action.LOGIN, user=users[1]).exists()
