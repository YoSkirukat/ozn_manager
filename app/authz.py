from functools import wraps

from flask import abort
from flask_login import current_user

ROLE_ADMIN = "admin"
ROLE_USER = "user"


def is_admin(user=None) -> bool:
    u = user or current_user
    return (
        getattr(u, "is_authenticated", False)
        and bool(getattr(u, "is_active", False))
        and getattr(u, "role", None) == ROLE_ADMIN
    )


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not is_admin():
            abort(403)
        return f(*args, **kwargs)

    return wrapped
