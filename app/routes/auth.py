from datetime import datetime, timedelta, timezone
import re
import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from app.models import User, Department, ROLE_ADMIN, ROLE_EMPLOYEE

auth_bp = Blueprint("auth", __name__)


def _normalise_phone(value):
    """Store mobile numbers consistently while allowing spaces, dashes and country codes."""
    value = value.strip()
    if not value:
        return ""
    return "+" + re.sub(r"\D", "", value) if value.startswith("+") else re.sub(r"\D", "", value)


def _user_for_identity(identity):
    identity = identity.strip().lower()
    if "@" in identity:
        return User.query.filter_by(email=identity).first()
    return User.query.filter_by(phone=_normalise_phone(identity)).first()


def _login_non_admin(user):
    if user.status != "Active":
        flash("This account has been deactivated. Contact your Admin.", "error")
        return False
    if user.is_admin:
        flash("Please use the secure Admin sign-in page.", "info")
        return False
    login_user(user)
    return True


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    departments = Department.query.filter_by(status="Active").order_by(Department.name).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = _normalise_phone(request.form.get("phone", ""))
        password = request.form.get("password", "")
        department_id = request.form.get("department_id") or None

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("auth/signup.html", departments=departments)

        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "error")
            return render_template("auth/signup.html", departments=departments)

        if phone and User.query.filter_by(phone=phone).first():
            flash("An account with this mobile number already exists.", "error")
            return render_template("auth/signup.html", departments=departments)

        # Signup always creates an Employee account. No role selection at signup —
        # role changes only happen through Admin > Organization Setup > Employee Directory.
        user = User(name=name, email=email, phone=phone or None, role=ROLE_EMPLOYEE, department_id=department_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created. You can now sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/signup.html", departments=departments)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html")

        if _login_non_admin(user):
            return redirect(url_for("dashboard.home"))
        return render_template("auth/login.html")

    return render_template("auth/login.html")


@auth_bp.route("/login/otp", methods=["GET", "POST"])
def otp_login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "send":
            identity = request.form.get("identity", "")
            user = _user_for_identity(identity)
            if user is None:
                flash("We could not find an account with that email or mobile number.", "error")
                return render_template("auth/otp_login.html", identity=identity)
            if user.is_admin:
                flash("Administrators must use the secure Admin sign-in page.", "info")
                return redirect(url_for("auth.admin_login"))
            if user.status != "Active":
                flash("This account has been deactivated. Contact your Admin.", "error")
                return render_template("auth/otp_login.html", identity=identity)

            code = f"{secrets.randbelow(1_000_000):06d}"
            session["otp_user_id"] = user.id
            session["otp_code_hash"] = generate_password_hash(code)
            session["otp_expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            session["otp_identity"] = identity
            if current_app.config["OTP_DEMO_MODE"]:
                flash(f"Demo OTP: {code} (valid for 10 minutes)", "info")
            else:
                flash("Your one-time code has been sent.", "success")
            return render_template("auth/otp_login.html", identity=identity, code_sent=True)

        if action == "verify":
            user_id = session.get("otp_user_id")
            expires_at = session.get("otp_expires_at")
            valid_code = session.get("otp_code_hash")
            submitted_code = request.form.get("code", "")
            expired = not expires_at or datetime.now(timezone.utc) > datetime.fromisoformat(expires_at)
            if not user_id or not valid_code or expired or not check_password_hash(valid_code, submitted_code):
                flash("That code is invalid or expired. Request a new code.", "error")
                return render_template("auth/otp_login.html", identity=session.get("otp_identity", ""))

            user = db.session.get(User, user_id)
            for key in ("otp_user_id", "otp_code_hash", "otp_expires_at", "otp_identity"):
                session.pop(key, None)
            if user and _login_non_admin(user):
                return redirect(url_for("dashboard.home"))
            return redirect(url_for("auth.otp_login"))

    return render_template("auth/otp_login.html", identity=session.get("otp_identity", ""))


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user is None or user.role != ROLE_ADMIN or not user.check_password(password):
            flash("Invalid administrator credentials.", "error")
        elif user.status != "Active":
            flash("This administrator account has been deactivated.", "error")
        else:
            login_user(user)
            return redirect(url_for("dashboard.home"))

    return render_template("auth/admin_login.html")


@auth_bp.route("/login/google")
def google_login():
    flash("Google Sign-In is ready in the interface. Add your Google OAuth client ID and callback configuration before enabling it in production.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been signed out.", "info")
    return redirect(url_for("auth.login"))
