"""Who can see what in the operations portal.

Roles are Django groups, so they also show up in the Django admin. A user's role is the
first matching group; superusers are always managers. Staff accounts with no group fall
back to Front desk (the safest role that can still run a shift).
"""
MANAGER = "Manager"
FRONT_DESK = "Front desk"
FINANCE = "Finance"
HOUSEKEEPING = "Housekeeping"

ALL_SECTIONS = {
    "today", "front", "payments", "till", "finance", "reports", "property", "maintenance",
    "housekeeping", "staff", "logbook",
}

ROLES = {
    MANAGER: {
        "sections": ALL_SECTIONS,
        "home": "dashboard:home",
        "summary": "Everything, including staff accounts, pricing and the property profile.",
        "icon": "key",
    },
    FRONT_DESK: {
        "sections": {"today", "front", "payments", "till", "housekeeping", "maintenance"},
        "home": "dashboard:home",
        "summary": "Bookings, check-in/out, guests, taking payments and closing their own till.",
        "icon": "person-badge",
    },
    FINANCE: {
        "sections": {"today", "payments", "till", "finance", "reports", "logbook"},
        "home": "dashboard:finance",
        "summary": "Payments, expenses, profit & loss, till reviews, reports and the logbook.",
        "icon": "calculator",
    },
    HOUSEKEEPING: {
        "sections": {"housekeeping", "maintenance"},
        "home": "dashboard:housekeeping",
        "summary": "The housekeeping board and maintenance tickets — works well on a phone.",
        "icon": "stars",
    },
}
ROLE_NAMES = list(ROLES)


def ensure_groups():
    from django.contrib.auth.models import Group

    for name in ROLE_NAMES:
        Group.objects.get_or_create(name=name)


def user_role(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return None
    if user.is_superuser:
        return MANAGER
    cached = getattr(user, "_ks_role", None)
    if cached:
        return cached
    names = set(user.groups.values_list("name", flat=True))
    role = next((r for r in ROLE_NAMES if r in names), FRONT_DESK)
    user._ks_role = role
    return role


def sections_for(user):
    role = user_role(user)
    return ROLES[role]["sections"] if role else set()


def can(user, section):
    return section in sections_for(user)


def home_url_name(user):
    role = user_role(user)
    return ROLES[role]["home"] if role else "stays:home"


def set_role(user, role):
    from django.contrib.auth.models import Group

    ensure_groups()
    user.groups.remove(*Group.objects.filter(name__in=ROLE_NAMES))
    user.groups.add(Group.objects.get(name=role))
    user._ks_role = role
