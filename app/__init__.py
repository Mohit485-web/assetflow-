import os
from sqlalchemy import inspect, text
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("config.Config")

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from app import models

    @login_manager.user_loader
    def load_user(user_id):
        return models.User.query.get(int(user_id))

    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)

    with app.app_context():
        # Debug Information
        print("=" * 60)
        print("Instance Path :", app.instance_path)
        print("Database URI  :", app.config["SQLALCHEMY_DATABASE_URI"])
        print("Engine URL    :", db.engine.url)
        print("=" * 60)

        try:
            conn = db.engine.connect()
            print("Database connection successful!")
            conn.close()
        except Exception as e:
            print("Database connection failed!")
            print(type(e).__name__)
            print(e)
            raise

        db.create_all()
        _ensure_schema()
        print("Tables created successfully!")

        _seed_admin()
        print("Admin seeded successfully!")

    return app


def _ensure_schema():
    """Apply the small SQLite schema update needed by existing demo databases."""
    columns = {column["name"] for column in inspect(db.engine).get_columns("users")}
    if "phone" not in columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(30)"))
        db.session.commit()


def _seed_admin():
    from app.models import User, ROLE_ADMIN

    if User.query.filter_by(role=ROLE_ADMIN).first() is None:
        admin = User(
            name="Admin",
            email="admin@assetflow.local",
            role=ROLE_ADMIN
        )
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()
