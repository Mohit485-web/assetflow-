from datetime import datetime
from decimal import Decimal, InvalidOperation
import csv
import io
from sqlalchemy import or_
from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from app import db
from app.models import (ActivityLog, Allocation, Asset, AssetCategory, AuditCycle, AuditItem,
    Booking, Department, MaintenanceRequest, TransferRequest, User, Notification,
    ASSET_ALLOCATED, ASSET_AVAILABLE, ASSET_LOST, ASSET_MAINTENANCE, ASSET_STATUSES, ROLES)

operations_bp = Blueprint("operations", __name__)

def _record(action, entity=None): db.session.add(ActivityLog(user_id=current_user.id, action=action, entity=entity))
def _manager_required():
    if not (current_user.is_admin or current_user.is_asset_manager): abort(403)
def _date(value): return datetime.strptime(value, "%Y-%m-%d").date() if value else None
def _notify(user_id, message, kind="Update"): db.session.add(Notification(user_id=user_id, message=message, type=kind))

@operations_bp.route("/assets", methods=["GET", "POST"])
@login_required
def assets():
    categories = AssetCategory.query.order_by(AssetCategory.name).all()
    if request.method == "POST":
        _manager_required(); name = request.form.get("name", "").strip(); category_id = request.form.get("category_id", type=int)
        if not name or not db.session.get(AssetCategory, category_id): flash("Asset name and valid category are required.", "error")
        else:
            try: cost = Decimal(request.form.get("acquisition_cost")) if request.form.get("acquisition_cost") else None
            except InvalidOperation: cost = None
            asset = Asset(tag=Asset.generate_tag(), name=name, category_id=category_id,
                serial_number=request.form.get("serial_number", "").strip() or None, acquisition_date=_date(request.form.get("acquisition_date")), acquisition_cost=cost,
                condition=request.form.get("condition", "Good"), location=request.form.get("location", "").strip() or None,
                photo_url=request.form.get("document_url", "").strip() or None, is_bookable=bool(request.form.get("is_bookable")), status=ASSET_AVAILABLE)
            db.session.add(asset); _record(f"Registered asset {asset.tag}", "Asset"); db.session.commit(); flash(f"{asset.name} registered as {asset.tag}.", "success")
            return redirect(url_for("operations.assets"))
    q, status, category_id = request.args.get("q", "").strip(), request.args.get("status", ""), request.args.get("category_id", type=int)
    query = Asset.query
    if q:
        like = f"%{q}%"; query = query.filter(or_(Asset.tag.ilike(like), Asset.name.ilike(like), Asset.serial_number.ilike(like), Asset.location.ilike(like)))
    if status in ASSET_STATUSES: query = query.filter_by(status=status)
    if category_id: query = query.filter_by(category_id=category_id)
    return render_template("operations/assets.html", assets=query.order_by(Asset.id.desc()).all(), categories=categories, statuses=ASSET_STATUSES)

@operations_bp.route("/assets/<int:asset_id>/update", methods=["POST"])
@login_required
def update_asset(asset_id):
    _manager_required(); asset = db.get_or_404(Asset, asset_id)
    asset.name = request.form.get("name", asset.name).strip() or asset.name; asset.serial_number = request.form.get("serial_number", "").strip() or None
    category_id = request.form.get("category_id", type=int)
    if db.session.get(AssetCategory, category_id): asset.category_id = category_id
    asset.location = request.form.get("location", "").strip() or None; asset.condition = request.form.get("condition", asset.condition); asset.acquisition_date = _date(request.form.get("acquisition_date")); asset.photo_url = request.form.get("document_url", "").strip() or None
    try: asset.acquisition_cost = Decimal(request.form.get("acquisition_cost")) if request.form.get("acquisition_cost") else None
    except InvalidOperation: pass
    status = request.form.get("status")
    if status in ASSET_STATUSES and not Allocation.query.filter_by(asset_id=asset.id, status="Active").first(): asset.status = status
    asset.is_bookable = bool(request.form.get("is_bookable")); _record(f"Updated {asset.tag}", "Asset"); db.session.commit(); flash("Asset updated.", "success")
    return redirect(url_for("operations.assets"))

