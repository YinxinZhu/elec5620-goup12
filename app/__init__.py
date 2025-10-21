from flask import Flask, flash, g, redirect, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "coach.login"

from .config import Config
from .db_maintenance import ensure_database_schema
from .i18n import (
    DEFAULT_LANGUAGE,
    ensure_language_code,
    get_language_choices,
    language_label,
    normalise_language_code,
    translate_text,
)


def _translate(message: str, *, language: str | None = None, **values: str) -> str:
    active_language = ensure_language_code(language or getattr(g, "active_language", DEFAULT_LANGUAGE))
    return translate_text(message, active_language, **values)

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

    from .models import Coach, Student
    from .services.language_management import (
        LanguageSwitchError,
        switch_student_language,
    )

    @login_manager.user_loader
    def load_user(user_id: str) -> Coach | Student | None:
        try:
            role, raw_id = user_id.split(":", 1)
            identity = int(raw_id)
        except (ValueError, TypeError):
            return None

        if role in {"coach", "admin"}:
            user = db.session.get(Coach, identity)
            if not user:
                return None
            if role == "admin" and not user.is_admin:
                return None
            return user

        if role == "student":
            return db.session.get(Student, identity)

        return None

    from .coach.routes import coach_bp
    from .student.routes import student_bp
    from .api import api_bp

    app.register_blueprint(coach_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def assign_active_language() -> None:
        language = None
        if current_user.is_authenticated:
            user = current_user._get_current_object()
            preference = getattr(user, "preferred_language", None)
            language = normalise_language_code(preference) or language
        session_preference = normalise_language_code(session.get("preferred_language"))
        if not language:
            language = session_preference
        if not language:
            language = DEFAULT_LANGUAGE
        session["preferred_language"] = language
        g.active_language = language

    @app.context_processor
    def inject_i18n():
        active = ensure_language_code(getattr(g, "active_language", DEFAULT_LANGUAGE))

        def translate(text: str, **values: str) -> str:
            return translate_text(text, active, **values)

        return {
            "_": translate,
            "active_language": active,
            "language_choices": get_language_choices(),
            "language_label": language_label,
        }

    @app.post("/language")
    def switch_language():
        requested = normalise_language_code(request.form.get("language"))
        redirect_target = request.form.get("next") or request.referrer or url_for("coach.login")

        if not requested:
            flash(_translate("Please choose a supported language."), "danger")
            return redirect(redirect_target)

        message: str | None = None
        previous_language = ensure_language_code(
            normalise_language_code(session.get("preferred_language")) or DEFAULT_LANGUAGE
        )
        if current_user.is_authenticated:
            user = current_user._get_current_object()
            preference_attr = getattr(user, "preferred_language", None)
            if preference_attr is not None:
                acting_student = user if getattr(user, "is_student", False) else None
                try:
                    message = switch_student_language(
                        user, requested, acting_student=acting_student
                    )
                    db.session.commit()
                except LanguageSwitchError as exc:
                    db.session.rollback()
                    session["preferred_language"] = previous_language
                    g.active_language = previous_language
                    flash(str(exc), "danger")
                    return redirect(redirect_target)

        session["preferred_language"] = requested
        g.active_language = requested

        if not message:
            message = translate_text(
                "Language switched to {label}.",
                requested,
                label=language_label(requested),
            )

        flash(message, "info")
        return redirect(redirect_target)

    @app.route("/")
    def index():
        return redirect(url_for("coach.login"))

    with app.app_context():
        ensure_database_schema(db.engine, app.logger)

    return app
