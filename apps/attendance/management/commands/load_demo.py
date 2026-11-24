"""Тестовые (демонстрационные) данные: подразделения, смены, сотрудники, график и отметки.

Все ФИО и отметки вымышлены и сгенерированы случайно (seed=2026), к реальным
работникам больницы отношения не имеют. Структура подразделений взята из открытых
публикаций о ГАУЗ СО «Арамильская городская больница».
"""
import os
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

import cv2
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.attendance import engine_service
from apps.attendance.models import AccessPoint, AttendanceEvent as Ev, ScheduleEntry, Shift
from apps.core import roles
from apps.staff.models import Department, Employee, FaceTemplate, Position

DEPARTMENTS = [
    ('Хирургическое отделение', 'ХИР'),
    ('Паллиативное отделение', 'ПАЛ'),
    ('Приемное отделение', 'ПРМ'),
    ('Взрослая поликлиника', 'ВПК'),
    ('Детская поликлиника', 'ДПК'),
    ('ОВП мкр. Гарнизон', 'ОВП1'),
    ('Администрация', 'АДМ'),
]
POSITIONS = [
    ('Врач-хирург', 'doctor'), ('Врач-терапевт участковый', 'doctor'), ('Врач-педиатр участковый', 'doctor'),
    ('Врач по паллиативной медицинской помощи', 'doctor'), ('Медицинская сестра палатная', 'nurse'),
    ('Медицинская сестра процедурной', 'nurse'), ('Медицинская сестра участковая', 'nurse'),
    ('Фельдшер', 'nurse'), ('Санитар', 'other'), ('Регистратор', 'other'), ('Специалист по кадрам', 'admin'),
    ('Заведующий отделением', 'doctor'),
]
SHIFTS = [('Дневная', 'Д', time(8, 0), '8.0'), ('Суточное дежурство', 'С', time(8, 0), '24.0'),
          ('Ночная', 'Н', time(20, 0), '12.0'), ('Поликлиника', 'П', time(8, 0), '7.8')]
LAST = ['Иванова', 'Петрова', 'Смирнова', 'Кузнецова', 'Попова', 'Соколова', 'Лебедева', 'Козлова', 'Новикова',
        'Морозова', 'Волкова', 'Алексеева', 'Павлова', 'Семенова', 'Голубева', 'Виноградова', 'Богданова',
        'Воробьева', 'Федорова', 'Михайлова', 'Беляева', 'Тарасова', 'Белова', 'Комарова', 'Орлова', 'Киселева']
LAST_M = ['Иванов', 'Петров', 'Смирнов', 'Кузнецов', 'Попов', 'Соколов', 'Лебедев', 'Козлов', 'Новиков',
          'Морозов', 'Волков', 'Алексеев', 'Павлов', 'Семенов', 'Голубев', 'Виноградов']
FIRST_F = ['Анна', 'Мария', 'Елена', 'Ольга', 'Наталья', 'Ирина', 'Светлана', 'Татьяна', 'Юлия', 'Екатерина']
FIRST_M = ['Алексей', 'Дмитрий', 'Сергей', 'Андрей', 'Игорь', 'Максим', 'Олег', 'Павел']
MID_F = ['Александровна', 'Сергеевна', 'Викторовна', 'Игоревна', 'Андреевна', 'Николаевна']
MID_M = ['Александрович', 'Сергеевич', 'Викторович', 'Игоревич', 'Андреевич']

STAFF_PLAN = {   # подразделение: [(должность, число, график)]
    'ХИР': [('Заведующий отделением', 1, 'Д'), ('Врач-хирург', 3, 'С'), ('Медицинская сестра палатная', 6, 'С'),
            ('Медицинская сестра процедурной', 1, 'Д'), ('Санитар', 3, 'С')],
    'ПАЛ': [('Врач по паллиативной медицинской помощи', 2, 'Д'), ('Медицинская сестра палатная', 6, 'С'),
            ('Санитар', 4, 'С')],
    'ПРМ': [('Фельдшер', 3, 'С'), ('Медицинская сестра палатная', 3, 'Н'), ('Санитар', 2, 'С')],
    'ВПК': [('Врач-терапевт участковый', 4, 'П'), ('Медицинская сестра участковая', 4, 'П'), ('Регистратор', 3, 'П')],
    'ДПК': [('Врач-педиатр участковый', 3, 'П'), ('Медицинская сестра участковая', 3, 'П'), ('Регистратор', 2, 'П')],
    'ОВП1': [('Фельдшер', 1, 'П'), ('Медицинская сестра участковая', 1, 'П')],
    'АДМ': [('Специалист по кадрам', 2, 'П')],
}


