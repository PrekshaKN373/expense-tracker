from django.urls import path
from django.views.generic.base import RedirectView
from . import views

app_name = "tracker"

urlpatterns = [
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("auth/login/", views.login_view, name="login"),
    path("auth/register/", views.register_view, name="register"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/verify-token/", views.verify_token_view, name="verify_token"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("transactions/", views.list_transactions, name="list_transactions"),
    path("transactions/add/", views.add_transaction, name="add_transaction"),
    path("transactions/<str:txn_id>/edit/", views.edit_transaction, name="edit_transaction"),
    path("transactions/<str:txn_id>/delete/", views.delete_transaction, name="delete_transaction"),
    path("categories/", views.list_categories, name="list_categories"),
    path("categories/add/", views.add_category, name="add_category"),
    path("categories/<str:cat_id>/delete/", views.delete_category, name="delete_category"),
    path("budgets/", views.list_budgets, name="list_budgets"),
    path("budgets/add/", views.add_budget, name="add_budget"),
    path("budgets/<str:budget_id>/delete/", views.delete_budget, name="delete_budget"),
    path("accounts/", views.list_accounts, name="list_accounts"),
    path("accounts/add/", views.add_account, name="add_account"),
    path("accounts/<str:account_id>/edit/", views.edit_account, name="edit_account"),
    path("accounts/<str:account_id>/delete/", views.delete_account_entry, name="delete_account_entry"),
    path("reports/", views.reports_view, name="reports"),
    path("reports/export/", views.export_csv, name="export_csv"),
    path("recurring/", views.list_recurring, name="list_recurring"),
    path("recurring/add/", views.add_recurring, name="add_recurring"),
    path("recurring/<str:rec_id>/delete/", views.delete_recurring, name="delete_recurring"),
    path("recurring/process/", views.process_recurring, name="process_recurring"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/update-profile/", views.update_profile, name="update_profile"),
    path("settings/change-password/", views.change_password, name="change_password"),
    path("settings/clear-transactions/", views.clear_transactions, name="clear_transactions"),
    path("settings/delete-account/", views.delete_account, name="delete_account"),
]
