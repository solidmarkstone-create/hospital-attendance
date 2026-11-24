"""Служебные команды: роли, точка прохода, тестовые данные; регистрация эталона снимками с камеры."""
import base64
import json
from io import StringIO

import cv2
import numpy as np
import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.attendance.models import AccessPoint, AttendanceEvent, ScheduleEntry
from apps.core import roles
from apps.staff.models import Employee, FaceTemplate


@pytest.mark.django_db
def test_init_roles_idempotent():
    call_command('init_roles', stdout=StringIO())
    call_command('init_roles', stdout=StringIO())
    assert set(Group.objects.values_list('name', flat=True)) == set(roles.ALL_ROLES)


@pytest.mark.django_db
def test_create_point_prints_working_key(client):
    out = StringIO()
    call_command('create_point', 'Служебный вход', 'Стационар', stdout=out)
    key = out.getvalue().split('key=')[1].strip()
    p = AccessPoint.objects.get()
    assert AccessPoint.by_token(key) == p and key not in p.token_hash


@pytest.mark.django_db
def test_load_demo_creates_consistent_data():
    out = StringIO()
    call_command('load_demo', days=10, stdout=out)
    assert Employee.objects.count() == 57
    assert ScheduleEntry.objects.exists() and AttendanceEvent.objects.exists()
    # у сотрудников без согласия нет эталонов и все отметки – по PIN
    refused = Employee.objects.exclude(consent=Employee.Consent.GIVEN)
    assert not FaceTemplate.objects.filter(employee__in=refused).exists()
    assert not AttendanceEvent.objects.filter(employee__in=refused, method='face').exists()
    assert 'kiosk/?key=' in out.getvalue()


@pytest.mark.django_db
def test_enroll_from_camera_frames(client, org, user_factory, fake_engine):
    img = np.random.default_rng(1).integers(0, 255, (120, 160, 3), dtype=np.uint8)
    data = 'data:image/jpeg;base64,' + base64.b64encode(cv2.imencode('.jpg', img)[1].tobytes()).decode()
    client.force_login(user_factory('k', roles.HR))
    r = client.post(f'/staff/{org.e1.pk}/enroll/', {'camera_frames': json.dumps([data, data, data])})
    assert r.status_code == 302 and FaceTemplate.objects.filter(employee=org.e1).count() == 1


@pytest.mark.django_db
def test_enroll_without_photos_shows_error(client, org, user_factory, fake_engine):
    client.force_login(user_factory('k', roles.HR))
    r = client.post(f'/staff/{org.e1.pk}/enroll/', {})
    assert r.status_code == 200 and FaceTemplate.objects.count() == 0
    assert 'Эталон не создан' in r.content.decode()


@pytest.mark.django_db
def test_template_delete_and_pin(client, org, user_factory):
    t = FaceTemplate.objects.create(employee=org.e1, model_name='w600k_r50', vector=b'x')
    client.force_login(user_factory('k', roles.HR))
    client.post(f'/staff/{org.e1.pk}/templates/{t.pk}/delete/')
    assert FaceTemplate.objects.count() == 0
    client.post(f'/staff/{org.e1.pk}/pin/', {'pin': '12'})            # слишком короткий
    org.e1.refresh_from_db()
    assert org.e1.fallback_pin == ''
    client.post(f'/staff/{org.e1.pk}/pin/', {'pin': '4821'})
    org.e1.refresh_from_db()
    assert org.e1.check_pin('4821')


@pytest.mark.django_db
def test_employee_create_and_edit(client, org, user_factory):
    client.force_login(user_factory('k', roles.HR))
    r = client.post('/staff/new/', {'personnel_number': '00099', 'last_name': 'Смирнова', 'first_name': 'Ольга',
                                     'middle_name': '', 'department': org.surg.pk, 'position': org.nurse.pk,
                                     'is_active': 'on'})
    assert r.status_code == 302 and Employee.objects.filter(personnel_number='00099').exists()
