"""Fixtures Flask : CSRF désactivé pour les requêtes de test."""

import pytest

from app import app as flask_app


@pytest.fixture
def app():
    prev_testing = flask_app.config.get("TESTING")
    prev_csrf = flask_app.config.get("WTF_CSRF_ENABLED")
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    yield flask_app
    flask_app.config["TESTING"] = prev_testing
    flask_app.config["WTF_CSRF_ENABLED"] = prev_csrf


@pytest.fixture
def client(app):
    return app.test_client()
