# Ozon Manager

Веб-сервис для работы с API Ozon: авторизация, магазины, товары, заказы, поставки, отчёты, аналитика и журнал изменений.

## Стек

- **Backend:** Python, Flask, SQLAlchemy, Flask-Migrate, Flask-Login, Gunicorn
- **Frontend:** Bootstrap 5, ES6 (fetch), SPA-подобная навигация
- **БД:** SQLite (по умолчанию) или PostgreSQL через `DATABASE_URL`

## Структура проекта

```
ozn_manager/
├── app/
│   ├── __init__.py          # фабрика приложения
│   ├── config.py            # конфигурация (.env)
│   ├── extensions.py        # db, migrate, login_manager
│   ├── models.py            # модели SQLAlchemy
│   ├── cli.py               # flask init-db, create-admin
│   ├── routes/              # страницы и blueprints (далее)
│   │   └── api/             # REST /api/*
│   ├── services/
│   │   └── change_log.py    # аудит изменений
│   └── ozon/                # клиент Ozon API (далее)
├── templates/
│   ├── base.html            # header + footer + main
│   └── index.html           # дашборд (заглушка)
├── static/
│   ├── css/main.css
│   └── js/app.js            # AJAX-навигация
├── instance/                # SQLite (создаётся автоматически)
├── reports/                 # сгенерированные отчёты
├── migrations/              # flask db migrate
├── requirements.txt
├── .env.example
├── wsgi.py                  # Gunicorn: gunicorn wsgi:app
└── run.py                   # dev: python run.py
```

## Установка и запуск

```bash
cd /home/yos/www/ozn_manager
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# отредактируйте SECRET_KEY и при необходимости OZON_* в .env

export FLASK_APP=wsgi:app
flask db init          # один раз
flask db migrate -m "initial"
flask db upgrade
flask create-admin     # или flask init-db для create_all без миграций

# разработка
python run.py

# production (планировщик — в одном процессе; при -w > 1 нужен SCHEDULER_FILE_LOCK=1 в .env)
gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
```

## Что уже сделано (этап 1)

- Структура каталогов и зависимости
- Модели: `User`, `Product`, `Order`, `Shipment`, `Report`, `Analytics`, `ChangeLog`
- Сервис `log_change()` для аудита с автоинкрементом `version`
- Шаблон `base.html` (Bootstrap 5, навигация, тосты, лоадер)
- Заготовка SPA-навигации в `static/js/app.js`

## Следующие этапы

1. Авторизация (login/register)
2. Blueprints страниц и REST API
3. Интеграция Ozon API
4. Модули: товары, заказы, поставки, отчёты, аналитика, журнал с откатом
# ozn_manager
