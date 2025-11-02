import os
from pathlib import Path

from sqlalchemy.engine import URL


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    default_db_path = Path(__file__).resolve().parent.parent / "instance" / "app.db"
    default_db_uri = URL.create(
        drivername="sqlite",
        database=str(default_db_path),
    )
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", str(default_db_uri))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    VARIANT_PROXY_ENABLED = os.environ.get("VARIANT_PROXY_ENABLED", "1").lower() not in {
        "0",
        "false",
        "no",
    }
    VARIANT_PROXY_BASE_URL = os.environ.get(
        "VARIANT_PROXY_BASE_URL",
        os.environ.get("VARIANT_PROXY_URL", "http://47.74.8.132:18899"), # http://localhost:18899
    )
    VARIANT_PROXY_TOKEN = os.environ.get("VARIANT_PROXY_TOKEN", "9786534210")
    VARIANT_PROXY_TIMEOUT = int(os.environ.get("VARIANT_PROXY_TIMEOUT", "120"))
    VARIANT_PROXY_FAST_URL = os.environ.get("VARIANT_PROXY_FAST_URL", VARIANT_PROXY_BASE_URL)
    VARIANT_PROXY_COMPLEX_URL = os.environ.get("VARIANT_PROXY_COMPLEX_URL", "http://47.74.8.132:28899")
    VARIANT_PROXY_FAST_TOKEN = os.environ.get("VARIANT_PROXY_FAST_TOKEN", VARIANT_PROXY_TOKEN)
    VARIANT_PROXY_COMPLEX_TOKEN = os.environ.get("VARIANT_PROXY_COMPLEX_TOKEN", VARIANT_PROXY_TOKEN)
    VARIANT_PROXY_FAST_TIMEOUT = int(os.environ.get("VARIANT_PROXY_FAST_TIMEOUT", VARIANT_PROXY_TIMEOUT))
    VARIANT_PROXY_COMPLEX_TIMEOUT = int(os.environ.get("VARIANT_PROXY_COMPLEX_TIMEOUT", VARIANT_PROXY_TIMEOUT))
    VARIANT_PROXY_DEFAULT_AGENT = os.environ.get("VARIANT_PROXY_DEFAULT_AGENT", "fast").lower()
    VARIANT_PROXY_ENDPOINTS = {
        "fast": {
            "base_url": VARIANT_PROXY_FAST_URL,
            "token": VARIANT_PROXY_FAST_TOKEN,
            "timeout": VARIANT_PROXY_FAST_TIMEOUT,
        },
        "complex": {
            "base_url": VARIANT_PROXY_COMPLEX_URL,
            "token": VARIANT_PROXY_COMPLEX_TOKEN,
            "timeout": VARIANT_PROXY_COMPLEX_TIMEOUT,
        },
    }


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    VARIANT_PROXY_ENABLED = False