@operations_bp.route("/assets/<int:asset_id>/delete", methods=["POST"])
@login_required
def delete_asset(asset_id):
    _manager_required(); asset = db.get_or_404(Asset, asset_id)
    if Allocation.query.filter_by(asset_id=asset.id, status="Active").first() or Booking.query.filter_by(asset_id=asset.id, status="Upcoming").first(): flash("This asset has active records and cannot be deleted.", "error")
    else: db.session.delete(asset); _record(f"Deleted {asset.tag}", "Asset"); db.session.commit(); flash("Asset deleted.", "success")
    return redirect(url_for("operations.assets"))

@operations_bp.route("/assets/<int:asset_id>/history")
@login_required
def asset_history(asset_id):
    asset = db.get_or_404(Asset, asset_id)
    allocations = Allocation.query.filter_by(asset_id=asset.id).order_by(Allocation.allocated_date.desc()).all()
    maintenance_items = MaintenanceRequest.query.filter_by(asset_id=asset.id).order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template("operations/asset_history.html", asset=asset, allocations=allocations, maintenance_items=maintenance_items)

@operations_bp.route("/allocations", methods=["GET", "POST"])
@login_required
def allocations():
    if request.method == "POST":
        _manager_required(); asset = db.session.get(Asset, request.form.get("asset_id", type=int)); user_id = request.form.get("user_id", type=int)
        if not asset or not user_id: flash("Select an asset and employee.", "error")
        elif asset.status != ASSET_AVAILABLE:
            holder = Allocation.query.filter_by(asset_id=asset.id, status="Active").first(); flash(f"This asset is currently held by {holder.employee.name if holder and holder.employee else 'another user'}. Request a transfer instead.", "error")
        else:
            db.session.add(Allocation(asset_id=asset.id, employee_id=user_id, expected_return_date=_date(request.form.get("expected_return_date")))); asset.status = ASSET_ALLOCATED; _notify(user_id, f"{asset.tag} has been assigned to you.", "AssetAssigned"); _record(f"Allocated {asset.tag}", "Allocation"); db.session.commit(); flash("Asset allocated.", "success")
        return redirect(url_for("operations.allocations"))
    return render_template("operations/allocations.html", allocations=Allocation.query.filter_by(status="Active").order_by(Allocation.allocated_date.desc()).all(), assets=Asset.query.filter_by(status=ASSET_AVAILABLE).order_by(Asset.name).all(), users=User.query.filter_by(status="Active").order_by(User.name).all(), transfers=TransferRequest.query.order_by(TransferRequest.created_at.desc()).all())

@operations_bp.route("/allocations/<int:allocation_id>/return", methods=["POST"])
@login_required
def return_asset(allocation_id):
    _manager_required(); allocation = db.get_or_404(Allocation, allocation_id); allocation.status = "Returned"; allocation.actual_return_date = datetime.utcnow(); allocation.condition_notes = request.form.get("condition_notes", "").strip() or None; allocation.asset.status = ASSET_AVAILABLE; _record(f"Returned {allocation.asset.tag}", "Allocation"); db.session.commit(); flash("Asset returned and marked Available.", "success"); return redirect(url_for("operations.allocations"))

@operations_bp.route("/transfers", methods=["POST"])
@login_required
def request_transfer():
    allocation = db.get_or_404(Allocation, request.form.get("allocation_id", type=int)); to_user_id = request.form.get("to_user_id", type=int)
    if allocation.status != "Active" or not to_user_id or to_user_id == allocation.employee_id: flash("Choose a different employee for an active allocation.", "error")
    else: db.session.add(TransferRequest(asset_id=allocation.asset_id, from_user_id=allocation.employee_id, to_user_id=to_user_id, requested_by=current_user.id)); _record(f"Requested transfer of {allocation.asset.tag}", "TransferRequest"); db.session.commit(); flash("Transfer request submitted.", "success")
    return redirect(url_for("operations.allocations"))

