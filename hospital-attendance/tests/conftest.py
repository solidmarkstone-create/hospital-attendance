"""Общие заготовки тестов.

Модульные тесты не загружают нейросети: вместо них FakeEngine с заданными ответами.
Тесты с настоящими моделями помечены @pytest.mark.models и пропускаются, если моделей нет.
"""
import os
from datetime import time
from decimal import Decimal

import numpy as np
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.models import Group, User

from apps.attendance import engine_service
from apps.attendance.models import AccessPoint, Shift
from apps.core import roles
from apps.staff.models import Department, Employee, Position
from recognition.matcher import Gallery, Thresholds
from recognition.types import Decision, EngineResult, Match

MODELS_DIR = os.environ.get('FACE_MODELS_DIR', '/root/models128')
LFW_DIR = os.environ.get('LFW_DIR', os.path.join(MODELS_DIR, 'lfw', 'lfw'))


@pytest.fixture(autouse=True)
def _biometric_key(settings):
    settings.BIOMETRIC_KEY = Fernet.generate_key().decode()
    settings.STORAGES = {'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
    yield
    engine_service.set_engine(None)


class FakeEngine:
    """Заглушка движка: возвращает заранее заданное решение, считает вызовы."""

    def __init__(self, result=None, vector=None):
        self.result = result
        self.vector = vector if vector is not None else np.ones(512, np.float32) / np.sqrt(512)
        self.gallery = Gallery()
        self.cfg = type('C', (), {'thresholds': Thresholds()})()
        self.calls = 0
        self.frames_seen = 0

    def identify(self, frames):
        self.calls += 1
        self.frames_seen += len(frames)
        return self.result

    def enroll(self, photos):
        return self.vector, 0.8


@pytest.fixture
def fake_engine():
    eng = FakeEngine()
    engine_service.set_engine(eng)
    yield eng
    engine_service.set_engine(None)


@pytest.fixture
def make_result():
    def make(decision, emp=None, score=0.7, liveness=0.95):
        m = Match(employee_id=emp.pk if emp else None, score=score) if decision != Decision.NO_FACE else None
        return EngineResult(decision, match=m, liveness=liveness, quality=0.8, frame_index=0,
                            message={'accept': 'Отметка принята.'}.get(decision.value, 'msg'))
    return make


@pytest.fixture
def groups(db):
    return {r: Group.objects.get_or_create(name=r)[0] for r in roles.ALL_ROLES}


@pytest.fixture
def org(db, groups):
    """Два отделения, по сотруднику в каждом, смены и точка прохода."""
    surg = Department.objects.create(name='Хирургическое отделение', code='ХИР')
    pal = Department.objects.create(name='Паллиативное отделение', code='ПАЛ')
    nurse = Position.objects.create(name='Медицинская сестра палатная', category='nurse')
    e1 = Employee.objects.create(personnel_number='00001', last_name='Иванова', first_name='Анна',
                                 middle_name='Сергеевна', department=surg, position=nurse, consent='given')
    e2 = Employee.objects.create(personnel_number='00002', last_name='Петрова', first_name='Мария',
                                 department=pal, position=nurse, consent='given')
    day = Shift.objects.create(name='Дневная', code='Д', start=time(8, 0), duration_hours=Decimal('8.0'))
    duty = Shift.objects.create(name='Суточное дежурство', code='С', start=time(8, 0), duration_hours=Decimal('24.0'))
    night = Shift.objects.create(name='Ночная', code='Н', start=time(20, 0), duration_hours=Decimal('12.0'))
    point = AccessPoint(name='Служебный вход', building='Стационар')
    token = point.issue_token()
    point.save()
    return type('Org', (), dict(surg=surg, pal=pal, e1=e1, e2=e2, day=day, duty=duty, night=night,
                                point=point, token=token, nurse=nurse))


@pytest.fixture
def user_factory(db, groups):
    def make(username, role=None, employee=None, head_of=None):
        u = User.objects.create_user(username, password='Test-pass-2026')
        if role:
            u.groups.add(groups[role])
        if employee:
            employee.user = u
            employee.save()
        if head_of:
            head_of.head = u
            head_of.save()
        return u
    return make


@pytest.fixture
def login(client):
    def do(user):
        client.force_login(user)
        return client
    return do
