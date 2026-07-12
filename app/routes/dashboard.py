from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from app import db
from app.models import (
    Asset, AssetCategory, Allocation, MaintenanceRequest, Booking, TransferRequest, ActivityLog,
    ASSET_AVAILABLE, ASSET_ALLOCATED, ASSET_MAINTENANCE,
)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/", methods=["GET", "POST"])
@login_required
def home():
    if request.method == "POST":
        if not (current_user.is_admin or current_user.is_asset_manager):
            flash("Only an Admin or Asset Manager can register assets.", "error")
        else:
            name = request.form.get("name", "").strip()
            category_id = request.form.get("category_id", type=int)
            if not name or not db.session.get(AssetCategory, category_id):
                flash("Enter an asset name and select a category.", "error")
            else:
                asset = Asset(tag=Asset.generate_tag(), name=name, category_id=category_id,
                              serial_number=request.form.get("serial_number", "").strip() or None,
                              location=request.form.get("location", "").strip() or None,
                              is_bookable=bool(request.form.get("is_bookable")), status=ASSET_AVAILABLE)
                db.session.add(asset)
                db.session.add(ActivityLog(user_id=current_user.id, action=f"Registered asset {asset.tag} from dashboard", entity="Asset"))
                db.session.commit()
                flash(f"{asset.name} registered as {asset.tag}.", "success")
        return redirect(url_for("dashboard.home"))
    today = date.today()

    kpis = {
        "available": Asset.query.filter_by(status=ASSET_AVAILABLE).count(),
        "allocated": Asset.query.filter_by(status=ASSET_ALLOCATED).count(),
        "maintenance_today": MaintenanceRequest.query.filter(
            MaintenanceRequest.status.in_(["Approved", "TechnicianAssigned", "InProgress"])
        ).count(),
        "active_bookings": Booking.query.filter_by(status="Upcoming").count(),
        "pending_transfers": TransferRequest.query.filter_by(status="Requested").count(),
        "upcoming_returns": Allocation.query.filter(
            Allocation.status == "Active",
            Allocation.expected_return_date.isnot(None),
            Allocation.expected_return_date >= today,
        ).count(),
    }

    overdue = (
        Allocation.query.filter(
            Allocation.status == "Active",
            Allocation.expected_return_date.isnot(None),
            Allocation.expected_return_date < today,
        )
        .limit(10)
        .all()
    )

    upcoming = (
        Allocation.query.filter(
            Allocation.status == "Active",
            Allocation.expected_return_date.isnot(None),
            Allocation.expected_return_date >= today,
        )
        .order_by(Allocation.expected_return_date)
        .limit(10)
        .all()
    )

    return render_template(
        "dashboard.html", kpis=kpis, overdue=overdue, upcoming=upcoming, today=today,
        categories=AssetCategory.query.order_by(AssetCategory.name).all(),
    )