@operations_bp.route("/transfers/<int:transfer_id>/resolve", methods=["POST"])
@login_required
def resolve_transfer(transfer_id):
    _manager_required(); transfer = db.get_or_404(TransferRequest, transfer_id); decision = request.form.get("decision")
    if transfer.status != "Requested" or decision not in {"Approved", "Rejected"}: abort(400)
    transfer.status, transfer.resolved_at = decision, datetime.utcnow()
    if decision == "Approved":
        old = Allocation.query.filter_by(asset_id=transfer.asset_id, status="Active").first()
        if old: old.status, old.actual_return_date = "Returned", datetime.utcnow()
        db.session.add(Allocation(asset_id=transfer.asset_id, employee_id=transfer.to_user_id)); transfer.asset.status = ASSET_ALLOCATED; _notify(transfer.to_user_id, f"{transfer.asset.tag} was transferred to you.", "TransferApproved")
    _record(f"{decision} transfer of {transfer.asset.tag}", "TransferRequest"); db.session.commit(); flash(f"Transfer {decision.lower()}.", "success"); return redirect(url_for("operations.allocations"))

@operations_bp.route("/bookings", methods=["GET", "POST"])
@login_required
def bookings():
    if request.method == "POST":
        asset_id = request.form.get("asset_id", type=int)
        try: start, end = datetime.fromisoformat(request.form.get("start_time", "")), datetime.fromisoformat(request.form.get("end_time", ""))
        except ValueError: flash("Enter a valid start and end time.", "error"); return redirect(url_for("operations.bookings"))
        asset = db.session.get(Asset, asset_id); conflict = Booking.query.filter(Booking.asset_id == asset_id, Booking.status != "Cancelled", Booking.start_time < end, Booking.end_time > start).first()
        if not asset or not asset.is_bookable or end <= start: flash("Choose a bookable resource and valid time range.", "error")
        elif conflict: flash("This booking overlaps an existing reservation.", "error")
        else: db.session.add(Booking(asset_id=asset_id, booked_by=current_user.id, start_time=start, end_time=end)); _record("Created resource booking", "Booking"); db.session.commit(); flash("Booking confirmed.", "success")
        return redirect(url_for("operations.bookings"))
    now = datetime.utcnow()
    for booking in Booking.query.filter(Booking.status != "Cancelled").all():
        booking.status = "Completed" if booking.end_time <= now else ("Ongoing" if booking.start_time <= now else "Upcoming")
    db.session.commit(); return render_template("operations/bookings.html", bookings=Booking.query.order_by(Booking.start_time.desc()).all(), assets=Asset.query.filter_by(is_bookable=True).order_by(Asset.name).all())

@operations_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.booked_by != current_user.id and not (current_user.is_admin or current_user.is_asset_manager): abort(403)
    booking.status = "Cancelled"; _record("Cancelled resource booking", "Booking"); db.session.commit(); flash("Booking cancelled.", "success"); return redirect(url_for("operations.bookings"))

@operations_bp.route("/maintenance", methods=["GET", "POST"])
@login_required
def maintenance():
    assets = Asset.query.order_by(Asset.name).all()
    if request.method == "POST":
        asset_id, issue = request.form.get("asset_id", type=int), request.form.get("issue", "").strip()
        if not db.session.get(Asset, asset_id) or not issue: flash("Select an asset and describe the issue.", "error")
        else: db.session.add(MaintenanceRequest(asset_id=asset_id, raised_by=current_user.id, issue=issue, priority=request.form.get("priority", "Medium"), photo_url=request.form.get("photo_url", "").strip() or None)); _record("Raised maintenance request", "MaintenanceRequest"); db.session.commit(); flash("Maintenance request submitted for approval.", "success")
        return redirect(url_for("operations.maintenance"))
    return render_template("operations/maintenance.html", assets=assets, items=MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all())

