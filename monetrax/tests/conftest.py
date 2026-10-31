import pytest

from app import create_app
from config import TestConfig
from extensions import db


@pytest.fixture
def app():
    app = create_app(TestConfig)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _register(client, name="Juan Dela Cruz", email="juan@school.edu.ph", password="Budget2026",
              confirm=None, terms="on"):
    data = {"full_name": name, "email": email, "password": password,
            "confirm_password": password if confirm is None else confirm}
    if terms:
        data["terms"] = terms
    return client.post("/register", data=data)


@pytest.fixture
def register(client):
    def _do(**kw):
        return _register(client, **kw)
    return _do


@pytest.fixture
def user_client(client, register):
    register()
    return client


@pytest.fixture
def cat_id(app):
    from sqlalchemy import select
    from models import Category

    def _get(name, user_id=1):
        with app.app_context():
            return db.session.scalar(select(Category.id).where(Category.user_id == user_id, Category.name == name))
    return _get
