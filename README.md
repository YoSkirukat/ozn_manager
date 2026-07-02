# Ozon Manager

Веб-сервис для продавцов Ozon: заказы, товары, поставки, остатки, возвраты, аналитика, уведомления и регламентные задания. Подключение к [Ozon Seller API](https://seller.ozon.ru/app/settings/api-keys) через профиль пользователя.

## Стек

- **Backend:** Python, Flask, SQLAlchemy, Flask-Migrate, Flask-Login, APScheduler, Gunicorn
- **Frontend:** Bootstrap 5, ES6 (fetch), SPA-подобная навигация без перезагрузки страницы
- **БД:** SQLite (по умолчанию) или PostgreSQL через `DATABASE_URL`
- **Экспорт:** openpyxl, xlrd, xlwt

## Возможности

### Авторизация и пользователи

- Регистрация, вход, профиль с подключением Ozon API (Client ID и API Key)
- Роли `admin` / `user`; новые аккаунты требуют активации администратором
- Админ-панель: управление пользователями, журнал обновлений сервиса (release notes)

### Разделы интерфейса

| Раздел | Путь | Описание |
|--------|------|----------|
| Главная | `/` | Дашборд: сводка, график заказов |
| Товары | `/products` | Каталог, цены, остатки FBO/FBS, акции, закупочные цены |
| Заказы | `/orders` | FBS/FBO за период, фильтры, маржа, экспорт в Excel |
| Поставки | `/shipments` | Заявки FBO, статусы, детали |
| Остатки | `/reports/stock` | Остатки по складам FBO |
| Возвраты | `/reports/returns` | Возвраты FBO/FBS/realFBS за период |
| Планирование поставки | `/analytics/supply-planning` | Прогноз и рекомендации по складам |
| Товары в акциях | `/analytics/promotions` | Участие товаров в акциях Ozon |
| Склады и слоты | `/analytics/warehouse-slots` | Кластеры, мониторинг доступности складов |
| Журнал изменений | `/changelog` | История версий сервиса |

### Регламентные задания

Встроенный планировщик (APScheduler) без cron. Задания настраиваются в интерфейсе по пользователю:

- Синхронизация заказов (30 дней)
- Синхронизация поставок (21 день)
- Отчёт по остаткам
- Синхронизация товаров, акций и закупочных цен
- Проверка возвратов (30 дней)

### Уведомления

- Новый заказ, новая поставка, смена статуса поставки
- Доступность отслеживаемого склада для FBO-поставки

## Структура проекта

```
ozn_manager/
├── app/
│   ├── __init__.py              # фабрика приложения
│   ├── config.py                # конфигурация из .env
│   ├── extensions.py            # db, migrate, login_manager
│   ├── models.py                # модели SQLAlchemy
│   ├── cli.py                   # flask-команды
│   ├── authz.py                 # проверка ролей
│   ├── routes/
│   │   ├── auth.py              # login / register
│   │   ├── main.py              # страницы
│   │   ├── admin.py             # /admin/*
│   │   ├── profile.py           # профиль и Ozon API
│   │   └── api/                 # REST /api/*
│   ├── services/                # бизнес-логика
│   ├── ozon/                    # клиент Ozon Seller API
│   ├── scheduled_tasks/         # планировщик и задания
│   └── notifications/           # проверка и доставка уведомлений
├── templates/                   # Jinja2-шаблоны
├── static/
│   ├── css/main.css
│   └── js/                      # модули по разделам + app.js
├── migrations/                  # Alembic / flask db migrate
├── instance/                    # SQLite (создаётся автоматически)
├── reports/                     # сгенерированные отчёты
├── requirements.txt
├── .env.example
├── wsgi.py                      # Gunicorn: gunicorn wsgi:app
└── run.py                       # dev: python run.py
```

## Установка и запуск

```bash
cd ozn_manager
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# отредактируйте SECRET_KEY; OZON_* можно задать глобально или в профиле каждого пользователя

export FLASK_APP=wsgi:app
flask db upgrade
flask create-admin
flask seed-releases   # опционально: начальная запись в журнале обновлений

# разработка (порт 5000)
python run.py

# production
# при gunicorn -w > 1 обязательно SCHEDULER_FILE_LOCK=1 в .env
gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
```

Для новой БД без существующих миграций: `flask db init`, затем `flask db migrate` и `flask db upgrade`.

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `FLASK_APP` | Точка входа: `wsgi:app` |
| `SECRET_KEY` | Секрет сессий Flask |
| `DATABASE_URL` | SQLite или PostgreSQL (`sqlite:///instance/ozn_manager.db` по умолчанию) |
| `OZON_CLIENT_ID`, `OZON_API_KEY` | Глобальные ключи Ozon (опционально; обычно задаются в профиле) |
| `SCHEDULER_ENABLED` | `1` — включить планировщик (по умолчанию) |
| `SCHEDULER_FILE_LOCK` | `1` — один планировщик на БД при нескольких воркерах Gunicorn |
| `SCHEDULER_TIMEZONE` | Часовой пояс планировщика (`Europe/Moscow`) |
| `APP_TIMEZONE` | Часовой пояс отображения дат в интерфейсе |
| `SCHEDULER_SYNC_SECONDS` | Как часто планировщик перечитывает задания из БД |
| `FLASK_USE_RELOADER` | `0` — один процесс при `python run.py` (надёжнее для планировщика) |
| `FLASK_ENV` | `development` / `production` |

Полный список — в [.env.example](.env.example).

## CLI-команды

```bash
flask init-db                  # создать таблицы без миграций
flask create-admin             # создать или повысить администратора
flask promote-admin USERNAME   # назначить роль admin
flask seed-releases            # начальная версия в журнале обновлений
flask refresh-order-thumbnails # обновить миниатюры заказов из каталога
```

## REST API

Префикс `/api`. Основные группы:

- `/api/dashboard` — данные дашборда и графика
- `/api/products` — синхронизация и действия с товарами
- `/api/orders` — синхронизация, экспорт, детали
- `/api/shipments` — поставки
- `/api/stocks` — остатки
- `/api/supply-planning` — планирование поставки
- `/api/promotions` — акции
- `/api/warehouse-slots` — склады и мониторинг слотов
- `/api/scheduled-tasks` — регламентные задания
- `/api/notifications` — уведомления и настройки

Все эндпоинты требуют авторизации (Flask-Login).