@operations_bp.route("/maintenance/<int:request_id>/status", methods=["POST"])
@login_required
def maintenance_status(request_id):
    _manager_required(); item = db.get_or_404(MaintenanceRequest, request_id); status = request.form.get("status")
    if status not in {"Approved", "Rejected", "TechnicianAssigned", "InProgress", "Resolved"}: abort(400)
    item.status = status; item.technician_name = request.form.get("technician_name", "").strip() or item.technician_name
    if status in {"Approved", "TechnicianAssigned", "InProgress"}: item.asset.status = ASSET_MAINTENANCE
    elif status == "Resolved": item.asset.status, item.resolved_at = ASSET_AVAILABLE, datetime.utcnow()
    _record(f"Set maintenance request to {status}", "MaintenanceRequest"); db.session.commit(); flash("Maintenance request updated.", "success"); return redirect(url_for("operations.maintenance"))

@operations_bp.route("/audits", methods=["GET", "POST"])
@login_required
def audits():
    if request.method == "POST":
        _manager_required(); start, end = _date(request.form.get("start_date")), _date(request.form.get("end_date"))
        if not start or not end or end < start: flash("Enter a valid audit date range.", "error")
        else:
            cycle = AuditCycle(scope_department_id=request.form.get("department_id", type=int), scope_location=request.form.get("location", "").strip() or None, start_date=start, end_date=end); db.session.add(cycle); db.session.flush()
            for asset in Asset.query.all(): db.session.add(AuditItem(cycle_id=cycle.id, asset_id=asset.id, auditor_id=request.form.get("auditor_id", type=int)))
            _record("Created audit cycle", "AuditCycle"); db.session.commit(); flash("Audit cycle created.", "success")
        return redirect(url_for("operations.audits"))
    return render_template("operations/audits.html", cycles=AuditCycle.query.order_by(AuditCycle.start_date.desc()).all(), audit_items=AuditItem.query.all(), departments=Department.query.order_by(Department.name).all(), users=User.query.order_by(User.name).all())

@operations_bp.route("/audits/<int:cycle_id>/items/<int:item_id>", methods=["POST"])
@login_required
def update_audit_item(cycle_id, item_id):
    item = db.get_or_404(AuditItem, item_id); result = request.form.get("result")
    if item.cycle_id != cycle_id or item.cycle.status == "Closed" or result not in {"Verified", "Missing", "Damaged"}: abort(400)
    item.result = result
    if result == "Missing": item.asset.status = ASSET_LOST
    elif result == "Damaged": item.asset.status = ASSET_MAINTENANCE
    _record(f"Audited {item.asset.tag}: {result}", "AuditItem"); db.session.commit(); return redirect(url_for("operations.audits"))

@operations_bp.route("/audits/<int:cycle_id>/close", methods=["POST"])
@login_required
def close_audit(cycle_id):
    _manager_required(); cycle = db.get_or_404(AuditCycle, cycle_id); cycle.status = "Closed"; _record("Closed audit cycle", "AuditCycle"); db.session.commit(); flash("Audit cycle closed.", "success"); return redirect(url_for("operations.audits"))