def pattern(code, emp_idx, day_idx):
    """Работает ли сотрудник в этот день: сутки через трое, ночь через двое, пятидневка."""
    if code == 'С':
        return (day_idx + emp_idx) % 4 == 0
    if code == 'Н':
        return (day_idx + emp_idx) % 3 == 0
    return (day_idx % 7) < 5


class Command(BaseCommand):
    help = 'Загружает тестовые данные (вымышленные сотрудники и отметки)'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='Demo-2026-pass')
        parser.add_argument('--days', type=int, default=45, help='сколько прошедших дней заполнить отметками')
        parser.add_argument('--faces', default='', help='папка с фото <табельный номер>.jpg для эталонов')

    @transaction.atomic
    def handle(self, *args, **o):
        rnd = random.Random(2026)
        call_command('init_roles', stdout=open(os.devnull, 'w'))
        deps = {code: Department.objects.get_or_create(code=code, defaults={'name': name})[0]
                for name, code in DEPARTMENTS}
        pos = {n: Position.objects.get_or_create(name=n, defaults={'category': c})[0] for n, c in POSITIONS}
        shifts = {c: Shift.objects.get_or_create(code=c, defaults={'name': n, 'start': t,
                                                                   'duration_hours': Decimal(h)})[0]
                  for n, c, t, h in SHIFTS}
        point_main, _ = AccessPoint.objects.get_or_create(
            name='Служебный вход стационара', defaults={'building': 'ул. Садовая, 10', 'token_hash': 'demo-main'})
        point_pk, _ = AccessPoint.objects.get_or_create(
            name='Служебный вход детской поликлиники', defaults={'building': 'Детская поликлиника',
                                                                 'token_hash': 'demo-child'})
        token = point_main.issue_token()
        point_main.save()

        n = 0
        plan = []
        for code, rows in STAFF_PLAN.items():
            for pname, count, shift_code in rows:
                for _ in range(count):
                    n += 1
                    male = rnd.random() < 0.25 or pname.startswith('Врач-хирург')
                    emp, _ = Employee.objects.get_or_create(personnel_number=f'{n:05d}', defaults=dict(
                        last_name=rnd.choice(LAST_M if male else LAST),
                        first_name=rnd.choice(FIRST_M if male else FIRST_F),
                        middle_name=rnd.choice(MID_M if male else MID_F),
                        department=deps[code], position=pos[pname],
                        consent=Employee.Consent.GIVEN if rnd.random() < 0.93 else Employee.Consent.REFUSED,
                        consent_date=timezone.localdate() - timedelta(days=60), consent_doc=f'Согласие № {n}'))
                    if emp.consent == Employee.Consent.REFUSED:
                        emp.consent_doc = ''
                        emp.set_pin('2468')
                        emp.save()
                    plan.append((emp, shift_code))

        def mk_user(username, role, first, last, employee=None, head_of=None):
            u, created = User.objects.get_or_create(username=username, defaults={'first_name': first, 'last_name': last})
            if created:
                u.set_password(o['password'])
                u.save()
            u.groups.add(Group.objects.get(name=role))
            if employee:
                employee.user = u
                employee.save()
            if head_of:
                head_of.head = u
                head_of.save()
            return u

        admin = mk_user('admin', roles.ADMIN, 'Администратор', 'Системы')
        admin.is_staff = admin.is_superuser = True
        admin.save()
        hr_emp = Employee.objects.filter(department=deps['АДМ']).first()
        mk_user('kadry', roles.HR, hr_emp.first_name, hr_emp.last_name, employee=hr_emp)
        head_emp = Employee.objects.filter(department=deps['ХИР'], position=pos['Заведующий отделением']).first()
        mk_user('zav_hir', roles.HEAD, head_emp.first_name, head_emp.last_name, employee=head_emp,
                head_of=deps['ХИР'])
        nurse = Employee.objects.filter(department=deps['ХИР'], position=pos['Медицинская сестра палатная']).first()
        mk_user('rabotnik', roles.EMPLOYEE, nurse.first_name, nurse.last_name, employee=nurse)

        # график на прошлый, текущий и следующий месяц
        today = timezone.localdate()
        first = (today.replace(day=1) - timedelta(days=40)).replace(day=1)
        last = (today.replace(day=28) + timedelta(days=40)).replace(day=1) - timedelta(days=1)
        ScheduleEntry.objects.filter(date__gte=first, date__lte=last).delete()
        entries = []
        for i, (emp, code) in enumerate(plan):
            d, k = first, 0
            while d <= last:
                if pattern(code, i, k):
                    entries.append(ScheduleEntry(employee=emp, date=d, shift=shifts[code]))
                d += timedelta(days=1)
                k += 1
        ScheduleEntry.objects.bulk_create(entries)

        # отметки за прошедшие дни
        Ev.objects.all().delete()
        tz = timezone.get_current_timezone()
        now = timezone.now()
        evs = []
        start_day = today - timedelta(days=o['days'])
        for e in ScheduleEntry.objects.filter(date__gte=start_day, date__lte=today).select_related('shift', 'employee'):
            emp = e.employee
            r = rnd.random()
            if r < 0.025:
                continue                                    # неявка
            s_start = timezone.make_aware(datetime.combine(e.date, e.shift.start), tz)
            s_end = s_start + timedelta(hours=float(e.shift.duration_hours))
            late = rnd.choice([0] * 12 + [7, 12, 25]) if r < 0.9 else 0
            t_in = s_start - timedelta(minutes=rnd.randint(3, 20)) + timedelta(minutes=late)
            t_out = s_end + timedelta(minutes=rnd.randint(0, 25)) - timedelta(minutes=rnd.choice([0] * 15 + [30]))
            face = emp.consent == Employee.Consent.GIVEN
            point = point_pk if emp.department.code == 'ДПК' else point_main
            for ts, direction in ((t_in, Ev.Direction.IN), (t_out, Ev.Direction.OUT)):
                if ts > now:
                    continue
                pending = (not face) and (today - ts.astimezone(tz).date()).days < 2
                review = face and rnd.random() < 0.02 and (today - ts.astimezone(tz).date()).days < 3
                evs.append(Ev(employee=emp, point=point, timestamp=ts, direction=direction,
                              method=Ev.Method.FACE if face else Ev.Method.FALLBACK,
                              status=Ev.Status.PENDING if (pending or review) else Ev.Status.CONFIRMED,
                              score=round(rnd.uniform(0.38, 0.44), 3) if review else
                              (round(rnd.uniform(0.55, 0.85), 3) if face else None),
                              liveness=round(rnd.uniform(0.8, 0.99), 3) if face else None,
                              reason='сходство ниже порога допуска' if review else
                              ('запасная отметка, требует подтверждения' if pending else '')))
        Ev.objects.bulk_create(evs)

        if o['faces']:
            engine = engine_service.get_engine()
            c = engine_service.cipher()
            for fn in sorted(os.listdir(o['faces'])):
                num = os.path.splitext(fn)[0]
                emp = Employee.objects.filter(personnel_number=num).first()
                if emp is None or not emp.biometrics_allowed:
                    continue
                vec, q = engine.enroll([cv2.imread(os.path.join(o['faces'], fn))])
                FaceTemplate.objects.filter(employee=emp).delete()
                FaceTemplate.objects.create(employee=emp, model_name=engine_service.model_name(),
                                            vector=c.encrypt(vec), quality=q, created_by=admin)
                self.stdout.write(f'эталон: {emp.short_name} ({q:.2f})')

        self.stdout.write(self.style.SUCCESS(
            f'Сотрудников: {Employee.objects.count()}, записей графика: {len(entries)}, отметок: {len(evs)}'))
        self.stdout.write(f'Пароль тестовых пользователей admin, kadry, zav_hir, rabotnik: {o["password"]}')
        self.stdout.write(f'Терминал стационара: /kiosk/?key={token}')
