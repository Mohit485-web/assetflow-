import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, "assetflow.db").replace("\\", "/")

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
    "DATABASE_URL",
    "sqlite:///assetflow.db"
)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    OTP_DEMO_MODE = os.environ.get("OTP_DEMO_MODE", "true").lower() == "true"
