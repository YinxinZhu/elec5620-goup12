from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api")

from . import routes  # noqa: E402  # isort:skip

__all__ = ["api_bp"]
