from django.core.management.base import BaseCommand

from apps.attendance.models import AccessPoint


class Command(BaseCommand):
    help = 'Регистрирует точку прохода и печатает ключ терминала (показывается один раз)'

    def add_arguments(self, parser):
        parser.add_argument('name')
        parser.add_argument('building')

    def handle(self, *args, **o):
        p = AccessPoint(name=o['name'], building=o['building'])
        token = p.issue_token()
        p.save()
        self.stdout.write(f'Точка «{p}» создана. Адрес терминала: /kiosk/?key={token}')
