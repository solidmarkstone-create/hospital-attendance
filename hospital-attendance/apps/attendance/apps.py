from django.apps import AppConfig


class Config(AppConfig):
    verbose_name = 'Учет посещаемости'
    name = 'apps.attendance'
    label = 'attendance'
    default_auto_field = 'django.db.models.BigAutoField'
