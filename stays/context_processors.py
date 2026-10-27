from django.conf import settings

from .whatsapp import link


def site(request):
    k = settings.KUNDA
    return {
        "site": {
            **k,
            "whatsapp_link": link(k["whatsapp"], f"Hello {k['name']}, I'd like to ask about an apartment."),
            "maps_embed": f"https://maps.google.com/maps?q={k['lat']},{k['lng']}&z=15&output=embed",
            "maps_link": f"https://www.google.com/maps/dir/?api=1&destination={k['lat']},{k['lng']}",
        }
    }
