from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from .config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "coach.login"

def create_app(config_class: type[Config] | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    config = config_class or Config
    app.config.from_object(config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    if db_uri:
        try:
            url = make_url(db_uri)
        except ArgumentError:
            url = None
        if url and url.drivername == "sqlite" and url.database:
            db_path = Path(url.database)
            if not db_path.is_absolute():
                db_path = Path(app.root_path) / db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)

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
