#!/bin/sh
# Демо-запуск (GitHub Codespaces, ноутбук, Hugging Face): база SQLite создается заново с тестовыми данными.
set -e
cd "$(dirname "$0")/.."
export DJANGO_HTTPS=${DJANGO_HTTPS:-1} DJANGO_DEBUG=0
export DJANGO_ALLOWED_HOSTS=${DJANGO_ALLOWED_HOSTS:-.app.github.dev,.hf.space,localhost,127.0.0.1}
export DJANGO_CSRF_TRUSTED=${DJANGO_CSRF_TRUSTED:-https://*.app.github.dev,https://*.hf.space}
[ -n "$DJANGO_SECRET_KEY" ] || export DJANGO_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))")
[ -n "$BIOMETRIC_KEY" ] || export BIOMETRIC_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
rm -f db.sqlite3
python manage.py collectstatic --noinput > /dev/null
python manage.py migrate --noinput > /dev/null
python manage.py load_demo --password "${DEMO_PASSWORD:-Demo-2026-pass}" | grep -v "Терминал"
python manage.py shell -c "
import os
from apps.attendance.models import AccessPoint as A
p = A.objects.get(name='Служебный вход стационара')
p.token_hash = A.hash_token(os.environ.get('KIOSK_KEY') or 'demo-terminal')
p.save()"
echo "Программа запущена. Терминал: /kiosk/?key=${KIOSK_KEY:-demo-terminal}"
exec gunicorn config.wsgi -b 0.0.0.0:${PORT:-8000} -w 1 --threads 4 --timeout 120
