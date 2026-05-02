import csv
import json
import calendar
from collections import defaultdict
from datetime import datetime, date, timedelta

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages

from firebase_admin import firestore
from .firebase import verify_token, get_or_create_user_profile, get_db


def login_view(request):
    return render(request, "auth/login.html")


def register_view(request):
    return render(request, "auth/register.html")


@require_http_methods(["POST"])
@csrf_exempt
def verify_token_view(request):
    """
    Expects POST body with Firebase ID token (e.g. token=... or JSON { "token": "..." }).
    Verifies with Firebase Admin, creates Django session (uid, email, name, currency).
    Returns JSON response.
    """
    token = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        import json
        try:
            data = json.loads(request.body)
            token = data.get("token")
        except Exception:
            pass
    if not token and request.POST:
        token = request.POST.get("token")
    if not token:
        return JsonResponse({"success": False, "error": "Missing token"}, status=400)
    decoded = verify_token(token)
    if not decoded:
        return JsonResponse({"success": False, "error": "Invalid token"}, status=401)
    uid = decoded.get("uid")
    email = decoded.get("email", "")
    name = decoded.get("name") or ""
    if not isinstance(name, str):
        name = ""
    profile = get_or_create_user_profile(uid=uid, email=email, name=name)
    request.session["uid"] = profile["uid"]
    request.session["email"] = profile["email"]
    request.session["name"] = profile["name"]
    request.session["currency"] = profile["currency"]
    # Keep Firestore profile doc in sync for Settings page.
    uid = profile["uid"]
    db = get_db()
    db.collection("users").document(uid).collection("profile").document("main").set({
        "name": profile["name"],
        "email": profile["email"],
        "currency": profile["currency"],
    }, merge=True)
    return JsonResponse({
        "success": True,
        "uid": profile["uid"],
        "email": profile["email"],
        "name": profile["name"],
        "currency": profile["currency"],
    })


def logout_view(request):
    request.session.flush()
    return redirect("/auth/login/")


def dashboard_view(request):
    if not request.session.get("uid"):
        return redirect("/auth/login/")
    uid = request.session["uid"]
    currency = request.session.get("currency", "USD")
    db = get_db()
    txns_ref = db.collection("users").document(uid).collection("transactions")
    query = txns_ref.order_by("date", direction=firestore.Query.DESCENDING)
    docs = query.stream()
    transactions = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        _normalize_txn_date(data)
        transactions.append(data)
    total_income = sum(float(t.get("amount", 0) or 0) for t in transactions if t.get("type") == "income")
    total_expenses = sum(float(t.get("amount", 0) or 0) for t in transactions if t.get("type") == "expense")
    balance = total_income - total_expenses
    recent_transactions = transactions[:5]
    expenses_by_category = defaultdict(float)
    for t in transactions:
        if t.get("type") == "expense":
            cat = t.get("category") or "Other"
            expenses_by_category[cat] += float(t.get("amount", 0) or 0)
    pie_data = [{"label": k, "value": round(v, 2)} for k, v in sorted(expenses_by_category.items(), key=lambda x: -x[1])]
    monthly = defaultdict(lambda: {"income": 0.0, "expenses": 0.0})
    for t in transactions:
        date_str = t.get("date") or ""
        if len(date_str) >= 7:
            month_key = date_str[:7]
            amount = float(t.get("amount", 0) or 0)
            if t.get("type") == "income":
                monthly[month_key]["income"] += amount
            else:
                monthly[month_key]["expenses"] += amount
    sorted_months = sorted(monthly.keys(), reverse=True)[:12]
    bar_data = []
    for m in reversed(sorted_months):
        try:
            dt = datetime.strptime(m, "%Y-%m")
            label = dt.strftime("%b %Y")
        except ValueError:
            label = m
        bar_data.append({
            "month": label,
            "income": round(monthly[m]["income"], 2),
            "expenses": round(monthly[m]["expenses"], 2),
        })
    currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
    currency_symbol = currency_symbols.get(currency, currency + " ")
    context = {
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "balance": round(balance, 2),
        "recent_transactions": recent_transactions,
        "expenses_by_category": pie_data,
        "monthly_data": bar_data,
        "currency": currency,
        "currency_symbol": currency_symbol,
        "has_transactions": len(transactions) > 0,
    }
    context["expenses_by_category_json"] = json.dumps(pie_data)
    context["monthly_data_json"] = json.dumps(bar_data)

    # Upcoming recurring (next 7 days)
    today = date.today()
    horizon = today + timedelta(days=7)
    upcoming = []
    rec_ref = db.collection("users").document(uid).collection("recurring")
    for doc in rec_ref.stream():
        r = doc.to_dict()
        next_due = _parse_ymd(r.get("next_due") or "")
        if not next_due:
            continue
        if today <= next_due <= horizon:
            days_left = (next_due - today).days
            upcoming.append({
                "id": doc.id,
                "name": r.get("name") or "Recurring",
                "amount": float(r.get("amount", 0) or 0),
                "due": _format_ymd(next_due),
                "days_left": days_left,
            })
    upcoming.sort(key=lambda x: x["due"])
    context["upcoming_bills"] = upcoming[:3]

    return render(request, "tracker/dashboard.html", context)


