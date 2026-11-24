# Учет посещаемости персонала больницы с распознаванием лиц

Веб-приложение для контроля прихода и ухода персонала медицинской организации по изображению лица.
Разработано в рамках выпускной квалификационной работы (Финансовый университет, 09.03.03 «Прикладная информатика»)
в интересах ГАУЗ СО «Арамильская городская больница».

## Что умеет

- терминал у служебного входа: браузер с веб-камерой, отметка одним нажатием, ответ меньше чем за 1 с на сервере без видеокарты;
- поиск лица (SCRFD или RetinaFace), проверка «живости» (MiniFASNetV2), вектор ArcFace, сравнение с эталонами;
- серая зона сходства и запасная отметка по табельному номеру и PIN – на подтверждение руководителю;
- табель за месяц по графику смен (включая ночные смены и суточные дежурства), отчет об опозданиях, выгрузка CSV;
- четыре роли (администратор, отдел кадров, руководитель отделения, работник), журнал аудита;
- учет письменного согласия на биометрию: без согласия эталон не создается, при отзыве удаляется;
- фотографии не хранятся; в базе только векторы, зашифрованные Fernet (ключ вне базы).

## Структура

```
recognition/        модуль распознавания (без Django): detectors, align, liveness, embedder, matcher, engine, crypto
apps/staff/         подразделения, должности, сотрудники, согласия, эталоны
apps/attendance/    точки прохода, смены, график, отметки, табель, API терминала
apps/core/          роли, журнал аудита, сводка, вход
templates/, static/ интерфейс (Django templates + Bootstrap 5.3), программа терминала static/js/kiosk.js
tests/              модульные и интеграционные тесты (pytest)
eval/               испытания на LFW и CelebA-Spoof, замеры скорости; результаты в eval/results
deploy/             Dockerfile, docker-compose (PostgreSQL + приложение + nginx с TLS), служба systemd
docs/adr/           записи архитектурных решений (ADR)
```

## Быстрый показ в GitHub Codespaces

На странице репозитория: Code, вкладка Codespaces, Create codespace on main. Первый запуск 5–10 минут
(ставятся библиотеки и скачиваются нейросети), дальше программа стартует сама (`deploy/demo_start.sh`):
база SQLite с тестовыми данными, порт 8000. Ссылку на программу показывает вкладка Ports; чтобы ее открыли
другие, у порта 8000 поставить Port Visibility: Public. Пароль входов и ключ терминала можно задать
переменными DEMO_PASSWORD и KIOSK_KEY (по умолчанию Demo-2026-pass и demo-terminal).

## Установка (Ubuntu 24.04, Python 3.12, PostgreSQL 16)

```sh
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
./scripts/download_models.sh models          # модели в папку models
cp .env.example .env                           # заполнить пароли и ключи
python manage.py migrate
python manage.py init_roles
python manage.py createsuperuser
python manage.py create_point "Служебный вход стационара" "ул. Садовая, 10"   # печатает адрес терминала с ключом
gunicorn config.wsgi -b 127.0.0.1:8000
```

Терминал открывается по адресу `/kiosk/?key=...`; браузер дает доступ к камере только по HTTPS, поэтому в больнице
приложение работает за nginx (deploy/nginx.conf). Вариант в контейнерах: `docker compose -f deploy/docker-compose.yml up -d`.

Тестовые данные (вымышленные сотрудники и отметки): `python manage.py load_demo`.

## Логины и пароли (тестовые данные `load_demo`)

| Учетная запись | Роль | Пароль | Что видит |
|---|---|---|---|
| admin | Администратор (и панель /admin/) | Demo-2026-pass | все разделы, настройки, журнал аудита |
| kadry | Отдел кадров | Demo-2026-pass | все отделения, карточки, согласия, эталоны, табель |
| zav_hir | Руководитель хирургического отделения | Demo-2026-pass | свое отделение, проверка отметок, табель |
| rabotnik | Работник (медсестра хирургии) | Demo-2026-pass | только свои отметки |

- PIN запасной отметки у тестовых сотрудников без согласия на биометрию: 2468 (табельный номер – в списке сотрудников).
- Ключ терминала печатает команда `load_demo` (строка «Терминал стационара: /kiosk/?key=…») или `create_point`; при каждом запуске `load_demo` ключ новый.
- База данных PostgreSQL: база attendance, пользователь attendance, пароль задается в .env (POSTGRES_PASSWORD), готовый вариант для учебного стенда: att_local_2026.
- Ключ шифрования биометрии BIOMETRIC_KEY создается командой из .env.example; если его потерять, эталоны придется зарегистрировать заново.

## Тесты и испытания

```sh
pip install -r requirements-dev.txt
pytest -m "not models" --cov=apps --cov=recognition      # модульные тесты, без нейросетей
FACE_MODELS_DIR=models LFW_DIR=/путь/к/lfw pytest -m models   # с настоящими моделями
python -m eval.lfw_experiments --lfw /путь/к/lfw --pairs pairs.txt --models models
python -m eval.speed --models models --lfw /путь/к/lfw
python -m eval.detect_masks --models models --lfw /путь/к/lfw
python -m eval.liveness_eval --parquet valid-00000-of-00009.parquet --models models
```

## Лицензии

Код – MIT. Модели в репозиторий не входят: InsightFace buffalo_l/buffalo_s – только некоммерческое
использование (при внедрении нужна замена модели или коммерческая лицензия), RetinaFace (yakhyo/retinaface-pytorch) – MIT,
MiniFASNet (minivision-ai/Silent-Face-Anti-Spoofing) – Apache-2.0.
