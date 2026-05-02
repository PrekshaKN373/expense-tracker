"""
FirebaseAuthMiddleware: protect all routes except /auth/, /static/, and /admin/.
Redirect to /auth/login/ if the request has no valid session (uid).
"""
from django.shortcuts import redirect


class FirebaseAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/auth/") or path.startswith("/static/") or path.startswith("/admin/"):
            return self.get_response(request)
        if not request.session.get("uid"):
            return redirect("/auth/login/")
        return self.get_response(request)
