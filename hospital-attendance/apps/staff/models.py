from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class Department(models.Model):
    name = models.CharField('Подразделение', max_length=150, unique=True)
    code = models.CharField('Код', max_length=20, unique=True)
    head = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Руководитель', null=True, blank=True,
                             on_delete=models.SET_NULL, related_name='headed_departments')

    class Meta:
        verbose_name = 'Подразделение'
        verbose_name_plural = 'Подразделения'
        ordering = ['name']

    def __str__(self):
        return self.name


class Position(models.Model):
    class Category(models.TextChoices):
        DOCTOR = 'doctor', 'Врачи'
        NURSE = 'nurse', 'Средний медицинский персонал'
        OTHER = 'other', 'Прочий персонал'
        ADMIN = 'admin', 'Административно-управленческий персонал'

    name = models.CharField('Должность', max_length=150, unique=True)
    category = models.CharField('Категория персонала', max_length=10, choices=Category.choices)

    class Meta:
        verbose_name = 'Должность'
        verbose_name_plural = 'Должности'
        ordering = ['name']

    def __str__(self):
        return self.name


class Employee(models.Model):
    class Consent(models.TextChoices):
        NONE = 'none', 'Не оформлено'
        GIVEN = 'given', 'Дано'
        REFUSED = 'refused', 'Отказ от биометрии'
        WITHDRAWN = 'withdrawn', 'Отозвано'

    personnel_number = models.CharField('Табельный номер', max_length=20, unique=True)
    last_name = models.CharField('Фамилия', max_length=60)
    first_name = models.CharField('Имя', max_length=60)
    middle_name = models.CharField('Отчество', max_length=60, blank=True)
    department = models.ForeignKey(Department, verbose_name='Подразделение', on_delete=models.PROTECT,
                                   related_name='employees')
    position = models.ForeignKey(Position, verbose_name='Должность', on_delete=models.PROTECT)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name='Учетная запись', null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='employee')
    is_active = models.BooleanField('Работает', default=True)
    consent = models.CharField('Согласие на обработку биометрии', max_length=10, choices=Consent.choices,
                               default=Consent.NONE)
    consent_date = models.DateField('Дата согласия (отзыва)', null=True, blank=True)
    consent_doc = models.CharField('Реквизиты документа', max_length=100, blank=True)
    fallback_pin = models.CharField('PIN запасной отметки (хеш)', max_length=128, blank=True)

    class Meta:
        verbose_name = 'Сотрудник'
        verbose_name_plural = 'Сотрудники'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return self.short_name

    @property
    def full_name(self):
        return ' '.join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def short_name(self):
        ini = ''.join(f'{p[0]}.' for p in (self.first_name, self.middle_name) if p)
        return f'{self.last_name} {ini}'.strip()

    @property
    def biometrics_allowed(self):
        return self.consent == self.Consent.GIVEN and self.is_active

    def set_pin(self, raw):
        self.fallback_pin = make_password(raw)

    def check_pin(self, raw):
        return bool(self.fallback_pin) and check_password(raw, self.fallback_pin)


class FaceTemplate(models.Model):
    """Эталон лица. Хранится только зашифрованный вектор; фотография не сохраняется."""
    employee = models.ForeignKey(Employee, verbose_name='Сотрудник', on_delete=models.CASCADE,
                                 related_name='templates')
    model_name = models.CharField('Модель распознавания', max_length=60)
    vector = models.BinaryField('Вектор (зашифрован)')
    quality = models.FloatField('Качество снимков', default=0)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто зарегистрировал', null=True,
                                   blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = 'Эталон лица'
        verbose_name_plural = 'Эталоны лиц'

    def __str__(self):
        return f'Эталон {self.employee} ({self.model_name})'
