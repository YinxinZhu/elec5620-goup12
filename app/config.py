import os
from pathlib import Path


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    default_db_path = Path(__file__).resolve().parent.parent / "instance" / "app.db"
    default_db_uri = f"sqlite:///{default_db_path.as_posix()}"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", default_db_uri)
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