def _require_uid(view_func):
    """Redirect to login if request.session has no uid."""
    def wrapper(request, *args, **kwargs):
        if not request.session.get("uid"):
            return redirect("/auth/login/")
        return view_func(request, *args, **kwargs)
    return wrapper


def _normalize_txn_date(data):
    """Ensure data['date'] is a YYYY-MM-DD string for template."""
    d = data.get("date")
    if d is not None and hasattr(d, "strftime"):
        data["date"] = d.strftime("%Y-%m-%d")
    elif d is not None and hasattr(d, "isoformat"):
        data["date"] = str(d)[:10]


@_require_uid
def list_transactions(request):
    uid = request.session["uid"]
    db = get_db()
    txns_ref = db.collection("users").document(uid).collection("transactions")
    filter_type = request.GET.get("type", "").strip().lower()
    query = txns_ref.order_by("date", direction=firestore.Query.DESCENDING)
    docs = query.stream()
    transactions = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        _normalize_txn_date(data)
        if filter_type in ("income", "expense") and data.get("type") != filter_type:
            continue
        transactions.append(data)
    return render(request, "tracker/transactions.html", {"transactions": transactions, "filter_type": filter_type or "all"})


@_require_uid
def add_transaction(request):
    uid = request.session["uid"]
    accounts = _get_accounts(uid)
    if request.method == "GET":
        return render(request, "tracker/add_transaction.html", {"transaction": None, "accounts": accounts})
    amount = request.POST.get("amount", "").strip()
    txn_type = request.POST.get("type", "expense").strip().lower()
    category = request.POST.get("category", "Other").strip()
    note = request.POST.get("note", "").strip()
    date_str = request.POST.get("date", "").strip()
    payment_method = request.POST.get("payment_method", "Cash").strip()
    account = (request.POST.get("account") or "").strip() or (accounts[0]["name"] if accounts else "")
    if not amount or not date_str:
        messages.error(request, "Amount and date are required.")
        return render(request, "tracker/add_transaction.html", {"transaction": None, "accounts": accounts})
    try:
        amount_val = float(amount)
    except ValueError:
        messages.error(request, "Invalid amount.")
        return render(request, "tracker/add_transaction.html", {"transaction": None, "accounts": accounts})
    if txn_type not in ("income", "expense"):
        txn_type = "expense"
    db = get_db()
    txns_ref = db.collection("users").document(uid).collection("transactions")
    txns_ref.add({
        "amount": amount_val,
        "type": txn_type,
        "category": category,
        "note": note,
        "date": date_str,
        "payment_method": payment_method,
        "account": account,
        "createdAt": datetime.utcnow(),
    })
    messages.success(request, "Transaction added successfully.")
    if txn_type == "expense" and len(date_str) >= 7:
        try:
            month = int(date_str[5:7])
            year = int(date_str[:4])
        except (ValueError, IndexError):
            month = datetime.now().month
            year = datetime.now().year
        spent = _get_spent_by_category_month(uid, month, year).get(category, 0)
        budgets_ref = db.collection("users").document(uid).collection("budgets")
        for doc in budgets_ref.stream():
            b = doc.to_dict()
            if (b.get("category") or "Other") != category:
                continue
            if int(b.get("month", 1)) != month or int(b.get("year", 0)) != year:
                continue
            limit = float(b.get("limit", 0) or 0)
            if limit <= 0:
                continue
            if spent >= limit:
                messages.error(request, f"Budget exceeded for {category}: spent {spent:.2f} of {limit:.2f}.")
                break
            elif spent >= limit * 0.8:
                messages.warning(request, f"Budget warning for {category}: {spent:.2f} of {limit:.2f} ({(spent/limit)*100:.0f}% used).")
                break
    return redirect("/transactions/")


