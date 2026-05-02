"""
Firebase Admin SDK initialization and helpers.
Uses .env for config; credentials from FIREBASE_KEY_PATH (e.g. serviceAccountKey.json).
"""
import os

from django.conf import settings

# Load .env so os.getenv has values when this module runs
from dotenv import load_dotenv
load_dotenv(settings.BASE_DIR / ".env")

_db = None
_auth = None
_initialized = False


def _ensure_initialized():
    global _initialized, _db, _auth
    if _initialized:
        return
    import firebase_admin
    from firebase_admin import credentials, auth, firestore
    key_path = os.getenv("FIREBASE_KEY_PATH", "serviceAccountKey.json")
    if not os.path.isabs(key_path):
        key_path = str(settings.BASE_DIR / key_path)
    if not os.path.isfile(key_path):
        raise FileNotFoundError(f"Firebase key file not found: {key_path}")
    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred)
    _db = firestore.client()
    _auth = auth
    _initialized = True


def get_db():
    _ensure_initialized()
    return _db


def verify_token(id_token: str):
    """
    Verify a Firebase ID token from the frontend.
    Returns decoded claims dict if valid, None otherwise.
    """
    _ensure_initialized()
    try:
        decoded = _auth.verify_id_token(id_token)
        return decoded
    except Exception:
        return None


def get_or_create_user_profile(uid: str, email: str = "", name: str = ""):
    """
    Get or create a user profile document in Firestore (e.g. users/{uid}).
    Returns profile dict with at least uid, email, name, currency.
    """
    db = get_db()
    users_ref = db.collection("users")
    doc_ref = users_ref.document(uid)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return {
            "uid": uid,
            "email": data.get("email", email),
            "name": data.get("name", name),
            "currency": data.get("currency", "USD"),
        }
    profile = {
        "uid": uid,
        "email": email or "",
        "name": name or "",
        "currency": "USD",
    }
    doc_ref.set(profile)
    return profile
