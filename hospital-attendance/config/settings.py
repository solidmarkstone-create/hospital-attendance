"""Настройки веб-приложения учета посещаемости персонала больницы.

Все секреты и параметры площадки задаются переменными окружения (файл .env),
в репозитории их нет. Пример – .env.example.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).lower() in ('1', 'true', 'yes', 'on')


# файл .env рядом с manage.py (простые строки КЛЮЧ=значение)
_env_file = BASE_DIR / '.env'
if _env_file.exists():
    for line in _env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

SECRET_KEY = env('DJANGO_SECRET_KEY', 'dev-only-insecure-key-change-me')
DEBUG = env_bool('DJANGO_DEBUG', False)
ALLOWED_HOSTS = [h for h in env('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h]
CSRF_TRUSTED_ORIGINS = [o for o in env('DJANGO_CSRF_TRUSTED', '').split(',') if o]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.core',
    'apps.staff',
    'apps.attendance',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'apps.core.context.roles_ctx',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'

# PostgreSQL в рабочей среде; SQLite – только для быстрых тестов разработчика
if env('POSTGRES_DB'):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('POSTGRES_DB'),
        'USER': env('POSTGRES_USER', 'attendance'),
        'PASSWORD': env('POSTGRES_PASSWORD', ''),
        'HOST': env('POSTGRES_HOST', '127.0.0.1'),
        'PORT': env('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = env('TIME_ZONE', 'Asia/Yekaterinburg')   # Свердловская область
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
SESSION_COOKIE_AGE = 8 * 3600            # рабочая смена администратора
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
if env_bool('DJANGO_HTTPS', False):       # за обратным прокси nginx с TLS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000

DATA_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024   # до 5 кадров JPEG с терминала

# ---------- биометрия и распознавание
BIOMETRIC_KEY = env('BIOMETRIC_KEY', '')            # ключ Fernet для шифрования эталонов
FACE = {
    'MODELS_DIR': env('FACE_MODELS_DIR', str(BASE_DIR / 'models')),
    'DETECTOR': env('FACE_DETECTOR', 'scrfd'),
    'DETECTOR_FILE': env('FACE_DETECTOR_FILE', 'buffalo_l/det_10g.onnx'),
    'RECOGNIZER_FILE': env('FACE_RECOGNIZER_FILE', 'buffalo_l/w600k_r50.onnx'),
    'LIVENESS_FILE': env('FACE_LIVENESS_FILE', 'onnx/minifasnet_v2.onnx'),
    'USE_LIVENESS': env_bool('FACE_USE_LIVENESS', True),
    'DET_SIZE': int(env('FACE_DET_SIZE', '640')),
    'THREADS': int(env('FACE_THREADS', '2')),
    'ACCEPT': float(env('FACE_ACCEPT', '0.40')),
    'REVIEW': float(env('FACE_REVIEW', '0.25')),
    'MARGIN': float(env('FACE_MARGIN', '0.05')),
    'LIVENESS': float(env('FACE_LIVENESS', '0.60')),
}

# ---------- правила учета
ATTENDANCE = {
    'REPEAT_SECONDS': 120,        # повторная отметка в течение 2 минут не создает событие
    'OPEN_SHIFT_HOURS': 26,       # вход без выхода дольше 26 ч не закрывается автоматически (сутки + запас)
    'LATE_TOLERANCE_MIN': 5,      # опоздание считается после 5 минут от начала смены
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', 'INFO')},
}
