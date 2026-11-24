from django.contrib import admin

from .models import Department, Employee, FaceTemplate, Position


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'head')


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('name', 'category')
    list_filter = ('category',)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('personnel_number', 'full_name', 'department', 'position', 'consent', 'is_active')
    list_filter = ('department', 'consent', 'is_active')
    search_fields = ('last_name', 'personnel_number')
    exclude = ('fallback_pin',)


@admin.register(FaceTemplate)
class FaceTemplateAdmin(admin.ModelAdmin):
    """Вектор в админке не показывается и не редактируется."""
    list_display = ('employee', 'model_name', 'quality', 'created_at', 'created_by')
    exclude = ('vector',)
    readonly_fields = ('employee', 'model_name', 'quality', 'created_by')

    def has_add_permission(self, request):
        return False