@_require_uid
def edit_transaction(request, txn_id):
    uid = request.session["uid"]
    accounts = _get_accounts(uid)
    db = get_db()
    doc_ref = db.collection("users").document(uid).collection("transactions").document(txn_id)
    doc = doc_ref.get()
    if not doc.exists:
        messages.error(request, "Transaction not found.")
        return redirect("/transactions/")
    if request.method == "GET":
        data = doc.to_dict()
        data["id"] = doc.id
        _normalize_txn_date(data)
        return render(request, "tracker/edit_transaction.html", {"transaction": data, "accounts": accounts})
    amount = request.POST.get("amount", "").strip()
    txn_type = request.POST.get("type", "expense").strip().lower()
    category = request.POST.get("category", "Other").strip()
    note = request.POST.get("note", "").strip()
    date_str = request.POST.get("date", "").strip()
    payment_method = request.POST.get("payment_method", "Cash").strip()
    account = (request.POST.get("account") or "").strip() or (accounts[0]["name"] if accounts else "")
    if not amount or not date_str:
        messages.error(request, "Amount and date are required.")
        data = doc.to_dict()
        data["id"] = doc.id
        _normalize_txn_date(data)
        return render(request, "tracker/edit_transaction.html", {"transaction": data, "accounts": accounts})
    try:
        amount_val = float(amount)
    except ValueError:
        messages.error(request, "Invalid amount.")
        data = doc.to_dict()
        data["id"] = doc.id
        _normalize_txn_date(data)
        return render(request, "tracker/edit_transaction.html", {"transaction": data, "accounts": accounts})
    if txn_type not in ("income", "expense"):
        txn_type = "expense"
    doc_ref.update({
        "amount": amount_val,
        "type": txn_type,
        "category": category,
        "note": note,
        "date": date_str,
        "payment_method": payment_method,
        "account": account,
    })
    messages.success(request, "Transaction updated successfully.")
    return redirect("/transactions/")


@_require_uid
def delete_transaction(request, txn_id):
    uid = request.session["uid"]
    db = get_db()
    doc_ref = db.collection("users").document(uid).collection("transactions").document(txn_id)
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.delete()
        messages.success(request, "Transaction deleted successfully.")
    else:
        messages.error(request, "Transaction not found.")
    return redirect("/transactions/")


DEFAULT_CATEGORIES = [
    {"name": "Food", "icon": "🍔", "color": "#f6c23e", "isCustom": False},
    {"name": "Transport", "icon": "🚗", "color": "#4e73df", "isCustom": False},
    {"name": "Shopping", "icon": "🛍️", "color": "#e74a3b", "isCustom": False},
    {"name": "Bills", "icon": "💡", "color": "#36b9cc", "isCustom": False},
    {"name": "Health", "icon": "🏥", "color": "#1cc88a", "isCustom": False},
    {"name": "Entertainment", "icon": "🎬", "color": "#858796", "isCustom": False},
    {"name": "Salary", "icon": "💰", "color": "#2e59d9", "isCustom": False},
    {"name": "Other", "icon": "📦", "color": "#5a5c69", "isCustom": False},
]


@_require_uid
def list_categories(request):
    uid = request.session["uid"]
    db = get_db()
    cats_ref = db.collection("users").document(uid).collection("categories")
    docs = list(cats_ref.stream())
    if not docs:
        for cat in DEFAULT_CATEGORIES:
            cats_ref.add(cat)
        docs = list(cats_ref.stream())
    categories = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        data.setdefault("isCustom", False)
        categories.append(data)
    return render(request, "tracker/categories.html", {"categories": categories})


@_require_uid
def add_category(request):
    if request.method == "GET":
        return render(request, "tracker/add_category.html")
    uid = request.session["uid"]
    name = (request.POST.get("name") or "").strip()
    icon = (request.POST.get("icon") or "").strip()
    color = (request.POST.get("color") or "#6c757d").strip()
    if not name:
        messages.error(request, "Name is required.")
        return render(request, "tracker/add_category.html")
    db = get_db()
    cats_ref = db.collection("users").document(uid).collection("categories")
    cats_ref.add({
        "name": name,
        "icon": icon or "📦",
        "color": color,
        "isCustom": True,
    })
    messages.success(request, "Category added successfully.")
    return redirect("/categories/")


@_require_uid
def delete_category(request, cat_id):
    uid = request.session["uid"]
    db = get_db()
    doc_ref = db.collection("users").document(uid).collection("categories").document(cat_id)
    doc = doc_ref.get()
    if not doc.exists:
        messages.error(request, "Category not found.")
        return redirect("/categories/")
    data = doc.to_dict()
    if not data.get("isCustom", False):
        messages.error(request, "Default categories cannot be deleted.")
        return redirect("/categories/")
    doc_ref.delete()
    messages.success(request, "Category deleted successfully.")
    return redirect("/categories/")


