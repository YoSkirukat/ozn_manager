import click
from datetime import date
from flask.cli import with_appcontext

from app.extensions import db
from app.models import Order, ReleaseNote, User
from app.services.order_images import resolve_thumbnail_url


def register_commands(app):
    @app.cli.command("init-db")
    @with_appcontext
    def init_db():
        """Создать таблицы БД (без миграций)."""
        db.create_all()
        click.echo("База данных инициализирована.")

    @app.cli.command("create-admin")
    @click.option("--username", default="admin")
    @click.option("--email", default="admin@example.com")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @with_appcontext
    def create_admin(username, email, password):
        user = User.query.filter_by(username=username).first()
        if user:
            user.role = User.ROLE_ADMIN
            user.is_active = True
            user.display_name = user.display_name or username
            user.set_password(password)
            db.session.commit()
            click.echo(f"Пользователь {username} обновлён до администратора.")
            return
        user = User(
            username=username,
            email=email,
            display_name=username,
            role=User.ROLE_ADMIN,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Администратор {username} создан.")

    @app.cli.command("promote-admin")
    @click.argument("username")
    @with_appcontext
    def promote_admin(username):
        user = User.query.filter_by(username=username).first()
        if not user:
            click.echo("Пользователь не найден.")
            return
        user.role = User.ROLE_ADMIN
        db.session.commit()
        click.echo(f"{username} назначен администратором.")

    @app.cli.command("seed-releases")
    @with_appcontext
    def seed_releases():
        """Начальные записи журнала обновлений (если пусто)."""
        if ReleaseNote.query.first():
            click.echo("Записи уже есть, пропуск.")
            return
        note = ReleaseNote(
            version="1.0.0",
            released_at=date.today(),
            items=[
                "Запуск Ozon Manager: авторизация, дашборд, профиль с подключением Ozon Seller API.",
                "Управление пользователями для администратора.",
                "Журнал обновлений сервиса (release notes).",
                "Разделы: товары, заказы, поставки, отчёты (остатки, возвраты), аналитика.",
                "Регламентные задания и уведомления.",
            ],
        )
        db.session.add(note)
        db.session.commit()
        click.echo("Добавлена версия 1.0.0.")

    @app.cli.command("refresh-order-thumbnails")
    @click.option("--user-id", type=int, default=None, help="ID пользователя (все, если не указан)")
    @with_appcontext
    def refresh_order_thumbnails(user_id):
        """Подставить миниатюры заказов из каталога товаров."""
        query = Order.query
        if user_id:
            query = query.filter_by(user_id=user_id)
        updated = 0
        for order in query.all():
            thumb = resolve_thumbnail_url(order.user_id, order.raw_data)
            if thumb and order.thumbnail_url != thumb:
                order.thumbnail_url = thumb
                updated += 1
        db.session.commit()
        click.echo(f"Обновлено миниатюр: {updated}.")
