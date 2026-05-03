"""
Inject Firebase Web SDK config from .env into every template.
"""
import os

from django.conf import settings
from dotenv import load_dotenv

# Load .env when it exists (local development). In production the file won't
# be present; environment variables are already set by the platform.
_env_file = settings.BASE_DIR / ".env"
if _env_file.is_file():
    load_dotenv(_env_file)


def firebase_config(request):
    return {
        "FIREBASE_API_KEY": os.getenv("FIREBASE_API_KEY", "").strip('"').strip(",").strip(),
        "FIREBASE_AUTH_DOMAIN": os.getenv("FIREBASE_AUTH_DOMAIN", "").strip('"').strip(",").strip(),
        "FIREBASE_PROJECT_ID": os.getenv("FIREBASE_PROJECT_ID", "").strip('"').strip(",").strip(),
        "FIREBASE_STORAGE_BUCKET": os.getenv("FIREBASE_STORAGE_BUCKET_WEB", os.getenv("FIREBASE_STORAGE_BUCKET", "")).strip('"').strip(",").strip(),
        "FIREBASE_MESSAGING_SENDER_ID": os.getenv("FIREBASE_MESSAGING_SENDER_ID", "").strip('"').strip(",").strip(),
        "FIREBASE_APP_ID": os.getenv("FIREBASE_APP_ID", "").strip('"').strip(",").strip(),
    }