def _get_categories(uid):
    """Return list of category dicts (id, name, icon, color) for user."""
    db = get_db()
    cats_ref = db.collection("users").document(uid).collection("categories")
    docs = list(cats_ref.stream())
    if not docs:
        for cat in DEFAULT_CATEGORIES:
            cats_ref.add(cat)
        docs = list(cats_ref.stream())
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]


def _get_spent_by_category_month(uid, month, year):
    """Return dict category_name -> total amount spent (expenses only) for given month/year."""
    db = get_db()
    month_prefix = f"{year}-{month:02d}"
    txns_ref = db.collection("users").document(uid).collection("transactions")
    docs = txns_ref.stream()
    spent = defaultdict(float)
    for doc in docs:
        data = doc.to_dict()
        if data.get("type") != "expense":
            continue
        date_str = (data.get("date") or "")[:7]
        if date_str == month_prefix:
            cat = data.get("category") or "Other"
            spent[cat] += float(data.get("amount", 0) or 0)
    return dict(spent)


@_require_uid
def list_budgets(request):
    uid = request.session["uid"]
    currency = request.session.get("currency", "USD")
    currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
    currency_symbol = currency_symbols.get(currency, currency + " ")
    db = get_db()
    categories_by_name = {c["name"]: c for c in _get_categories(uid)}
    budgets_ref = db.collection("users").document(uid).collection("budgets")
    docs = list(budgets_ref.stream())
    budgets = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        limit = float(data.get("limit", 0) or 0)
        month = int(data.get("month", 1))
        year = int(data.get("year", datetime.now().year))
        category_name = data.get("category") or "Other"
        spent = _get_spent_by_category_month(uid, month, year).get(category_name, 0)
        data["spent"] = round(spent, 2)
        data["limit"] = limit
        data["month"] = month
        data["year"] = year
        data["category_name"] = category_name
        cat_info = categories_by_name.get(category_name, {})
        data["icon"] = cat_info.get("icon", "📦")
        data["color"] = cat_info.get("color", "#6c757d")
        if limit <= 0:
            pct = 0
        else:
            pct = (spent / limit) * 100
        data["percentage"] = round(pct, 1)
        if pct >= 100:
            data["status"] = "exceeded"
        elif pct >= 80:
            data["status"] = "warning"
        else:
            data["status"] = "safe"
        data["progress_width"] = min(pct, 100)
        try:
            data["month_label"] = datetime(year, month, 1).strftime("%B %Y")
        except ValueError:
            data["month_label"] = f"{month}/{year}"
        budgets.append(data)
    return render(request, "tracker/budgets.html", {
        "budgets": budgets,
        "currency_symbol": currency_symbol,
    })


@_require_uid
def add_budget(request):
    uid = request.session["uid"]
    categories = _get_categories(uid)
    if request.method == "GET":
        return render(request, "tracker/add_budget.html", {"categories": categories, "current_year": datetime.now().year})
    category = (request.POST.get("category") or "").strip() or "Other"
    limit_str = (request.POST.get("limit") or "").strip()
    month_str = (request.POST.get("month") or "").strip()
    year_str = (request.POST.get("year") or "").strip()
    if not limit_str:
        messages.error(request, "Budget limit is required.")
        return render(request, "tracker/add_budget.html", {"categories": categories, "current_year": datetime.now().year})
    try:
        limit_val = float(limit_str)
    except ValueError:
        messages.error(request, "Invalid limit amount.")
        return render(request, "tracker/add_budget.html", {"categories": categories, "current_year": datetime.now().year})
    now = datetime.now()
    try:
        month = int(month_str) if month_str else now.month
        year = int(year_str) if year_str else now.year
    except ValueError:
        month, year = now.month, now.year
    month = max(1, min(12, month))
    db = get_db()
    budgets_ref = db.collection("users").document(uid).collection("budgets")
    budgets_ref.add({
        "category": category,
        "limit": limit_val,
        "month": month,
        "year": year,
    })
    messages.success(request, "Budget added successfully.")
    return redirect("/budgets/")


@_require_uid
def delete_budget(request, budget_id):
    uid = request.session["uid"]
    db = get_db()
    doc_ref = db.collection("users").document(uid).collection("budgets").document(budget_id)
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.delete()
        messages.success(request, "Budget deleted successfully.")
    else:
        messages.error(request, "Budget not found.")
    return redirect("/budgets/")