@operations_bp.route("/reports")
@login_required
def reports():
    metrics = [("Registered assets", Asset.query.count()), ("Available assets", Asset.query.filter_by(status=ASSET_AVAILABLE).count()), ("Allocated assets", Allocation.query.filter_by(status="Active").count()), ("Maintenance requests", MaintenanceRequest.query.count()), ("Active bookings", Booking.query.filter(Booking.status.in_(["Upcoming", "Ongoing"])).count())]
    category_summary = [(category.name, Asset.query.filter_by(category_id=category.id).count()) for category in AssetCategory.query.order_by(AssetCategory.name).all()]
    department_summary = [(department.name, Allocation.query.filter_by(department_id=department.id, status="Active").count()) for department in Department.query.order_by(Department.name).all()]
    maintenance_summary = [(asset, MaintenanceRequest.query.filter_by(asset_id=asset.id).count()) for asset in Asset.query.order_by(Asset.name).all()]
    maintenance_summary = [item for item in maintenance_summary if item[1]]
    return render_template("operations/reports.html", metrics=metrics, category_summary=category_summary, department_summary=department_summary, maintenance_summary=maintenance_summary)

@operations_bp.route("/reports/export")
@login_required
def export_report():
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Asset Tag", "Name", "Category", "Status", "Location", "Condition", "Acquisition Cost"])
    for asset in Asset.query.order_by(Asset.tag).all(): writer.writerow([asset.tag, asset.name, asset.category.name, asset.status, asset.location or "", asset.condition, asset.acquisition_cost or ""])
    response = make_response(output.getvalue()); response.headers["Content-Disposition"] = "attachment; filename=assetflow-assets.csv"; response.headers["Content-Type"] = "text/csv"
    return response

@operations_bp.route("/activity")
@login_required
def activity():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(100).all(); notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(20).all()
    return render_template("operations/list.html", title="Activity & notifications", description="A record of actions performed in AssetFlow.", headers=["When", "Who", "Action", "Entity"], rows=[(x.timestamp.strftime("%d %b %Y %H:%M"), x.user.name if x.user else "System", x.action, x.entity or "—") for x in logs], empty="No activity has been recorded yet.", notifications=notifications)

@operations_bp.route("/organization", methods=["GET", "POST"])
@login_required
def organization():
    if not current_user.is_admin: abort(403)
    if request.method == "POST":
        kind, name = request.form.get("kind"), request.form.get("name", "").strip()
        model = Department if kind == "department" else AssetCategory if kind == "category" else None
        if kind in {"department", "category"}:
            if not name or not model: flash("Enter a valid name.", "error")
            elif model.query.filter_by(name=name).first(): flash("That name already exists.", "error")
            else: db.session.add(model(name=name)); _record(f"Created {kind} {name}", model.__name__); db.session.commit(); flash(f"{kind.title()} created.", "success")
        elif kind == "department_update":
            department = db.get_or_404(Department, request.form.get("department_id", type=int)); department.status = request.form.get("status") if request.form.get("status") in {"Active", "Inactive"} else department.status
            department.head_id = request.form.get("head_id", type=int) or None; department.parent_id = request.form.get("parent_id", type=int) or None
            if department.parent_id == department.id: department.parent_id = None
            _record(f"Updated department {department.name}", "Department"); db.session.commit(); flash("Department updated.", "success")
        elif kind == "category_update":
            category = db.get_or_404(AssetCategory, request.form.get("category_id", type=int)); category.custom_fields = request.form.get("custom_fields", "").strip() or None
            _record(f"Updated category {category.name}", "AssetCategory"); db.session.commit(); flash("Category updated.", "success")
        elif kind == "employee_update":
            user = db.get_or_404(User, request.form.get("user_id", type=int)); role, status = request.form.get("role"), request.form.get("status")
            if role in ROLES: user.role = role
            if status in {"Active", "Inactive"}: user.status = status
            department_id = request.form.get("department_id", type=int); user.department_id = department_id if not department_id or db.session.get(Department, department_id) else user.department_id
            _record(f"Updated employee {user.name}", "User"); db.session.commit(); flash("Employee updated.", "success")
        else: flash("Unknown organization action.", "error")
        return redirect(url_for("operations.organization"))
    return render_template("operations/organization.html", departments=Department.query.order_by(Department.name).all(), categories=AssetCategory.query.order_by(AssetCategory.name).all(), users=User.query.order_by(User.name).all())
