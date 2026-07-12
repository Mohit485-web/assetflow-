from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db

# ---------- Enums (plain strings kept simple for SQLite + hackathon speed) ----------

ROLE_EMPLOYEE = "Employee"
ROLE_DEPT_HEAD = "DepartmentHead"
ROLE_ASSET_MANAGER = "AssetManager"
ROLE_ADMIN = "Admin"
ROLES = [ROLE_EMPLOYEE, ROLE_DEPT_HEAD, ROLE_ASSET_MANAGER, ROLE_ADMIN]

ASSET_AVAILABLE = "Available"
ASSET_ALLOCATED = "Allocated"
ASSET_RESERVED = "Reserved"
ASSET_MAINTENANCE = "UnderMaintenance"
ASSET_LOST = "Lost"
ASSET_RETIRED = "Retired"
ASSET_DISPOSED = "Disposed"
ASSET_STATUSES = [
    ASSET_AVAILABLE, ASSET_ALLOCATED, ASSET_RESERVED,
    ASSET_MAINTENANCE, ASSET_LOST, ASSET_RETIRED, ASSET_DISPOSED,
]


class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    head_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True)
    status = db.Column(db.String(20), default="Active")  # Active / Inactive
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    head = db.relationship("User", foreign_keys=[head_id])
    parent = db.relationship("Department", remote_side=[id])


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(30), nullable=True, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default=ROLE_EMPLOYEE, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True)
    status = db.Column(db.String(20), default="Active")  # Active / Inactive
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    department = db.relationship("Department", foreign_keys=[department_id])

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_asset_manager(self):
        return self.role == ROLE_ASSET_MANAGER

    @property
    def is_dept_head(self):
        return self.role == ROLE_DEPT_HEAD


class AssetCategory(db.Model):
    __tablename__ = "asset_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    custom_fields = db.Column(db.Text, nullable=True)  # simple JSON string, kept minimal for MVP


class Asset(db.Model):
    __tablename__ = "assets"
    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String(20), nullable=False, unique=True, index=True)  # e.g. AF-0001
    name = db.Column(db.String(160), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("asset_categories.id"), nullable=False)
    serial_number = db.Column(db.String(120), nullable=True)
    acquisition_date = db.Column(db.Date, nullable=True)
    acquisition_cost = db.Column(db.Numeric(12, 2), nullable=True)
    condition = db.Column(db.String(40), default="Good")
    location = db.Column(db.String(160), nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)
    is_bookable = db.Column(db.Boolean, default=False)  # shared resource flag
    status = db.Column(db.String(30), default=ASSET_AVAILABLE, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("AssetCategory")

    @staticmethod
    def generate_tag():
        """AF-0001 style auto tag, based on current max id."""
        last = Asset.query.order_by(Asset.id.desc()).first()
        next_id = (last.id + 1) if last else 1
        return f"AF-{next_id:04d}"


class Allocation(db.Model):
    __tablename__ = "allocations"
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True)
    allocated_date = db.Column(db.DateTime, default=datetime.utcnow)
    expected_return_date = db.Column(db.Date, nullable=True)
    actual_return_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default="Active")  # Active / Returned
    condition_notes = db.Column(db.Text, nullable=True)

    asset = db.relationship("Asset")
    employee = db.relationship("User", foreign_keys=[employee_id])
    department = db.relationship("Department", foreign_keys=[department_id])


class TransferRequest(db.Model):
    __tablename__ = "transfer_requests"
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), default="Requested")  # Requested / Approved / Rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    asset = db.relationship("Asset")
    from_user = db.relationship("User", foreign_keys=[from_user_id])
    to_user = db.relationship("User", foreign_keys=[to_user_id])
    requester = db.relationship("User", foreign_keys=[requested_by])


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    booked_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default="Upcoming")  # Upcoming/Ongoing/Completed/Cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    asset = db.relationship("Asset")
    booker = db.relationship("User")


class MaintenanceRequest(db.Model):
    __tablename__ = "maintenance_requests"
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    raised_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    issue = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), default="Medium")  # Low/Medium/High
    photo_url = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default="Pending")
    # Pending -> Approved/Rejected -> TechnicianAssigned -> InProgress -> Resolved
    technician_name = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    asset = db.relationship("Asset")
    raiser = db.relationship("User")


class AuditCycle(db.Model):
    __tablename__ = "audit_cycles"
    id = db.Column(db.Integer, primary_key=True)
    scope_department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True)
    scope_location = db.Column(db.String(160), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default="Open")  # Open / Closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    department = db.relationship("Department")


class AuditItem(db.Model):
    __tablename__ = "audit_items"
    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey("audit_cycles.id"), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    auditor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    result = db.Column(db.String(20), nullable=True)  # Verified / Missing / Damaged

    cycle = db.relationship("AuditCycle")
    asset = db.relationship("Asset")
    auditor = db.relationship("User")


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(60), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(160), nullable=False)
    entity = db.Column(db.String(80), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
