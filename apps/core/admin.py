from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'action', 'object_repr', 'ip')
    list_filter = ('action',)

    def has_change_permission(self, request, obj=None):
        return False      # журнал аудита нельзя исправить

    def has_delete_permission(self, request, obj=None):
        return False
