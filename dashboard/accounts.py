"""Sign-in portal, personal account, staff management, logbook and the Ctrl+K search."""
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from .roles import FRONT_DESK, ROLE_NAMES, ROLES, can, ensure_groups, home_url_name, set_role, user_role
from .views import StaffMixin

PASSWORD_WORDS = ["baobab", "kora", "mango", "river", "kunda", "bantaba", "harmattan", "atlantic", "palm", "cashew", "sunset", "tide"]


def temp_password():
    """Readable one-time password, e.g. kora-mango-4821."""
    return f"{secrets.choice(PASSWORD_WORDS)}-{secrets.choice(PASSWORD_WORDS)}-{secrets.randbelow(9000) + 1000}"


def _key_rack():
    """Apartment keys for the sign-in screen: a key on its hook means the unit is free tonight."""
    from stays.models import Apartment
    from stays.services import occupied_apartment_ids

    busy = occupied_apartment_ids(timezone.localdate())
    return [{"number": a.number, "accent": a.accent, "free": a.id not in busy} for a in Apartment.objects.exclude(status=Apartment.INACTIVE)]


class PortalLoginView(View):
    template = "registration/login.html"

    def _lock_key(self, request, username):
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
        return f"login-fail:{username.lower()}:{ip}"

    def _render(self, request, **extra):
        ctx = {"keys": _key_rack(), "next": request.GET.get("next") or request.POST.get("next", ""), **extra}
        ctx["free_tonight"] = sum(1 for k in ctx["keys"] if k["free"])
        return render(request, self.template, ctx)

    def get(self, request):
        if request.user.is_authenticated and request.user.is_staff:
            return redirect(home_url_name(request.user))
        return self._render(request)

    def post(self, request):
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        key = self._lock_key(request, identifier)
        fails = cache.get(key, 0)
        if fails >= settings.LOGIN_MAX_ATTEMPTS:
            return self._render(request, error=f"Too many attempts. Wait {settings.LOGIN_LOCKOUT_MINUTES} minutes, or ask a manager to reset your password.", username=identifier)

        User = get_user_model()
        username = identifier
        if "@" in identifier:  # sign in with email too
            match = User.objects.filter(email__iexact=identifier, is_active=True).first()
            username = match.get_username() if match else identifier
        user = authenticate(request, username=username, password=password)

        if user is None or not user.is_staff:
            fails += 1
            cache.set(key, fails, settings.LOGIN_LOCKOUT_MINUTES * 60)
            left = settings.LOGIN_MAX_ATTEMPTS - fails
            msg = "That username and password don't match."
            if user is not None:
                msg = "This account isn't set up for the staff portal. Ask a manager."
            elif 0 < left <= 2:
                msg += f" {left} attempt{'s' if left != 1 else ''} left before a short lock."
            return self._render(request, error=msg, username=identifier)

        cache.delete(key)
        last = user.last_login
        login(request, user)
        if not request.POST.get("remember"):
            request.session.set_expiry(0)  # ends when the browser closes
        if last:
            messages.info(request, f"Welcome back, {user.first_name or user.get_username()}. Last signed in {timezone.localtime(last):%a %d %b, %H:%M}.")
        else:
            messages.success(request, f"Welcome, {user.first_name or user.get_username()}! Please set your own password under My account.")
        nxt = request.POST.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(nxt)
        return redirect(home_url_name(user))


class AccountView(StaffMixin, View):
    """Any staff member: their details and password."""

    def test_func(self):
        return self.request.user.is_staff

    def get(self, request):
        from stays.models import ActivityLog

        return render(request, "dashboard/account.html", {
            "role": user_role(request.user), "role_info": ROLES[user_role(request.user)],
            "recent": ActivityLog.objects.filter(user=request.user, category="auth")[:6],
        })

    def post(self, request):
        u = request.user
        p = request.POST
        if p.get("action") == "profile":
            u.first_name = p.get("first_name", "").strip()[:150]
            u.last_name = p.get("last_name", "").strip()[:150]
            u.email = p.get("email", "").strip()[:254]
            u.save(update_fields=["first_name", "last_name", "email"])
            messages.success(request, "Details saved.")
        elif p.get("action") == "password":
            if not u.check_password(p.get("old_password", "")):
                messages.error(request, "Your current password isn't right.")
            elif p.get("new_password") != p.get("new_password2"):
                messages.error(request, "The two new passwords don't match.")
            else:
                try:
                    validate_password(p.get("new_password", ""), u)
                except ValidationError as exc:
                    for e in exc.messages:
                        messages.error(request, e)
                else:
                    u.set_password(p["new_password"])
                    u.save()
                    update_session_auth_hash(request, u)
                    messages.success(request, "Password changed. Use it next time you sign in.")
        return redirect("dashboard:account")


