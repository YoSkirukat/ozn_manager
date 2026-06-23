"""Локальный запуск для разработки: python run.py"""

import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.cli import register_commands

app = create_app()
register_commands(app)

if __name__ == "__main__":
    # FLASK_USE_RELOADER=0 — один процесс, планировщик всегда в том же процессе, что и HTTP
    use_reloader = os.environ.get("FLASK_USE_RELOADER", "1") == "1"
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=use_reloader)
