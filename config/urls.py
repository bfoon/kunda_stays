from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path
from django.views.static import serve

admin.site.site_header = f"{settings.KUNDA['name']} admin"
admin.site.site_title = settings.KUNDA["name"]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", include("dashboard.urls")),
    path("", include("stays.urls")),
    # Uploaded apartment photos. For high traffic, serve /media/ from nginx instead.
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
