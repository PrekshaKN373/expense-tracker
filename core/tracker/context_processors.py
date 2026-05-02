"""
Inject Firebase Web SDK config from .env into every template.
"""
import os

from django.conf import settings
from dotenv import load_dotenv

load_dotenv(settings.BASE_DIR / ".env")


def firebase_config(request):
    return {
        "FIREBASE_API_KEY": os.getenv("FIREBASE_API_KEY", "").strip('"').strip(",").strip(),
        "FIREBASE_AUTH_DOMAIN": os.getenv("FIREBASE_AUTH_DOMAIN", "").strip('"').strip(",").strip(),
        "FIREBASE_PROJECT_ID": os.getenv("FIREBASE_PROJECT_ID", "").strip('"').strip(",").strip(),
        "FIREBASE_STORAGE_BUCKET": os.getenv("FIREBASE_STORAGE_BUCKET_WEB", os.getenv("FIREBASE_STORAGE_BUCKET", "")).strip('"').strip(",").strip(),
        "FIREBASE_MESSAGING_SENDER_ID": os.getenv("FIREBASE_MESSAGING_SENDER_ID", "").strip('"').strip(",").strip(),
        "FIREBASE_APP_ID": os.getenv("FIREBASE_APP_ID", "").strip('"').strip(",").strip(),
    }
