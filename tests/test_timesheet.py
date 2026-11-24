"""Табель: часы, неявки, опоздания, ночные смены и суточные дежурства."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.attendance.models import AttendanceEvent as Ev, ScheduleEntry
from apps.attendance.services import DAY_ABSENT, DAY_OFF, DAY_OPEN, DAY_WORK, build_timesheet, intervals, lateness_report
from apps.core import roles

D = date(2026, 10, 5)     # прошедший месяц, чтобы не зависеть от текущей даты


def at(day, hh, mm=0):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()) + timedelta(hours=hh, minutes=mm))


def ev(emp, when, direction, status=Ev.Status.CONFIRMED):
    return Ev.objects.create(employee=emp, timestamp=when, direction=direction, method=Ev.Method.FACE, status=status)


def cell(rows, emp, day):
    row = next(r for r in rows if r.employee == emp)
    return row.days[day.day - 1], row


@pytest.mark.django_db
def test_day_shift_hours_and_lateness(org):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.day)
    ev(org.e1, at(D, 8, 12), 'in')               # опоздание 12 мин
    ev(org.e1, at(D, 16, 0), 'out')
    days, rows = build_timesheet(2026, 10, [org.e1])
    c, row = cell(rows, org.e1, D)
    assert len(days) == 31
    assert c.code == DAY_WORK and c.hours == Decimal('7.8') and c.late_min == 12 and c.early_min == 0
    assert row.total_hours == Decimal('7.8') and row.late_count == 1


@pytest.mark.django_db
def test_arrival_within_tolerance_is_not_late(org):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.day)
    ev(org.e1, at(D, 8, 4), 'in'); ev(org.e1, at(D, 16, 5), 'out')
    c, _ = cell(build_timesheet(2026, 10, [org.e1])[1], org.e1, D)
    assert c.late_min == 0


@pytest.mark.django_db
def test_absence_and_day_off(org):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.day)
    _, rows = build_timesheet(2026, 10, [org.e1])
    assert cell(rows, org.e1, D)[0].code == DAY_ABSENT
    assert cell(rows, org.e1, D + timedelta(days=1))[0].code == DAY_OFF
    assert rows[0].absences == 1


@pytest.mark.django_db
def test_24h_duty_counted_on_start_day(org):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.duty)
    ev(org.e1, at(D, 7, 50), 'in')
    ev(org.e1, at(D + timedelta(days=1), 8, 10), 'out')
    _, rows = build_timesheet(2026, 10, [org.e1])
    c, _ = cell(rows, org.e1, D)
    nxt, _ = cell(rows, org.e1, D + timedelta(days=1))
    assert c.hours == Decimal('24.3') and nxt.code == DAY_OFF


@pytest.mark.django_db
def test_night_shift_early_leave(org):
    ScheduleEntry.objects.create(employee=org.e2, date=D, shift=org.night)
    ev(org.e2, at(D, 19, 55), 'in')
    ev(org.e2, at(D + timedelta(days=1), 7, 30), 'out')     # смена до 08:00
    c, _ = cell(build_timesheet(2026, 10, [org.e2])[1], org.e2, D)
    assert c.hours == Decimal('11.6') and c.early_min == 30


@pytest.mark.django_db
def test_missing_out_marked_open(org):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.day)
    ev(org.e1, at(D, 8, 0), 'in')
    c, _ = cell(build_timesheet(2026, 10, [org.e1])[1], org.e1, D)
    assert c.code == DAY_OPEN and c.hours == 0


@pytest.mark.django_db
def test_pending_and_rejected_not_counted(org):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.day)
    ev(org.e1, at(D, 8, 0), 'in', Ev.Status.PENDING)
    ev(org.e1, at(D, 16, 0), 'out', Ev.Status.REJECTED)
    c, _ = cell(build_timesheet(2026, 10, [org.e1])[1], org.e1, D)
    assert c.code == DAY_ABSENT


def test_intervals_pairs_and_limits():
    class E:
        def __init__(self, t, d):
            self.timestamp, self.direction = t, d
    base = at(D, 8)
    evs = [E(base, 'in'), E(base + timedelta(hours=8), 'out'),
           E(base + timedelta(days=1), 'in'), E(base + timedelta(days=3), 'out')]   # уход через 48 ч не закрывает
    res = intervals(evs)
    assert res[0] == (base, base + timedelta(hours=8)) and res[1][1] is None


@pytest.mark.django_db
def test_lateness_report(org):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.day)
    ScheduleEntry.objects.create(employee=org.e1, date=D + timedelta(days=1), shift=org.day)
    ev(org.e1, at(D, 8, 30), 'in'); ev(org.e1, at(D, 16, 0), 'out')
    items = lateness_report(2026, 10, [org.e1])
    assert [(i['date'], i['code'], i['late_min']) for i in items] == [(D, DAY_WORK, 30),
                                                                      (D + timedelta(days=1), DAY_ABSENT, 0)]


@pytest.mark.django_db
def test_timesheet_csv_export(client, org, user_factory):
    ScheduleEntry.objects.create(employee=org.e1, date=D, shift=org.day)
    ev(org.e1, at(D, 8, 0), 'in'); ev(org.e1, at(D, 16, 0), 'out')
    client.force_login(user_factory('k', roles.HR))
    r = client.get(f'/timesheet/?month=2026-10&dep={org.surg.pk}&format=csv')
    text = r.content.decode('utf-8-sig')
    assert r['Content-Type'].startswith('text/csv')
    assert 'Иванова Анна Сергеевна' in text and 'Я 8.0' in text and ';8,0;' in text


@pytest.mark.django_db
def test_head_timesheet_only_own_department(client, org, user_factory):
    client.force_login(user_factory('z', roles.HEAD, head_of=org.surg))
    html = client.get(f'/timesheet/?month=2026-10&dep={org.pal.pk}').content.decode()
    assert 'Иванова' in html and 'Петрова' not in html      # чужое отделение подменяется своим


@pytest.mark.django_db
def test_future_shift_is_not_absence(org):
    today = timezone.localdate()
    ScheduleEntry.objects.create(employee=org.e1, date=today + timedelta(days=1), shift=org.day)
    ScheduleEntry.objects.create(employee=org.e1, date=today, shift=org.day)
    nxt = today + timedelta(days=1)
    for d in (today, nxt):
        days, rows = build_timesheet(d.year, d.month, [org.e1])
        c = rows[0].days[d.day - 1]
        assert c.code == '' and c.shift == 'Д'          # смена сегодня или впереди – не неявка


def test_consent_date_widget_iso(db):
    from apps.staff.forms import ConsentForm
    from apps.staff.models import Employee
    html = str(ConsentForm(instance=Employee(consent='given', consent_date=date(2026, 9, 21)))['consent_date'])
    assert 'value="2026-09-21"' in html