class StaffView(StaffMixin, View):
    section = "staff"

    def get(self, request):
        ensure_groups()
        User = get_user_model()
        people = User.objects.filter(is_staff=True).prefetch_related("groups").order_by("-is_active", "first_name", "username")
        rows = [{"u": u, "role": user_role(u) if u.is_active else (user_role(u) or FRONT_DESK)} for u in people]
        return render(request, "dashboard/staff.html", {
            "rows": rows, "roles": ROLES, "role_names": ROLE_NAMES,
            "new_password": request.session.pop("ks_new_password", None),
        })

    def post(self, request):
        from stays.signals import log

        User = get_user_model()
        p = request.POST
        action = p.get("action")
        if action == "create":
            username = p.get("username", "").strip().lower()
            role = p.get("role") if p.get("role") in ROLES else FRONT_DESK
            if not username or User.objects.filter(username__iexact=username).exists():
                messages.error(request, "Choose a username that isn't taken.")
                return redirect("dashboard:staff")
            pw = temp_password()
            u = User.objects.create_user(
                username=username, password=pw, email=p.get("email", "").strip(), first_name=p.get("first_name", "").strip()[:150],
                last_name=p.get("last_name", "").strip()[:150], is_staff=True,
            )
            set_role(u, role)
            request.session["ks_new_password"] = {"username": username, "password": pw, "name": u.get_full_name() or username}
            log("staff", f"Created staff account {username} as {role}", reverse("dashboard:staff"))
            return redirect("dashboard:staff")

        u = get_object_or_404(User, pk=p.get("user"), is_staff=True)
        if u == request.user and action in ("deactivate", "role"):
            messages.error(request, "You can't change your own role or switch off your own account.")
            return redirect("dashboard:staff")
        if u.is_superuser and not request.user.is_superuser:
            messages.error(request, "Only a superuser can change another superuser.")
            return redirect("dashboard:staff")
        if action == "role" and p.get("role") in ROLES:
            set_role(u, p["role"])
            log("staff", f"Changed {u.get_username()}'s role to {p['role']}", reverse("dashboard:staff"))
            messages.success(request, f"{u.get_full_name() or u.get_username()} is now {p['role']}.")
        elif action == "reset":
            pw = temp_password()
            u.set_password(pw)
            u.save()
            request.session["ks_new_password"] = {"username": u.get_username(), "password": pw, "name": u.get_full_name() or u.get_username()}
            log("staff", f"Reset the password for {u.get_username()}", reverse("dashboard:staff"))
        elif action in ("deactivate", "activate"):
            u.is_active = action == "activate"
            u.save(update_fields=["is_active"])
            log("staff", f"{'Re-activated' if u.is_active else 'Switched off'} {u.get_username()}'s account", reverse("dashboard:staff"))
            messages.success(request, f"{u.get_username()} can {'now' if u.is_active else 'no longer'} sign in.")
        return redirect("dashboard:staff")


class LogbookView(StaffMixin, View):
    section = "logbook"

    def get(self, request):
        from stays.models import ActivityLog

        qs = ActivityLog.objects.select_related("user")
        cat, who, q = request.GET.get("category", ""), request.GET.get("user", ""), request.GET.get("q", "").strip()
        if cat:
            qs = qs.filter(category=cat)
        if who:
            qs = qs.filter(user_id=who)
        if q:
            qs = qs.filter(summary__icontains=q)
        page = Paginator(qs, 40).get_page(request.GET.get("page"))
        days = []
        for entry in page:
            d = timezone.localtime(entry.created_at).date()
            if not days or days[-1]["day"] != d:
                days.append({"day": d, "entries": []})
            days[-1]["entries"].append(entry)
        return render(request, "dashboard/logbook.html", {
            "page": page, "days": days, "categories": ActivityLog.CATEGORY_CHOICES, "f": request.GET,
            "people": get_user_model().objects.filter(is_staff=True).order_by("username"),
        })


class SearchView(StaffMixin, View):
    """JSON for the Ctrl+K palette: pages the user can open plus matching bookings and guests."""

    def test_func(self):
        return self.request.user.is_staff

    PAGES = [
        ("Today", "dashboard:home", "today", "grid-1x2"),
        ("Occupancy chart", "dashboard:tape", "front", "calendar3-range"),
        ("Bookings", "dashboard:bookings", "front", "journal-bookmark"),
        ("New booking", "dashboard:booking_new", "front", "plus-circle"),
        ("Guests", "dashboard:guests", "front", "people"),
        ("Messages", "dashboard:messages", "front", "whatsapp"),
        ("Payments", "dashboard:payments", "payments", "cash-stack"),
        ("Close the till", "dashboard:till", "till", "safe"),
        ("Finance overview", "dashboard:finance", "finance", "bank"),
        ("Expenses", "dashboard:expenses", "finance", "receipt-cutoff"),
        ("Reports", "dashboard:reports", "reports", "graph-up-arrow"),
        ("Housekeeping board", "dashboard:housekeeping", "housekeeping", "stars"),
        ("Maintenance", "dashboard:maintenance", "maintenance", "tools"),
        ("Apartments & photos", "dashboard:apartments", "property", "building"),
        ("Rates & pricing", "dashboard:rates", "property", "tags"),
        ("Property profile", "dashboard:property", "property", "info-circle"),
        ("Staff & roles", "dashboard:staff", "staff", "person-gear"),
        ("Logbook", "dashboard:logbook", "logbook", "journal-text"),
        ("My account", "dashboard:account", None, "person-circle"),
    ]

    def get(self, request):
        from stays.models import Booking, Guest

        q = request.GET.get("q", "").strip()
        user = request.user
        results = [
            {"label": label, "url": reverse(name), "icon": icon, "kind": "Page"}
            for label, name, section, icon in self.PAGES
            if (section is None or can(user, section)) and (not q or q.lower() in label.lower())
        ][:8]
        if len(q) >= 2 and can(user, "front"):
            for b in Booking.objects.select_related("guest", "apartment").filter(
                Q(reference__icontains=q) | Q(guest__full_name__icontains=q) | Q(guest__phone__icontains=q)
            ).order_by("-check_in")[:6]:
                results.append({
                    "label": f"{b.reference} · {b.guest.full_name}", "url": reverse("dashboard:booking", args=[b.pk]),
                    "icon": "journal-bookmark", "kind": f"Apt {b.apartment.number} · {b.check_in:%d %b} · {b.get_status_display()}",
                })
            for g in Guest.objects.filter(Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))[:4]:
                results.append({"label": g.full_name, "url": reverse("dashboard:guest", args=[g.pk]), "icon": "person", "kind": g.phone})
        return JsonResponse({"results": results})
