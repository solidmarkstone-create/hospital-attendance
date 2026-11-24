import json

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.attendance import engine_service
from apps.core.imaging import decode_bytes, decode_data_url
from apps.core.models import AuditLog, audit
from apps.core.roles import HEAD, can_manage_biometrics, can_manage_staff, has_role, managed_departments, require
from recognition.engine import EnrollmentError

from .forms import ConsentForm, EmployeeForm, EnrollForm, PinForm
from .models import Department, Employee, FaceTemplate


@require(lambda u: can_manage_staff(u) or has_role(u, HEAD))
def employee_list(request):
    qs = Employee.objects.select_related('department', 'position').annotate(n_templates=Count('templates'))
    deps = managed_departments(request.user)
    if deps is not None:
        qs = qs.filter(department__in=deps)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(last_name__icontains=q) | Q(personnel_number__icontains=q))
    dep = request.GET.get('dep')
    if dep:
        qs = qs.filter(department_id=dep)
    return render(request, 'staff/employee_list.html', {
        'employees': qs, 'q': q, 'dep': dep, 'departments': Department.objects.all(),
        'can_edit': can_manage_staff(request.user)})


@require(can_manage_staff)
def employee_edit(request, pk=None):
    emp = get_object_or_404(Employee, pk=pk) if pk else None
    form = EmployeeForm(request.POST or None, instance=emp)
    if request.method == 'POST' and form.is_valid():
        emp = form.save()
        audit(request, AuditLog.Action.EMPLOYEE_EDIT, emp)
        messages.success(request, 'Карточка сотрудника сохранена.')
        return redirect('employee_detail', pk=emp.pk)
    return render(request, 'staff/employee_form.html', {'form': form, 'employee': emp})


@require(can_manage_staff)
def employee_detail(request, pk):
    emp = get_object_or_404(Employee.objects.select_related('department', 'position'), pk=pk)
    consent_form = ConsentForm(instance=emp)
    if request.method == 'POST' and 'consent' in request.POST:
        consent_form = ConsentForm(request.POST, instance=emp)
        if consent_form.is_valid():
            emp = consent_form.save()
            removed = 0
            if emp.consent != Employee.Consent.GIVEN:
                # отказ или отзыв согласия: эталоны удаляются сразу (ч. 2 ст. 9 Закона № 152-ФЗ)
                removed = emp.templates.count()
                emp.templates.all().delete()
            audit(request, AuditLog.Action.CONSENT, emp, f'{emp.get_consent_display()}, удалено эталонов: {removed}')
            messages.success(request, 'Сведения о согласии сохранены.')
            return redirect('employee_detail', pk=emp.pk)
    return render(request, 'staff/employee_detail.html', {
        'employee': emp, 'consent_form': consent_form, 'pin_form': PinForm(),
        'templates': emp.templates.all(), 'events': emp.events.select_related('point')[:20]})


@require(can_manage_biometrics)
def enroll(request, pk):
    """Регистрация эталона: снимки читаются в память, считается вектор, снимки отбрасываются."""
    emp = get_object_or_404(Employee, pk=pk)
    if not emp.biometrics_allowed:
        messages.error(request, 'Нет действующего письменного согласия на обработку биометрии.')
        return redirect('employee_detail', pk=pk)
    posted = request.method == 'POST'
    form = EnrollForm(request.POST if posted else None, request.FILES if posted else None)
    if posted and form.is_valid():
        try:
            imgs = [decode_bytes(f.read()) for f in request.FILES.getlist('photos')[:5]]
            raw = form.cleaned_data.get('camera_frames')
            if raw:
                imgs += [decode_data_url(s) for s in json.loads(raw)[:5]]
            if not imgs:
                raise EnrollmentError('добавьте хотя бы одну фотографию или снимок с камеры')
            engine = engine_service.get_engine()
            vector, quality = engine.enroll(imgs)
        except (EnrollmentError, ValueError) as exc:
            messages.error(request, f'Эталон не создан: {exc}.')
        else:
            del imgs
            FaceTemplate.objects.create(employee=emp, model_name=engine_service.model_name(),
                                        vector=engine_service.cipher().encrypt(vector), quality=quality,
                                        created_by=request.user)
            audit(request, AuditLog.Action.ENROLL, emp, f'качество {quality:.2f}')
            messages.success(request, f'Эталон создан (качество снимков {quality:.2f}). Фотографии не сохранены.')
            return redirect('employee_detail', pk=pk)
    return render(request, 'staff/enroll.html', {'employee': emp, 'form': form})


@require(can_manage_biometrics)
@require_POST
def template_delete(request, pk, tpk):
    t = get_object_or_404(FaceTemplate, pk=tpk, employee_id=pk)
    t.delete()
    audit(request, AuditLog.Action.TEMPLATE_DELETE, t.employee)
    messages.success(request, 'Эталон удален.')
    return redirect('employee_detail', pk=pk)


@require(can_manage_staff)
@require_POST
def set_pin(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    form = PinForm(request.POST)
    if form.is_valid():
        emp.set_pin(form.cleaned_data['pin'])
        emp.save(update_fields=['fallback_pin'])
        audit(request, AuditLog.Action.EMPLOYEE_EDIT, emp, 'назначен PIN запасной отметки')
        messages.success(request, f'PIN запасной отметки назначен {timezone.localtime():%d.%m.%Y %H:%M}.')
    else:
        messages.error(request, 'PIN должен состоять из 4–6 цифр.')
    return redirect('employee_detail', pk=pk)
