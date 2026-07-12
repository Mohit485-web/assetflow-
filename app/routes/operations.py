from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import (
    ActivityLog, Allocation, Asset, AssetCategory, AuditCycle, Booking, Department,
    MaintenanceRequest, TransferRequest, User, ASSET_AVAILABLE,
)

operations_bp = Blueprint("operations", __name__)


def _record(action, entity=None):
    db.session.add(ActivityLog(user_id=current_user.id, action=action, entity=entity))


def _manager_required():
    if not (current_user.is_admin or current_user.is_asset_manager):
        abort(403)


@operations_bp.route("/assets", methods=["GET", "POST"])
@login_required
def assets():
    categories = AssetCategory.query.order_by(AssetCategory.name).all()
    if request.method == "POST":
        _manager_required()
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", type=int)
        if not name or not category_id:
            flash("Asset name and category are required.", "error")
        else:
            asset = Asset(tag=Asset.generate_tag(), name=name, category_id=category_id,
                          serial_number=request.form.get("serial_number", "").strip() or None,
                          location=request.form.get("location", "").strip() or None,
                          is_bookable=bool(request.form.get("is_bookable")), status=ASSET_AVAILABLE)
            db.session.add(asset)
            _record(f"Registered asset {asset.tag}", "Asset")
            db.session.commit()
            flash(f"{asset.name} registered as {asset.tag}.", "success")
            return redirect(url_for("operations.assets"))
    return render_template("operations/assets.html", assets=Asset.query.order_by(Asset.id.desc()).all(), categories=categories)


@operations_bp.route("/maintenance", methods=["GET", "POST"])
@login_required
def maintenance():
    assets = Asset.query.order_by(Asset.name).all()
    if request.method == "POST":
        asset_id = request.form.get("asset_id", type=int)
        issue = request.form.get("issue", "").strip()
        if not asset_id or not issue:
            flash("Select an asset and describe the issue.", "error")
        else:
            item = MaintenanceRequest(asset_id=asset_id, raised_by=current_user.id, issue=issue,
                                      priority=request.form.get("priority", "Medium"))
            db.session.add(item)
            _record("Raised maintenance request", "MaintenanceRequest")
            db.session.commit()
            flash("Maintenance request submitted for approval.", "success")
            return redirect(url_for("operations.maintenance"))
    items = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template("operations/maintenance.html", assets=assets, items=items)


@operations_bp.route("/allocations")
@login_required
def allocations():
    return render_template("operations/list.html", title="Allocations & Transfers", description="Track custody, expected returns, and transfer requests.",
                           headers=["Asset", "Held by", "Expected return", "Status"],
                           rows=[(a.asset.tag + " — " + a.asset.name, a.employee.name if a.employee else (a.department.name if a.department else "—"), a.expected_return_date.strftime("%d %b %Y") if a.expected_return_date else "—", a.status) for a in Allocation.query.order_by(Allocation.allocated_date.desc()).all()],
                           empty="No allocations yet. Register an asset, then allocate it from this module in the next workflow update.")


@operations_bp.route("/bookings")
@login_required
def bookings():
    return render_template("operations/list.html", title="Resource Bookings", description="Shared asset reservations and booking activity.",
                           headers=["Resource", "Booked by", "Start", "Status"],
                           rows=[(b.asset.name, b.booker.name, b.start_time.strftime("%d %b %Y %H:%M"), b.status) for b in Booking.query.order_by(Booking.start_time.desc()).all()],
                           empty="No bookings yet. Mark an asset as bookable when registering it.")


@operations_bp.route("/audits")
@login_required
def audits():
    return render_template("operations/list.html", title="Audit Cycles", description="Verification cycles and discrepancy reviews.",
                           headers=["Scope", "Start", "End", "Status"],
                           rows=[((a.department.name if a.department else a.scope_location or "Organization-wide"), a.start_date.strftime("%d %b %Y"), a.end_date.strftime("%d %b %Y"), a.status) for a in AuditCycle.query.order_by(AuditCycle.start_date.desc()).all()],
                           empty="No audit cycles yet. Administrators can create the first audit cycle here in the next workflow update.")


@operations_bp.route("/reports")
@login_required
def reports():
    metrics = [("Registered assets", Asset.query.count()), ("Allocated assets", Allocation.query.filter_by(status="Active").count()),
               ("Maintenance requests", MaintenanceRequest.query.count()), ("Active bookings", Booking.query.filter_by(status="Upcoming").count())]
    return render_template("operations/reports.html", metrics=metrics)


@operations_bp.route("/activity")
@login_required
def activity():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(100).all()
    return render_template("operations/list.html", title="Activity Log", description="A record of actions performed in AssetFlow.",
                           headers=["When", "Who", "Action", "Entity"],
                           rows=[(log.timestamp.strftime("%d %b %Y %H:%M"), log.user.name if log.user else "System", log.action, log.entity or "—") for log in logs],
                           empty="No activity has been recorded yet.")


@operations_bp.route("/organization", methods=["GET", "POST"])
@login_required
def organization():
    if not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        kind = request.form.get("kind")
        name = request.form.get("name", "").strip()
        if not name:
            flash("Enter a name before saving.", "error")
        elif kind == "department" and not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
            _record(f"Created department {name}", "Department")
            db.session.commit()
            flash("Department created.", "success")
        elif kind == "category" and not AssetCategory.query.filter_by(name=name).first():
            db.session.add(AssetCategory(name=name))
            _record(f"Created asset category {name}", "AssetCategory")
            db.session.commit()
            flash("Asset category created.", "success")
        else:
            flash("That name already exists.", "error")
        return redirect(url_for("operations.organization"))
    return render_template("operations/organization.html", departments=Department.query.order_by(Department.name).all(),
                           categories=AssetCategory.query.order_by(AssetCategory.name).all(), users=User.query.order_by(User.name).all())
