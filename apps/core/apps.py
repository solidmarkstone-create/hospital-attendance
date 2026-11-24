from django.apps import AppConfig


class Config(AppConfig):
    verbose_name = 'Общее'
    name = 'apps.core'
    label = 'core'
    default_auto_field = 'django.db.models.BigAutoField'