DEFAULT_ACCOUNTS = [
    {"name": "Cash", "type": "Cash", "balance": 0.0, "icon": "💵", "color": "#28a745"},
    {"name": "Bank Account", "type": "Bank Account", "balance": 0.0, "icon": "🏦", "color": "#17a2b8"},
    {"name": "Credit Card", "type": "Credit Card", "balance": 0.0, "icon": "💳", "color": "#6f42c1"},
    {"name": "UPI", "type": "UPI", "balance": 0.0, "icon": "📱", "color": "#fd7e14"},
]


def _get_accounts(uid):
    """Return list of account dicts for user; seed defaults if none exist."""
    db = get_db()
    acc_ref = db.collection("users").document(uid).collection("accounts")
    docs = list(acc_ref.stream())
    if not docs:
        for acc in DEFAULT_ACCOUNTS:
            acc_ref.add(acc)
        docs = list(acc_ref.stream())
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]


@_require_uid
def list_accounts(request):
    uid = request.session["uid"]
    currency = request.session.get("currency", "USD")
    currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
    currency_symbol = currency_symbols.get(currency, currency + " ")
    accounts = _get_accounts(uid)
    for a in accounts:
        a["balance"] = float(a.get("balance", 0) or 0)
    total_balance = sum(a["balance"] for a in accounts)
    return render(request, "tracker/accounts.html", {
        "accounts": accounts,
        "total_balance": round(total_balance, 2),
        "currency_symbol": currency_symbol,
    })


@_require_uid
def add_account(request):
    if request.method == "GET":
        return render(request, "tracker/add_account.html")
    uid = request.session["uid"]
    name = (request.POST.get("name") or "").strip()
    acc_type = (request.POST.get("type") or "Cash").strip()
    balance_str = (request.POST.get("balance") or "0").strip()
    icon = (request.POST.get("icon") or "💵").strip()
    color = (request.POST.get("color") or "#6c757d").strip()
    if not name:
        messages.error(request, "Name is required.")
        return render(request, "tracker/add_account.html")
    try:
        balance_val = float(balance_str)
    except ValueError:
        balance_val = 0.0
    db = get_db()
    acc_ref = db.collection("users").document(uid).collection("accounts")
    acc_ref.add({
        "name": name,
        "type": acc_type,
        "balance": balance_val,
        "icon": icon or "💵",
        "color": color,
    })
    messages.success(request, "Account added successfully.")
    return redirect("/accounts/")


@_require_uid
def edit_account(request, account_id):
    uid = request.session["uid"]
    db = get_db()
    doc_ref = db.collection("users").document(uid).collection("accounts").document(account_id)
    doc = doc_ref.get()
    if not doc.exists:
        messages.error(request, "Account not found.")
        return redirect("/accounts/")
    if request.method == "GET":
        data = doc.to_dict()
        data["id"] = doc.id
        return render(request, "tracker/edit_account.html", {"account": data})
    name = (request.POST.get("name") or "").strip()
    acc_type = (request.POST.get("type") or "Cash").strip()
    balance_str = (request.POST.get("balance") or "0").strip()
    icon = (request.POST.get("icon") or "").strip()
    color = (request.POST.get("color") or "#6c757d").strip()
    if not name:
        messages.error(request, "Name is required.")
        data = doc.to_dict()
        data["id"] = doc.id
        return render(request, "tracker/edit_account.html", {"account": data})
    try:
        balance_val = float(balance_str)
    except ValueError:
        balance_val = 0.0
    doc_ref.update({
        "name": name,
        "type": acc_type,
        "balance": balance_val,
        "icon": icon or "💵",
        "color": color,
    })
    messages.success(request, "Account updated successfully.")
    return redirect("/accounts/")


@_require_uid
def delete_account_entry(request, account_id):
    uid = request.session["uid"]
    db = get_db()
    doc_ref = db.collection("users").document(uid).collection("accounts").document(account_id)
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.delete()
        messages.success(request, "Account deleted successfully.")
    else:
        messages.error(request, "Account not found.")
    return redirect("/accounts/")


def _profile_doc_ref(uid):
    db = get_db()
    return db.collection("users").document(uid).collection("profile").document("main")


