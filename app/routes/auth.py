from datetime import datetime, timedelta, timezone
import json
import os
import re
import secrets
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


def _issue_otp(session_prefix):
    code = f"{secrets.randbelow(1_000_000):06d}"
    session[f"{session_prefix}_code_hash"] = generate_password_hash(code)
    session[f"{session_prefix}_expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    return code


def _otp_is_valid(session_prefix, submitted_code):
    expires_at = session.get(f"{session_prefix}_expires_at")
    valid_code = session.get(f"{session_prefix}_code_hash")
    return bool(
        expires_at
        and valid_code
        and datetime.now(timezone.utc) <= datetime.fromisoformat(expires_at)
        and check_password_hash(valid_code, submitted_code)
    )


def _clear_otp(session_prefix):
    for suffix in ("_code_hash", "_expires_at"):
        session.pop(f"{session_prefix}{suffix}", None)


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


@auth_bp.route("/signup/otp", methods=["GET", "POST"])
def otp_signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    departments = Department.query.filter_by(status="Active").order_by(Department.name).all()
    saved = session.get("signup_otp_data", {})
    if request.method == "POST":
        action = request.form.get("action")
        if action == "send":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = _normalise_phone(request.form.get("phone", ""))
            department_id = request.form.get("department_id") or None
            channel = request.form.get("channel", "email")

            if not name or not email:
                flash("Full name and work email are required.", "error")
                return render_template("auth/otp_signup.html", departments=departments, saved=request.form)
            if channel == "mobile" and not phone:
                flash("Enter a mobile number to verify by mobile OTP.", "error")
                return render_template("auth/otp_signup.html", departments=departments, saved=request.form)
            if User.query.filter_by(email=email).first() or (phone and User.query.filter_by(phone=phone).first()):
                flash("An account already exists with that email or mobile number.", "error")
                return render_template("auth/otp_signup.html", departments=departments, saved=request.form)

            session["signup_otp_data"] = {"name": name, "email": email, "phone": phone, "department_id": department_id}
            code = _issue_otp("signup_otp")
            if current_app.config["OTP_DEMO_MODE"]:
                flash(f"Demo OTP: {code} (valid for 10 minutes)", "info")
            else:
                _clear_otp("signup_otp")
                session.pop("signup_otp_data", None)
                flash("OTP delivery is not configured. Set OTP_DEMO_MODE=true for a demo or connect an email/SMS provider.", "error")
                return render_template("auth/otp_signup.html", departments=departments, saved=request.form)
            return render_template("auth/otp_signup.html", departments=departments, saved=session["signup_otp_data"], code_sent=True)

        if action == "verify":
            saved = session.get("signup_otp_data")
            if not saved or not _otp_is_valid("signup_otp", request.form.get("code", "")):
                flash("That code is invalid or expired. Request a new code.", "error")
                return render_template("auth/otp_signup.html", departments=departments, saved=saved or {})
            if User.query.filter_by(email=saved["email"]).first() or (saved["phone"] and User.query.filter_by(phone=saved["phone"]).first()):
                flash("An account was created with these details. Please sign in.", "info")
                return redirect(url_for("auth.login"))

            user = User(name=saved["name"], email=saved["email"], phone=saved["phone"] or None,
                        role=ROLE_EMPLOYEE, department_id=saved["department_id"])
            user.set_password(secrets.token_urlsafe(32))
            db.session.add(user)
            db.session.commit()
            _clear_otp("signup_otp")
            session.pop("signup_otp_data", None)
            login_user(user)
            flash("Your employee account is ready.", "success")
            return redirect(url_for("dashboard.home"))

    return render_template("auth/otp_signup.html", departments=departments, saved=saved)


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

            session["otp_user_id"] = user.id
            code = _issue_otp("otp")
            session["otp_identity"] = identity
            if current_app.config["OTP_DEMO_MODE"]:
                flash(f"Demo OTP: {code} (valid for 10 minutes)", "info")
            else:
                _clear_otp("otp")
                session.pop("otp_user_id", None)
                session.pop("otp_identity", None)
                flash("OTP delivery is not configured. Set OTP_DEMO_MODE=true for a demo or connect an email/SMS provider.", "error")
                return render_template("auth/otp_login.html", identity=identity)
            return render_template("auth/otp_login.html", identity=identity, code_sent=True)

        if action == "verify":
            user_id = session.get("otp_user_id")
            submitted_code = request.form.get("code", "")
            if not user_id or not _otp_is_valid("otp", submitted_code):
                flash("That code is invalid or expired. Request a new code.", "error")
                return render_template("auth/otp_login.html", identity=session.get("otp_identity", ""))

            user = db.session.get(User, user_id)
            _clear_otp("otp")
            session.pop("otp_user_id", None)
            session.pop("otp_identity", None)
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
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        flash("Google Sign-In needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file.", "error")
        return redirect(url_for("auth.login"))
    state = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state
    callback = url_for("auth.google_callback", _external=True)
    query = urlencode({"client_id": client_id, "redirect_uri": callback, "response_type": "code",
                       "scope": "openid email profile", "state": state, "prompt": "select_account"})
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@auth_bp.route("/login/google/callback")
def google_callback():
    if request.args.get("error"):
        flash("Google Sign-In was cancelled.", "info")
        return redirect(url_for("auth.login"))
    if request.args.get("state") != session.pop("google_oauth_state", None):
        flash("Google Sign-In could not be verified. Please try again.", "error")
        return redirect(url_for("auth.login"))
    code = request.args.get("code")
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not code or not client_id or not client_secret:
        flash("Google Sign-In configuration is incomplete.", "error")
        return redirect(url_for("auth.login"))

    callback = url_for("auth.google_callback", _external=True)
    try:
        payload = urlencode({"code": code, "client_id": client_id, "client_secret": client_secret,
                             "redirect_uri": callback, "grant_type": "authorization_code"}).encode()
        with urlopen(Request("https://oauth2.googleapis.com/token", data=payload,
                             headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=10) as response:
            token = json.load(response)
        with urlopen(Request("https://openidconnect.googleapis.com/v1/userinfo",
                             headers={"Authorization": f"Bearer {token['access_token']}"}), timeout=10) as response:
            profile = json.load(response)
    except Exception:
        flash("Google Sign-In could not be completed. Check your OAuth credentials and redirect URL.", "error")
        return redirect(url_for("auth.login"))

    email = profile.get("email", "").lower()
    if not email or not profile.get("email_verified"):
        flash("Google did not provide a verified email address.", "error")
        return redirect(url_for("auth.login"))
    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(name=profile.get("name") or email.split("@")[0], email=email, role=ROLE_EMPLOYEE)
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
        db.session.commit()
    if _login_non_admin(user):
        return redirect(url_for("dashboard.home"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been signed out.", "info")
    return redirect(url_for("auth.login"))
