from django.contrib import admin, messages

from .models import AccessPoint, AttendanceEvent, ScheduleEntry, Shift


@admin.register(AccessPoint)
class AccessPointAdmin(admin.ModelAdmin):
    list_display = ('name', 'building', 'is_active')
    actions = ['new_token']

    def save_model(self, request, obj, form, change):
        if not obj.token_hash:
            token = obj.issue_token()
            messages.warning(request, f'Ключ терминала (показывается один раз): {token}')
        super().save_model(request, obj, form, change)

    @admin.action(description='Выдать новый ключ терминала')
    def new_token(self, request, queryset):
        for p in queryset:
            token = p.issue_token()
            p.save()
            messages.warning(request, f'{p}: новый ключ {token}')


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'start', 'duration_hours')


@admin.register(ScheduleEntry)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'shift')
    list_filter = ('shift', 'date')


@admin.register(AttendanceEvent)
class EventAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'employee', 'direction', 'method', 'status', 'score', 'point')
    list_filter = ('status', 'method', 'direction')
    readonly_fields = ('score', 'liveness')
