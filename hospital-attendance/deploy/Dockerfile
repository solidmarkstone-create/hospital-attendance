FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ libgl1 libglib2.0-0 curl unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput
RUN useradd -r app && chown -R app /app
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "-b", "0.0.0.0:8000", "-w", "1", "--threads", "4", "--timeout", "60"]
