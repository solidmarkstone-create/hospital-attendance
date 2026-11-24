from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from apps.attendance import views as att
from apps.core import views as core
from apps.staff import views as staff

urlpatterns = [
    path('', core.dashboard, name='dashboard'),
    path('login/', core.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('audit/', core.audit_log, name='audit_log'),

    path('staff/', staff.employee_list, name='employee_list'),
    path('staff/new/', staff.employee_edit, name='employee_new'),
    path('staff/<int:pk>/', staff.employee_detail, name='employee_detail'),
    path('staff/<int:pk>/edit/', staff.employee_edit, name='employee_edit'),
    path('staff/<int:pk>/enroll/', staff.enroll, name='enroll'),
    path('staff/<int:pk>/pin/', staff.set_pin, name='set_pin'),
    path('staff/<int:pk>/templates/<int:tpk>/delete/', staff.template_delete, name='template_delete'),

    path('journal/', att.journal, name='journal'),
    path('review/', att.review_queue, name='review_queue'),
    path('review/<int:pk>/', att.review_decide, name='review_decide'),
    path('manual/', att.manual_mark, name='manual_mark'),
    path('timesheet/', att.timesheet, name='timesheet'),
    path('lateness/', att.lateness, name='lateness'),
    path('my/', att.my_attendance, name='my_attendance'),

    path('kiosk/', att.kiosk, name='kiosk'),
    path('api/kiosk/recognize/', att.kiosk_recognize, name='kiosk_recognize'),
    path('api/kiosk/fallback/', att.kiosk_fallback, name='kiosk_fallback'),

    path('admin/', admin.site.urls),
]

admin.site.site_header = 'Учет посещаемости персонала – администрирование'
