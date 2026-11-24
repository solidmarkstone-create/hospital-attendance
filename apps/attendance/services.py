"""Бизнес-логика учета: регистрация отметок, табель, отчет об опозданиях."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.staff.models import Employee
from recognition.types import Decision

from .models import AccessPoint, AttendanceEvent, ScheduleEntry

Ev = AttendanceEvent


def _rules():
    return settings.ATTENDANCE


def next_direction(employee: Employee, when) -> str:
    """Приход или уход: если последняя отметка – незакрытый приход за последние 26 ч, то уход."""
    since = when - timedelta(hours=_rules()['OPEN_SHIFT_HOURS'])
    last = (Ev.objects.filter(employee=employee, timestamp__gte=since, timestamp__lte=when)
            .exclude(status=Ev.Status.REJECTED).order_by('-timestamp').first())
    return Ev.Direction.OUT if last and last.direction == Ev.Direction.IN else Ev.Direction.IN


def recent_duplicate(employee: Employee, when):
    since = when - timedelta(seconds=_rules()['REPEAT_SECONDS'])
    return (Ev.objects.filter(employee=employee, timestamp__gte=since, timestamp__lte=when)
            .exclude(status=Ev.Status.REJECTED).order_by('-timestamp').first())


@transaction.atomic
def register_event(*, employee, point, method, status=Ev.Status.CONFIRMED, score=None, liveness=None,
                   reason='', user=None, when=None, direction=None):
    """Создает отметку. Повтор в течение 2 минут возвращает уже существующую отметку."""
    when = when or timezone.now()
    if employee is not None:
        Employee.objects.select_for_update().filter(pk=employee.pk).first()   # одна отметка за раз
        dup = recent_duplicate(employee, when)
        if dup is not None and direction is None:
            return dup, False
        direction = direction or next_direction(employee, when)
    return Ev.objects.create(employee=employee, point=point, timestamp=when, direction=direction or Ev.Direction.IN,
                             method=method, status=status, score=score, liveness=liveness, reason=reason,
                             created_by=user), True


def handle_recognition(result, point: AccessPoint) -> dict:
    """Перевод решения движка в отметку журнала и ответ терминалу."""
    m = result.match
    employee = None
    if m and m.employee_id is not None and result.decision in (Decision.ACCEPT, Decision.REVIEW):
        employee = Employee.objects.filter(pk=m.employee_id, is_active=True).first()
    payload = result.as_dict()
    payload.pop('employee_id', None)            # терминал не получает служебный идентификатор
    if result.decision == Decision.ACCEPT and employee:
        ev, created = register_event(employee=employee, point=point, method=Ev.Method.FACE, score=m.score,
                                     liveness=result.liveness)
        payload.update(employee=employee.short_name, direction=ev.get_direction_display(),
                       time=timezone.localtime(ev.timestamp).strftime('%H:%M'), repeated=not created)
    elif result.decision == Decision.REVIEW and employee:
        ev, created = register_event(employee=employee, point=point, method=Ev.Method.FACE,
                                     status=Ev.Status.PENDING, score=m.score, liveness=result.liveness,
                                     reason=f'сходство {m.score:.2f} ниже порога допуска')
        payload.update(employee=None, direction=ev.get_direction_display(), repeated=not created)
    elif result.decision == Decision.SPOOF:
        # кто пытался отметиться, неизвестно: событие без сотрудника для разбора администратором
        Ev.objects.create(employee=None, point=point, direction=Ev.Direction.IN, method=Ev.Method.FACE,
                          status=Ev.Status.PENDING, liveness=result.liveness,
                          reason=f'не пройдена проверка живости ({result.liveness:.2f})')
    return payload


# ---------------------------------------------------------------- табель
DAY_WORK, DAY_ABSENT, DAY_OFF, DAY_OPEN, DAY_PLAN = 'Я', 'НН', 'В', 'Я*', ''


@dataclass
class DayCell:
    code: str
    hours: Decimal = Decimal('0')
    late_min: int = 0
    early_min: int = 0
    shift: str = ''


@dataclass
class TimesheetRow:
    employee: Employee
    days: list = field(default_factory=list)

    @property
    def total_hours(self):
        return sum((d.hours for d in self.days), Decimal('0'))

    @property
    def worked_days(self):
        return sum(1 for d in self.days if d.code in (DAY_WORK, DAY_OPEN))

    @property
    def absences(self):
        return sum(1 for d in self.days if d.code == DAY_ABSENT)

    @property
    def late_count(self):
        return sum(1 for d in self.days if d.late_min > 0)


def intervals(events):
    """Пары «приход – уход» из подтвержденных отметок одного сотрудника (по времени)."""
    out, open_in = [], None
    limit = timedelta(hours=_rules()['OPEN_SHIFT_HOURS'])
    for e in events:
        if e.direction == Ev.Direction.IN:
            if open_in is not None:
                out.append((open_in, None))        # предыдущий приход без ухода
            open_in = e.timestamp
        elif open_in is not None and e.timestamp - open_in <= limit:
            out.append((open_in, e.timestamp))
            open_in = None
    if open_in is not None:
        out.append((open_in, None))
    return out


def month_days(year, month):
    n = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, n + 1)]


def build_timesheet(year: int, month: int, employees):
    """Табель за месяц: часы по дням, коды Я, НН, В, Я* (нет отметки ухода)."""
    days = month_days(year, month)
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(timezone.datetime.combine(days[0], timezone.datetime.min.time()), tz)
    end = start + timedelta(days=len(days) + 1)
    tol = _rules()['LATE_TOLERANCE_MIN']
    today = timezone.localdate()
    employees = list(employees)
    sched = {(s.employee_id, s.date): s.shift for s in
             ScheduleEntry.objects.filter(employee__in=employees, date__in=days).select_related('shift')}
    rows = []
    for emp in employees:
        evs = list(Ev.objects.filter(employee=emp, status=Ev.Status.CONFIRMED,
                                     timestamp__gte=start - timedelta(hours=1), timestamp__lt=end)
                   .order_by('timestamp'))
        by_day: dict = {}
        for t_in, t_out in intervals(evs):
            by_day.setdefault(timezone.localtime(t_in, tz).date(), []).append((t_in, t_out))
        row = TimesheetRow(emp)
        for d in days:
            shift = sched.get((emp.pk, d))
            ints = by_day.get(d, [])
            if not ints:
                if d >= today:          # смена еще не закончилась или впереди: неявку не ставим
                    row.days.append(DayCell(DAY_PLAN if shift else DAY_OFF, shift=shift.code if shift else ''))
                else:
                    row.days.append(DayCell(DAY_ABSENT if shift else DAY_OFF, shift=shift.code if shift else ''))
                continue
            closed = [(a, b) for a, b in ints if b is not None]
            hours = sum(((b - a).total_seconds() for a, b in closed), 0.0) / 3600
            cell = DayCell(DAY_WORK if len(closed) == len(ints) else DAY_OPEN,
                           Decimal(str(round(hours, 1))), shift=shift.code if shift else '')
            if shift:
                s_start, s_end = shift.bounds(d)
                first_in = min(a for a, _ in ints)
                late = (first_in - s_start).total_seconds() / 60
                if late > tol:
                    cell.late_min = int(late)
                if closed:
                    last_out = max(b for _, b in closed)
                    early = (s_end - last_out).total_seconds() / 60
                    if early > tol:
                        cell.early_min = int(early)
            row.days.append(cell)
        rows.append(row)
    return days, rows


def lateness_report(year, month, employees):
    days, rows = build_timesheet(year, month, employees)
    items = []
    for r in rows:
        for d, c in zip(days, r.days):
            if c.late_min or c.early_min or c.code == DAY_ABSENT:
                items.append({'employee': r.employee, 'date': d, 'shift': c.shift, 'code': c.code,
                              'late_min': c.late_min, 'early_min': c.early_min})
    return items
