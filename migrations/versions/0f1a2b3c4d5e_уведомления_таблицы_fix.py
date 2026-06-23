"""Уведомления: create notification tables (safety fix)

Этот миграционный файл создаёт таблицы уведомлений на случай,
если предыдущая миграция не применилась на текущей БД.
"""

from alembic import op
import sqlalchemy as sa


revision = "0f1a2b3c4d5e"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS notification_settings (
                id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                event_slug VARCHAR(64) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_notification_user_slug UNIQUE (user_id, event_slug),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
    )
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                event_slug VARCHAR(64) NOT NULL,
                title VARCHAR(256) NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                target_url VARCHAR(512) NOT NULL DEFAULT '/',
                entity_type VARCHAR(64) NOT NULL DEFAULT '',
                entity_id INTEGER NOT NULL DEFAULT 0,
                payload JSON,
                created_at DATETIME NOT NULL,
                read_at DATETIME,
                PRIMARY KEY (id),
                CONSTRAINT uq_notification_entity UNIQUE (user_id, event_slug, entity_type, entity_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
    )

    # Индексы (если отсутствуют — создадим)
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notification_settings_event_slug ON notification_settings (event_slug);"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notification_settings_user_id ON notification_settings (user_id);"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at);"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notifications_event_slug ON notifications (event_slug);"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notifications_read_at ON notifications (read_at);"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id);"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created ON notifications (user_id, read_at, created_at);"
        )
    )


def downgrade():
    # Обычно даунгрейд не нужен; оставляем безопасным.
    bind = op.get_bind()
    bind.execute(sa.text("DROP TABLE IF EXISTS notifications;"))
    bind.execute(sa.text("DROP TABLE IF EXISTS notification_settings;"))

