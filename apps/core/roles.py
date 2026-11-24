"""Роли пользователей и права доступа (матрица ролей – таблица 2.3 ВКР).

Роль = группа Django. Проверки прав собраны здесь, чтобы представления
не дублировали логику и ее можно было проверить тестами.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

ADMIN = 'Администратор'
HR = 'Отдел кадров'
HEAD = 'Руководитель отделения'
EMPLOYEE = 'Работник'
ALL_ROLES = (ADMIN, HR, HEAD, EMPLOYEE)


def role_names(user) -> set[str]:
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {ADMIN}
    if not hasattr(user, '_role_cache'):
        user._role_cache = set(user.groups.values_list('name', flat=True))
    return user._role_cache


def has_role(user, *roles) -> bool:
    return bool(role_names(user) & set(roles))


def can_manage_staff(user) -> bool:
    """Карточки сотрудников, эталоны, согласия: администратор и отдел кадров."""
    return has_role(user, ADMIN, HR)


def can_manage_biometrics(user) -> bool:
    """Регистрация и удаление эталонов лица: администратор и отдел кадров."""
    return has_role(user, ADMIN, HR)


def can_view_all_departments(user) -> bool:
    return has_role(user, ADMIN, HR)


def can_review(user) -> bool:
    return has_role(user, ADMIN, HR, HEAD)


def can_view_reports(user) -> bool:
    return has_role(user, ADMIN, HR, HEAD)


def can_configure(user) -> bool:
    """Точки прохода, смены, журнал аудита: только администратор."""
    return has_role(user, ADMIN)


def managed_departments(user):
    """Отделения, данные которых видит пользователь (None – все)."""
    from apps.staff.models import Department
    if can_view_all_departments(user):
        return None
    if has_role(user, HEAD):
        return Department.objects.filter(head=user)
    return Department.objects.none()


def require(check):
    """Декоратор представления: 403, если проверка прав не пройдена."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return deco
