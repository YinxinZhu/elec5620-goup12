from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from pathlib import Path

from .config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "coach.login"

def create_app(config_class: type[Config] | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    config = config_class or Config
    app.config.from_object(config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from .models import Coach

    @login_manager.user_loader
    def load_user(user_id: str) -> Coach | None:
        return Coach.query.get(int(user_id))

    from .coach.routes import coach_bp
    app.register_blueprint(coach_bp)

    @app.route("/")
    def index():
        from flask import redirect, url_for

        return redirect(url_for("coach.login"))

    return app
