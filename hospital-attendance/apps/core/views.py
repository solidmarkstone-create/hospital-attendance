from django.contrib.auth import views as auth_views
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.attendance.models import AttendanceEvent as Ev, ScheduleEntry
from apps.staff.models import Employee

from .models import AuditLog, audit
from .roles import can_configure, can_view_reports, managed_departments, require


class LoginView(auth_views.LoginView):
    template_name = 'core/login.html'

    def form_valid(self, form):
        resp = super().form_valid(form)
        audit(self.request, AuditLog.Action.LOGIN, self.request.user)
        return resp


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if not can_view_reports(request.user):
        return redirect('my_attendance')
    today = timezone.localdate()
    deps = managed_departments(request.user)
    emp_qs = Employee.objects.filter(is_active=True)
    ev_qs = Ev.objects.filter(timestamp__date=today)
    sch_qs = ScheduleEntry.objects.filter(date=today)
    if deps is not None:
        emp_qs = emp_qs.filter(department__in=deps)
        ev_qs = ev_qs.filter(employee__department__in=deps)
        sch_qs = sch_qs.filter(employee__department__in=deps)
    present = set(ev_qs.filter(status=Ev.Status.CONFIRMED, direction=Ev.Direction.IN)
                  .values_list('employee_id', flat=True))
    scheduled = set(sch_qs.values_list('employee_id', flat=True))
    pending = Ev.objects.filter(status=Ev.Status.PENDING)
    if deps is not None:
        pending = pending.filter(employee__department__in=deps)
    stats = {
        'employees': emp_qs.count(),
        'with_template': emp_qs.filter(templates__isnull=False).distinct().count(),
        'no_consent': emp_qs.filter(~Q(consent=Employee.Consent.GIVEN)).count(),
        'scheduled': len(scheduled),
        'present': len(present & scheduled) if scheduled else len(present),
        'absent': len(scheduled - present),
        'pending': pending.count(),
        'face_share': 0,
    }
    total = ev_qs.count()
    if total:
        stats['face_share'] = round(100 * ev_qs.filter(method=Ev.Method.FACE).count() / total)
    return render(request, 'core/dashboard.html', {
        'stats': stats, 'today': today,
        'last_events': ev_qs.select_related('employee', 'point').order_by('-timestamp')[:12]})


@require(can_configure)
def audit_log(request):
    return render(request, 'core/audit.html', {'items': AuditLog.objects.select_related('user')[:300]})