@_require_uid
def settings_view(request):
    uid = request.session["uid"]
    email = request.session.get("email", "")
    name = request.session.get("name", "")
    currency = request.session.get("currency", "USD")

    doc = _profile_doc_ref(uid).get()
    if doc.exists:
        p = doc.to_dict() or {}
        name = p.get("name", name)
        email = p.get("email", email)
        currency = p.get("currency", currency)
    else:
        _profile_doc_ref(uid).set({
            "name": name,
            "email": email,
            "currency": currency,
        }, merge=True)

    return render(request, "tracker/settings.html", {
        "name": name,
        "email": email,
        "currency": currency,
    })


@_require_uid
@require_http_methods(["POST"])
def update_profile(request):
    uid = request.session["uid"]
    current_email = request.session.get("email", "")
    name = (request.POST.get("name") or "").strip()
    currency = (request.POST.get("currency") or "USD").strip().upper()
    allowed_currencies = {"INR", "USD", "EUR", "GBP", "AED"}
    if currency not in allowed_currencies:
        currency = "USD"
    if not name:
        messages.error(request, "Name is required.")
        return redirect("/settings/")

    _profile_doc_ref(uid).set({
        "name": name,
        "email": current_email,
        "currency": currency,
    }, merge=True)

    request.session["name"] = name
    request.session["currency"] = currency
    messages.success(request, "Profile updated successfully.")
    return redirect("/settings/")


@_require_uid
@require_http_methods(["POST"])
def change_password(request):
    # Password update is handled client-side by Firebase SDK.
    # This endpoint is kept for frontend handshake and optional session sync.
    request.session.modified = True
    return JsonResponse({"success": True, "message": "Password updated via Firebase."})


@_require_uid
@require_http_methods(["POST"])
def clear_transactions(request):
    uid = request.session["uid"]
    confirm_text = (request.POST.get("confirm_text") or "").strip()
    if confirm_text != "CLEAR":
        messages.error(request, 'Type "CLEAR" to remove all transactions.')
        return redirect("/settings/")
    db = get_db()
    txns_ref = db.collection("users").document(uid).collection("transactions")
    for doc in txns_ref.stream():
        doc.reference.delete()
    messages.success(request, "All transactions were cleared.")
    return redirect("/settings/")


@_require_uid
@require_http_methods(["POST"])
def delete_account(request):
    uid = request.session["uid"]
    confirm_text = (request.POST.get("confirm_text") or "").strip()
    if confirm_text != "DELETE":
        messages.error(request, 'Type "DELETE" to confirm account deletion.')
        return redirect("/settings/")

    db = get_db()
    user_doc = db.collection("users").document(uid)
    subcollections = ["transactions", "categories", "budgets", "accounts", "recurring", "profile"]
    for col in subcollections:
        for doc in user_doc.collection(col).stream():
            doc.reference.delete()
    user_doc.delete()

    request.session.flush()
    messages.success(request, "Account deleted successfully.")
    return redirect("/auth/login/")


def _currency_symbol(request):
    currency = request.session.get("currency", "USD")
    currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
    return currency_symbols.get(currency, currency + " ")


def _parse_ymd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _format_ymd(d: date):
    return d.strftime("%Y-%m-%d")


def _add_months(d: date, months: int):
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    day = min(d.day, last_day)
    return date(y, m, day)


def _next_due_date(current_due: date, frequency: str):
    freq = (frequency or "").lower()
    if freq == "daily":
        return current_due + timedelta(days=1)
    if freq == "weekly":
        return current_due + timedelta(days=7)
    if freq == "monthly":
        return _add_months(current_due, 1)
    if freq == "yearly":
        return _add_months(current_due, 12)
    return current_due + timedelta(days=30)


