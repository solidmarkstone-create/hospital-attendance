from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.roles import ALL_ROLES


class Command(BaseCommand):
    help = 'Создает группы ролей: Администратор, Отдел кадров, Руководитель отделения, Работник'

    def handle(self, *args, **opts):
        for name in ALL_ROLES:
            _, created = Group.objects.get_or_create(name=name)
            self.stdout.write(f'{name}: {"создана" if created else "уже есть"}')
