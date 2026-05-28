import logging
from flask import Flask, jsonify
from config import LOG_LEVEL
from upstream.errors import UpstreamError


def create_app():
    app = Flask(__name__)
    logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))

    # Initialize database
    from db.database import init_db, close_db
    init_db()
    app.teardown_appcontext(close_db)

    # Register blueprints
    from endpoints.health import health_bp
    app.register_blueprint(health_bp)

    from endpoints.models import models_bp
    app.register_blueprint(models_bp)

    from endpoints.chat import chat_bp
    app.register_blueprint(chat_bp)

    from endpoints.responses import responses_bp
    app.register_blueprint(responses_bp)

    from endpoints.admin import admin_bp
    app.register_blueprint(admin_bp)

    from endpoints.usage import usage_bp
    app.register_blueprint(usage_bp)

    # Auth middleware
    from auth.middleware import init_auth
    init_auth(app)

    # Global error handlers
    @app.errorhandler(UpstreamError)
    def handle_upstream_error(e):
        return jsonify({"error": {"type": "upstream_error", "message": e.message}}), e.status_code

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({"error": {"type": "not_found", "message": "Endpoint not found"}}), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        logging.exception("Unhandled exception")
        return jsonify({"error": {"type": "server_error", "message": str(e)}}), 500

    return app
