"""
Firebase Admin SDK initialization and helpers.

Credentials are resolved in this order:
1. FIREBASE_CREDENTIALS_JSON env var — full service account JSON as a string
   (preferred for production / Railway deployments).
2. FIREBASE_KEY_PATH env var — path to a service account JSON file
   (defaults to serviceAccountKey.json, useful for local development).

If neither source yields valid credentials the first call to get_db() or
verify_token() will raise a RuntimeError with a clear message.
"""
import json
import os

from django.conf import settings

# Load .env when it exists (local development). In production the file won't
# be present and load_dotenv silently does nothing, so this is always safe.
from dotenv import load_dotenv
_env_file = settings.BASE_DIR / ".env"
if _env_file.is_file():
    load_dotenv(_env_file)

_db = None
_auth = None
_initialized = False


def _ensure_initialized():
    global _initialized, _db, _auth
    if _initialized:
        return
    import firebase_admin
    from firebase_admin import credentials, auth, firestore

    cred = None

    # --- Option 1: credentials supplied as a JSON string via env var ---
    credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if credentials_json:
        try:
            service_account_info = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "FIREBASE_CREDENTIALS_JSON is set but could not be parsed as JSON. "
                "Make sure the value is the raw contents of your service account key file."
            ) from exc
        cred = credentials.Certificate(service_account_info)

    # --- Option 2: fall back to a key file (local development) ---
    if cred is None:
        key_path = os.getenv("FIREBASE_KEY_PATH", "serviceAccountKey.json")
        if not os.path.isabs(key_path):
            key_path = str(settings.BASE_DIR / key_path)
        if os.path.isfile(key_path):
            cred = credentials.Certificate(key_path)

    if cred is None:
        raise RuntimeError(
            "Firebase credentials are not configured. "
            "In production, set the FIREBASE_CREDENTIALS_JSON environment variable "
            "to the contents of your service account key JSON. "
            "For local development, place serviceAccountKey.json in the project root "
            "or set FIREBASE_KEY_PATH to its location."
        )

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
