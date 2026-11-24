import csv
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.imaging import frames_from_request
from apps.core.models import AuditLog, audit
from apps.core.roles import (can_review, can_view_reports, has_role, managed_departments, require,
                             EMPLOYEE)
from apps.staff.models import Department, Employee

from . import engine_service
from .models import AccessPoint, AttendanceEvent as Ev
from .services import build_timesheet, handle_recognition, lateness_report, register_event


# ---------------------------------------------------------------- терминал на входе
def kiosk(request):
    """Экран терминала. Ключ точки прохода передается в адресе один раз и хранится в браузере терминала."""
    return render(request, 'attendance/kiosk.html')


def _kiosk_point(request):
    point = AccessPoint.by_token(request.headers.get('X-Kiosk-Key', ''))
    if point is None:
        raise PermissionDenied('неизвестный или отключенный терминал')
    return point


@csrf_exempt            # терминал не входит в систему, он подписывает запрос ключом точки прохода
@require_POST
def kiosk_recognize(request):
    try:
        point = _kiosk_point(request)
    except PermissionDenied:
        return JsonResponse({'decision': 'error', 'message': 'Терминал не зарегистрирован.'}, status=403)
    try:
        frames = frames_from_request(request)
    except ValueError as exc:
        return JsonResponse({'decision': 'error', 'message': str(exc)}, status=400)
    if not frames:
        return JsonResponse({'decision': 'error', 'message': 'Нет кадров с камеры.'}, status=400)
    result = engine_service.get_engine().identify(frames)
    del frames                      # кадры не сохраняются ни при каком решении
    return JsonResponse(handle_recognition(result, point))


@csrf_exempt
@require_POST
def kiosk_fallback(request):
    """Запасная отметка без биометрии: табельный номер и PIN. Отметку подтверждает руководитель."""
    try:
        point = _kiosk_point(request)
    except PermissionDenied:
        return JsonResponse({'ok': False, 'message': 'Терминал не зарегистрирован.'}, status=403)
    key = f'pinfail:{point.pk}'
    if cache.get(key, 0) >= 5:
        return JsonResponse({'ok': False, 'message': 'Слишком много ошибок. Обратитесь к администратору.'},
                            status=429)
    emp = Employee.objects.filter(personnel_number=request.POST.get('personnel_number', '').strip(),
                                  is_active=True).first()
    if emp is None or not emp.check_pin(request.POST.get('pin', '')):
        cache.set(key, cache.get(key, 0) + 1, 600)
        return JsonResponse({'ok': False, 'message': 'Неверный табельный номер или PIN.'}, status=400)
    ev, created = register_event(employee=emp, point=point, method=Ev.Method.FALLBACK, status=Ev.Status.PENDING,
                                 reason='запасная отметка, требует подтверждения')
    return JsonResponse({'ok': True, 'employee': emp.short_name, 'direction': ev.get_direction_display(),
                         'message': 'Отметка принята и будет подтверждена руководителем.'})


# ---------------------------------------------------------------- журнал и проверка
def _scope(request, qs, field='employee__department'):
    deps = managed_departments(request.user)
    if deps is None:
        return qs
    return qs.filter(**{f'{field}__in': deps})


def _parse_date(s, default):
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return default


@require(can_view_reports)
def journal(request):
    today = timezone.localdate()
    d1 = _parse_date(request.GET.get('from'), today - timedelta(days=6))
    d2 = _parse_date(request.GET.get('to'), today)
    qs = Ev.objects.select_related('employee', 'point', 'employee__department').filter(
        timestamp__date__gte=d1, timestamp__date__lte=d2)
    qs = _scope(request, qs)
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    if request.GET.get('dep'):
        qs = qs.filter(employee__department_id=request.GET['dep'])
    return render(request, 'attendance/journal.html', {
        'events': qs[:500], 'd1': d1, 'd2': d2, 'status': request.GET.get('status', ''),
        'dep': request.GET.get('dep', ''), 'statuses': Ev.Status.choices,
        'departments': _scope(request, Department.objects.all(), 'pk') if managed_departments(request.user) is None
        else managed_departments(request.user)})


@require(can_review)
def review_queue(request):
    qs = Ev.objects.select_related('employee', 'point').filter(status=Ev.Status.PENDING)
    deps = managed_departments(request.user)
    if deps is not None:
        qs = qs.filter(employee__department__in=deps)     # события без сотрудника видит только админ и кадры
    return render(request, 'attendance/review.html', {'events': qs.order_by('timestamp')})


