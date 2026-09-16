"""Entry point used by `flask run`, Gunicorn, and the Flask CLI (FLASK_APP)."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