@_require_uid
def reports_view(request):
    uid = request.session["uid"]
    currency_symbol = _currency_symbol(request)

    now = date.today()
    range_key = (request.GET.get("range") or "6m").lower()  # month, 3m, 6m, year
    if range_key in ("month", "this_month"):
        start = date(now.year, now.month, 1)
        months_count = 1
    elif range_key in ("3m", "last3", "last_3_months"):
        start = _add_months(date(now.year, now.month, 1), -2)
        months_count = 3
    elif range_key in ("year", "this_year"):
        start = date(now.year, 1, 1)
        months_count = now.month
    else:
        start = _add_months(date(now.year, now.month, 1), -5)
        months_count = 6
    end = now

    db = get_db()
    txns_ref = db.collection("users").document(uid).collection("transactions")
    docs = txns_ref.stream()

    txns = []
    for doc in docs:
        t = doc.to_dict()
        t["id"] = doc.id
        _normalize_txn_date(t)
        d = _parse_ymd(t.get("date") or "")
        if not d:
            continue
        if d < start or d > end:
            continue
        t["_date_obj"] = d
        t["amount"] = float(t.get("amount", 0) or 0)
        t["type"] = (t.get("type") or "expense").lower()
        t["category"] = t.get("category") or "Other"
        t["payment_method"] = t.get("payment_method") or "Cash"
        t["account"] = t.get("account") or ""
        txns.append(t)

    total_income = sum(t["amount"] for t in txns if t["type"] == "income")
    total_expenses = sum(t["amount"] for t in txns if t["type"] == "expense")
    balance = total_income - total_expenses

    monthly_index = []
    for i in range(months_count - 1, -1, -1):
        m_start = _add_months(date(now.year, now.month, 1), -i)
        monthly_index.append(m_start.strftime("%Y-%m"))

    monthly_map = {k: {"income": 0.0, "expenses": 0.0} for k in monthly_index}
    for t in txns:
        key = (t.get("date") or "")[:7]
        if key not in monthly_map:
            continue
        if t["type"] == "income":
            monthly_map[key]["income"] += t["amount"]
        else:
            monthly_map[key]["expenses"] += t["amount"]

    monthly_summary = []
    for key in monthly_index:
        try:
            label = datetime.strptime(key, "%Y-%m").strftime("%b %Y")
        except Exception:
            label = key
        inc = monthly_map[key]["income"]
        exp = monthly_map[key]["expenses"]
        monthly_summary.append({
            "month": label,
            "income": round(inc, 2),
            "expenses": round(exp, 2),
            "balance": round(inc - exp, 2),
        })

    category_totals = defaultdict(float)
    category_counts = defaultdict(int)
    for t in txns:
        if t["type"] != "expense":
            continue
        category_totals[t["category"]] += t["amount"]
        category_counts[t["category"]] += 1
    total_exp_for_pct = sum(category_totals.values()) or 0.0
    category_breakdown = []
    for cat, amt in sorted(category_totals.items(), key=lambda x: -x[1]):
        pct = (amt / total_exp_for_pct) * 100 if total_exp_for_pct > 0 else 0
        category_breakdown.append({
            "category": cat,
            "amount": round(amt, 2),
            "percentage": round(pct, 1),
            "transactions": category_counts[cat],
        })

    spending_by_day = defaultdict(float)
    for t in txns:
        if t["type"] == "expense":
            spending_by_day[t["date"]] += t["amount"]
    top_spending_days = [
        {"date": d, "amount": round(a, 2)}
        for d, a in sorted(spending_by_day.items(), key=lambda x: -x[1])[:5]
    ]

    pm_totals = defaultdict(float)
    for t in txns:
        if t["type"] == "expense":
            pm_totals[t["payment_method"]] += t["amount"]
    payment_breakdown = [
        {"method": m, "amount": round(a, 2)}
        for m, a in sorted(pm_totals.items(), key=lambda x: -x[1])
    ]

    biggest_expenses = [
        {
            "date": t["date"],
            "category": t["category"],
            "amount": round(t["amount"], 2),
            "note": t.get("note") or "",
            "payment_method": t["payment_method"],
            "account": t["account"],
        }
        for t in sorted([x for x in txns if x["type"] == "expense"], key=lambda x: -x["amount"])[:5]
    ]

    context = {
        "currency_symbol": currency_symbol,
        "has_transactions": len(txns) > 0,
        "range": range_key,
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "balance": round(balance, 2),
        "total_transactions": len(txns),
        "monthly_summary": monthly_summary,
        "category_breakdown": category_breakdown,
        "top_spending_days": top_spending_days,
        "payment_breakdown": payment_breakdown,
        "biggest_expenses": biggest_expenses,
        "monthly_summary_json": json.dumps(monthly_summary),
        "category_breakdown_json": json.dumps(category_breakdown),
        "payment_breakdown_json": json.dumps(payment_breakdown),
    }
    return render(request, "tracker/reports.html", context)


@_require_uid
def export_csv(request):
    uid = request.session["uid"]
    db = get_db()
    txns_ref = db.collection("users").document(uid).collection("transactions")
    docs = txns_ref.order_by("date", direction=firestore.Query.DESCENDING).stream()

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="transactions.csv"'

    writer = csv.writer(response)
    writer.writerow(["Date", "Type", "Category", "Amount", "Note", "Payment Method", "Account"])
    for doc in docs:
        t = doc.to_dict()
        _normalize_txn_date(t)
        writer.writerow([
            t.get("date") or "",
            (t.get("type") or "").title(),
            t.get("category") or "",
            t.get("amount") if t.get("amount") is not None else "",
            t.get("note") or "",
            t.get("payment_method") or "",
            t.get("account") or "",
        ])
    return response


