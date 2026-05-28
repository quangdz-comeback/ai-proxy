import logging
from flask import Flask
from config import LOG_LEVEL


def create_app():
    app = Flask(__name__)
    logging.basicConfig(level=LOG_LEVEL, format="%(levelname)s %(message)s")

    from db.database import init_db
    init_db()

    from endpoints.health import health_bp
    app.register_blueprint(health_bp)

    return app
