def portal(request):
    """Role, visible sections and sidebar badge counts — only computed inside the portal."""
    if not request.path.startswith("/dashboard/"):
        return {}
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return {}

    from stays.models import Apartment, Payment

    from .roles import ROLES, sections_for, user_role

    role = user_role(user)
    sections = sections_for(user)
    badges = {}
    if "payments" in sections:
        badges["payments"] = Payment.objects.filter(status=Payment.PENDING).count()
    if "housekeeping" in sections:
        badges["housekeeping"] = Apartment.objects.exclude(status=Apartment.INACTIVE).filter(
            housekeeping__in=[Apartment.HK_DIRTY, Apartment.HK_CLEANING]
        ).count()
    return {
        "portal": {
            "role": role,
            "role_icon": ROLES[role]["icon"],
            "sections": sections,
            "badges": badges,
            "display_name": user.get_full_name() or user.get_username(),
            "initials": "".join(p[0] for p in (user.get_full_name() or user.get_username()).split()[:2]).upper(),
        }
    }