@_require_uid
def list_recurring(request):
    uid = request.session["uid"]
    currency_symbol = _currency_symbol(request)
    today = date.today()

    db = get_db()
    rec_ref = db.collection("users").document(uid).collection("recurring")
    docs = rec_ref.stream()

    items = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        next_due_str = data.get("next_due") or ""
        due = _parse_ymd(next_due_str)
        if not due:
            continue
        days_until = (due - today).days
        if days_until <= 0:
            status = "overdue"
        elif days_until <= 3:
            status = "due_soon"
        else:
            status = "upcoming"
        data["days_until"] = days_until
        data["status"] = status
        data["amount"] = float(data.get("amount", 0) or 0)
        items.append(data)

    items.sort(key=lambda x: (x.get("next_due") or "9999-99-99"))
    return render(request, "tracker/recurring.html", {
        "recurring": items,
        "currency_symbol": currency_symbol,
    })


@_require_uid
def add_recurring(request):
    uid = request.session["uid"]
    categories = _get_categories(uid)
    if request.method == "GET":
        return render(request, "tracker/add_recurring.html", {"categories": categories})

    name = (request.POST.get("name") or "").strip()
    amount_str = (request.POST.get("amount") or "").strip()
    txn_type = (request.POST.get("type") or "expense").strip().lower()
    category = (request.POST.get("category") or "Other").strip() or "Other"
    frequency = (request.POST.get("frequency") or "monthly").strip().lower()
    start_date_str = (request.POST.get("start_date") or "").strip()
    payment_method = (request.POST.get("payment_method") or "Cash").strip()
    note = (request.POST.get("note") or "").strip()

    if not name or not amount_str:
        messages.error(request, "Name and amount are required.")
        return render(request, "tracker/add_recurring.html", {"categories": categories})
    try:
        amount_val = float(amount_str)
    except ValueError:
        messages.error(request, "Invalid amount.")
        return render(request, "tracker/add_recurring.html", {"categories": categories})
    if txn_type not in ("income", "expense"):
        txn_type = "expense"

    start_d = _parse_ymd(start_date_str) or date.today()
    next_due = _format_ymd(start_d)

    db = get_db()
    rec_ref = db.collection("users").document(uid).collection("recurring")
    rec_ref.add({
        "name": name,
        "amount": amount_val,
        "type": txn_type,
        "category": category,
        "frequency": frequency,
        "start_date": _format_ymd(start_d),
        "next_due": next_due,
        "payment_method": payment_method,
        "note": note,
        "createdAt": datetime.utcnow(),
    })
    messages.success(request, "Recurring transaction added successfully.")
    return redirect("/recurring/")


@_require_uid
def delete_recurring(request, rec_id):
    uid = request.session["uid"]
    db = get_db()
    doc_ref = db.collection("users").document(uid).collection("recurring").document(rec_id)
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.delete()
        messages.success(request, "Recurring transaction deleted successfully.")
    else:
        messages.error(request, "Recurring transaction not found.")
    return redirect("/recurring/")


@_require_uid
def process_recurring(request):
    uid = request.session["uid"]
    today = date.today()
    today_str = _format_ymd(today)

    db = get_db()
    rec_ref = db.collection("users").document(uid).collection("recurring")
    due_docs = rec_ref.where("next_due", "<=", today_str).stream()

    processed = 0
    for doc in due_docs:
        data = doc.to_dict()
        next_due_str = data.get("next_due") or ""
        due = _parse_ymd(next_due_str)
        if not due:
            continue
        freq = data.get("frequency") or "monthly"

        # Create transaction for each overdue occurrence, then advance next_due.
        while due and due <= today:
            db.collection("users").document(uid).collection("transactions").add({
                "amount": float(data.get("amount", 0) or 0),
                "type": (data.get("type") or "expense").lower(),
                "category": data.get("category") or "Other",
                "note": data.get("note") or data.get("name") or "",
                "date": _format_ymd(due),
                "payment_method": data.get("payment_method") or "Cash",
                "account": data.get("account") or "",
                "createdAt": datetime.utcnow(),
                "source": "recurring",
                "recurring_id": doc.id,
            })
            processed += 1
            due = _next_due_date(due, freq)

        if due:
            doc.reference.update({"next_due": _format_ymd(due)})

    if processed:
        messages.success(request, f"Processed {processed} due recurring transaction(s).")
    else:
        messages.info(request, "No due recurring transactions to process.")
    return redirect("/recurring/")
