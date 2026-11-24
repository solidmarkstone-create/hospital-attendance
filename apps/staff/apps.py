from django.apps import AppConfig


class Config(AppConfig):
    verbose_name = 'Персонал'
    name = 'apps.staff'
    label = 'staff'
    default_auto_field = 'django.db.models.BigAutoField'
