from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Журнал действий с персональными и биометрическими данными (п. 1.3, приказ ФСТЭК № 21)."""

    class Action(models.TextChoices):
        LOGIN = 'login', 'Вход в систему'
        ENROLL = 'enroll', 'Регистрация эталона лица'
        TEMPLATE_DELETE = 'template_delete', 'Удаление эталона лица'
        CONSENT = 'consent', 'Изменение согласия на биометрию'
        EMPLOYEE_EDIT = 'employee_edit', 'Изменение карточки сотрудника'
        REVIEW = 'review', 'Решение по спорной отметке'
        MANUAL_MARK = 'manual_mark', 'Ручная отметка'
        EXPORT = 'export', 'Выгрузка табеля'
        SETTINGS = 'settings', 'Изменение настроек'

    created_at = models.DateTimeField('Время', auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь', null=True, blank=True,
                             on_delete=models.SET_NULL)
    action = models.CharField('Действие', max_length=32, choices=Action.choices)
    object_repr = models.CharField('Объект', max_length=255, blank=True)
    details = models.TextField('Подробности', blank=True)
    ip = models.GenericIPAddressField('IP-адрес', null=True, blank=True)

    class Meta:
        verbose_name = 'Запись журнала аудита'
        verbose_name_plural = 'Журнал аудита'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.created_at:%d.%m.%Y %H:%M} {self.get_action_display()}'


def audit(request, action, obj='', details=''):
    user = request.user if request and request.user.is_authenticated else None
    ip = request.META.get('REMOTE_ADDR') if request else None
    return AuditLog.objects.create(user=user, action=action, object_repr=str(obj)[:255], details=details, ip=ip)
