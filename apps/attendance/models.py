import hashlib
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.staff.models import Employee


class AccessPoint(models.Model):
    """Точка прохода: служебный вход с камерой и экраном-терминалом."""
    name = models.CharField('Точка прохода', max_length=120)
    building = models.CharField('Здание', max_length=120)
    token_hash = models.CharField('Хеш ключа терминала', max_length=64, unique=True, editable=False)
    is_active = models.BooleanField('Работает', default=True)

    class Meta:
        verbose_name = 'Точка прохода'
        verbose_name_plural = 'Точки прохода'

    def __str__(self):
        return f'{self.name} ({self.building})'

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def issue_token(self) -> str:
        """Новый ключ терминала. Показывается один раз, в базе хранится только хеш."""
        token = secrets.token_urlsafe(24)
        self.token_hash = self.hash_token(token)
        return token

    @classmethod
    def by_token(cls, token: str):
        return cls.objects.filter(token_hash=cls.hash_token(token or ''), is_active=True).first()


class Shift(models.Model):
    name = models.CharField('Смена', max_length=60, unique=True)
    code = models.CharField('Обозначение', max_length=5, unique=True)
    start = models.TimeField('Начало')
    duration_hours = models.DecimalField('Продолжительность, ч', max_digits=4, decimal_places=1)

    class Meta:
        verbose_name = 'Смена'
        verbose_name_plural = 'Смены'
        ordering = ['start']

    def __str__(self):
        return f'{self.name} ({self.start:%H:%M}, {self.duration_hours} ч)'

    def bounds(self, day):
        """Начало и конец смены, которая начинается в день day (ночная смена переходит в следующие сутки)."""
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(day, self.start), tz)
        return start, start + timedelta(hours=float(self.duration_hours))


class ScheduleEntry(models.Model):
    """График работы: какая смена у сотрудника в какой день."""
    employee = models.ForeignKey(Employee, verbose_name='Сотрудник', on_delete=models.CASCADE,
                                 related_name='schedule')
    date = models.DateField('Дата')
    shift = models.ForeignKey(Shift, verbose_name='Смена', on_delete=models.PROTECT)

    class Meta:
        verbose_name = 'Запись графика'
        verbose_name_plural = 'График работы'
        constraints = [models.UniqueConstraint(fields=['employee', 'date'], name='one_shift_per_day')]
        ordering = ['date']

    def __str__(self):
        return f'{self.employee} {self.date:%d.%m} {self.shift.code}'


class AttendanceEvent(models.Model):
    class Direction(models.TextChoices):
        IN = 'in', 'Приход'
        OUT = 'out', 'Уход'

    class Method(models.TextChoices):
        FACE = 'face', 'По лицу'
        FALLBACK = 'fallback', 'Табельный номер и PIN'
        MANUAL = 'manual', 'Вручную (руководитель, отдел кадров)'

    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Подтверждена'
        PENDING = 'pending', 'Ожидает проверки'
        REJECTED = 'rejected', 'Отклонена'

    employee = models.ForeignKey(Employee, verbose_name='Сотрудник', null=True, blank=True,
                                 on_delete=models.PROTECT, related_name='events')
    point = models.ForeignKey(AccessPoint, verbose_name='Точка прохода', null=True, blank=True,
                              on_delete=models.PROTECT)
    timestamp = models.DateTimeField('Время', default=timezone.now, db_index=True)
    direction = models.CharField('Направление', max_length=3, choices=Direction.choices)
    method = models.CharField('Способ', max_length=10, choices=Method.choices)
    status = models.CharField('Статус', max_length=10, choices=Status.choices, default=Status.CONFIRMED,
                              db_index=True)
    score = models.FloatField('Сходство', null=True, blank=True)
    liveness = models.FloatField('Живость', null=True, blank=True)
    reason = models.CharField('Причина проверки / комментарий', max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто внес', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто проверил', null=True,
                                    blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField('Когда проверено', null=True, blank=True)

    class Meta:
        verbose_name = 'Отметка'
        verbose_name_plural = 'Журнал отметок'
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['employee', 'timestamp'])]

    def __str__(self):
        who = self.employee or 'неизвестный'
        return f'{self.timestamp:%d.%m.%Y %H:%M} {who} {self.get_direction_display()}'