@require(can_review)
@require_POST
def review_decide(request, pk):
    ev = get_object_or_404(Ev, pk=pk, status=Ev.Status.PENDING)
    deps = managed_departments(request.user)
    if deps is not None and (ev.employee is None or not deps.filter(pk=ev.employee.department_id).exists()):
        raise PermissionDenied
    ok = request.POST.get('decision') == 'confirm'
    if ok and ev.employee is None:
        messages.error(request, 'Нельзя подтвердить отметку, у которой не указан сотрудник.')
        return redirect('review_queue')
    ev.status = Ev.Status.CONFIRMED if ok else Ev.Status.REJECTED
    ev.reviewed_by, ev.reviewed_at = request.user, timezone.now()
    ev.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    audit(request, AuditLog.Action.REVIEW, ev, 'подтверждена' if ok else 'отклонена')
    messages.success(request, 'Отметка подтверждена.' if ok else 'Отметка отклонена.')
    return redirect('review_queue')


@require(can_review)
def manual_mark(request):
    """Ручная отметка (забыл отметиться, сбой камеры). Причина обязательна, действие пишется в аудит."""
    emps = _scope(request, Employee.objects.filter(is_active=True), 'department')
    if request.method == 'POST':
        emp = get_object_or_404(emps, pk=request.POST.get('employee'))
        reason = request.POST.get('reason', '').strip()
        try:
            when = timezone.make_aware(datetime.strptime(request.POST.get('when', ''), '%Y-%m-%dT%H:%M'))
        except ValueError:
            when = None
        direction = request.POST.get('direction')
        if not reason or when is None or direction not in (Ev.Direction.IN, Ev.Direction.OUT):
            messages.error(request, 'Укажите сотрудника, время, направление и причину.')
        elif when > timezone.now():
            messages.error(request, 'Нельзя поставить отметку на будущее время.')
        else:
            ev, _ = register_event(employee=emp, point=None, method=Ev.Method.MANUAL, reason=reason,
                                   user=request.user, when=when, direction=direction)
            audit(request, AuditLog.Action.MANUAL_MARK, ev, reason)
            messages.success(request, 'Ручная отметка сохранена.')
            return redirect('journal')
    return render(request, 'attendance/manual.html', {'employees': emps.select_related('department')})


# ---------------------------------------------------------------- табель и отчеты
def _month(request):
    today = timezone.localdate()
    try:
        y, m = map(int, request.GET.get('month', f'{today:%Y-%m}').split('-'))
        date(y, m, 1)
    except ValueError:
        y, m = today.year, today.month
    return y, m


def _dep_employees(request):
    deps = managed_departments(request.user)
    allowed = Department.objects.all() if deps is None else deps
    dep = allowed.filter(pk=request.GET.get('dep')).first() or allowed.first()
    emps = Employee.objects.filter(department=dep, is_active=True) if dep else Employee.objects.none()
    return allowed, dep, emps


@require(can_view_reports)
def timesheet(request):
    y, m = _month(request)
    allowed, dep, emps = _dep_employees(request)
    days, rows = build_timesheet(y, m, emps)
    if request.GET.get('format') == 'csv':
        audit(request, AuditLog.Action.EXPORT, dep, f'{m:02d}.{y}')
        resp = HttpResponse(content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="timesheet_{y}_{m:02d}.csv"'
        resp.write('﻿')
        w = csv.writer(resp, delimiter=';')
        w.writerow(['Табельный номер', 'Сотрудник', 'Должность'] + [d.day for d in days] +
                   ['Дней', 'Часов', 'Неявок', 'Опозданий'])
        for r in rows:
            w.writerow([r.employee.personnel_number, r.employee.full_name, r.employee.position.name] +
                       [f'{c.code} {c.hours}'.strip() if c.hours else c.code for c in r.days] +
                       [r.worked_days, str(r.total_hours).replace('.', ','), r.absences, r.late_count])
        return resp
    return render(request, 'attendance/timesheet.html', {
        'days': days, 'rows': rows, 'departments': allowed, 'dep': dep, 'month': f'{y}-{m:02d}'})


@require(can_view_reports)
def lateness(request):
    y, m = _month(request)
    allowed, dep, emps = _dep_employees(request)
    return render(request, 'attendance/lateness.html', {
        'items': lateness_report(y, m, emps), 'departments': allowed, 'dep': dep, 'month': f'{y}-{m:02d}'})


def my_attendance(request):
    """Работник видит только свои отметки (принцип открытости системы, п. 1.1)."""
    if not request.user.is_authenticated:
        return redirect('login')
    emp = getattr(request.user, 'employee', None)
    if emp is None:
        if has_role(request.user, EMPLOYEE):
            messages.error(request, 'Учетная запись не связана с карточкой сотрудника.')
        return redirect('dashboard')
    y, m = _month(request)
    days, rows = build_timesheet(y, m, [emp])
    return render(request, 'attendance/my.html', {
        'employee': emp, 'events': emp.events.select_related('point')[:60], 'days': days,
        'row': rows[0], 'month': f'{y}-{m:02d}'})
