"""Demo data: amenities, apartments with generated photos, guests, bookings, payments."""
import os
import random
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

AMENITIES = [
    ("Fast Wi-Fi", "wifi"), ("Air conditioning", "snow"), ("Backup generator", "lightning-charge"),
    ("Smart TV", "tv"), ("Full kitchen", "cup-hot"), ("Washing machine", "basket"),
    ("Secure parking", "car-front"), ("24/7 security", "shield-check"), ("Hot water", "droplet-half"),
    ("Workspace", "laptop"), ("Balcony", "brightness-high"), ("Daily housekeeping", "stars"),
]

APARTMENTS = [
    ("101", "Mangrove Studio", "Calm ground-floor studio steps from the garden", 0, 1, 1, 2, 32, 2200, 52000, "#1F6F50"),
    ("102", "Kora Suite", "One bedroom with a proper desk and fast Wi-Fi", 0, 1, 1, 2, 45, 2800, 65000, "#0B4F5C"),
    ("201", "Atlantic View", "Two bedrooms and a balcony that catches the sea breeze", 1, 2, 2, 4, 78, 4200, 98000, "#0E6A78"),
    ("202", "Kunda Family Home", "Room for the whole family, with a full kitchen", 1, 3, 2, 6, 110, 5600, 125000, "#B8336A"),
    ("203", "Harmattan Loft", "Bright loft with high ceilings and a reading nook", 1, 1, 1, 2, 50, 3100, 70000, "#C98A00"),
    ("301", "Baobab Penthouse", "Top floor, rooftop terrace, sunset over the river", 2, 2, 2, 4, 95, 6500, 140000, "#07363F"),
    ("302", "Fajara Flat", "Simple, spotless and great value for longer stays", 2, 1, 1, 2, 40, 2000, 45000, "#56707A"),
    ("303", "Senegambia Duplex", "Split-level two bedroom near shops and restaurants", 2, 2, 1, 4, 82, 4600, 105000, "#2E9468"),
]

DESCRIPTION = (
    "{name} is a fully furnished apartment on the {floor} with {beds} bedroom{s}, reliable power and fast Wi-Fi. "
    "Linen and towels are provided, the kitchen is stocked with the basics, and our team is a WhatsApp message away.\n\n"
    "Ideal for mission travel, consultants and families visiting home. Stay 30 nights or more and the monthly rate applies automatically."
)

GUESTS = [
    ("Fatou Jallow", "+220 7712345", "Gambia"), ("Lamin Ceesay", "+220 3345678", "Gambia"),
    ("Aminata Diallo", "+221 771234567", "Senegal"), ("James Okafor", "+234 8031234567", "Nigeria"),
    ("Sarah Mitchell", "+44 7700900123", "United Kingdom"), ("Ousman Sowe", "+220 9912345", "Gambia"),
    ("Mariama Touray", "+220 2234567", "Gambia"), ("Kwame Mensah", "+233 244123456", "Ghana"),
    ("Ingrid Larsen", "+47 41234567", "Norway"), ("Ebrima Njie", "+220 6612345", "Gambia"),
]


def _photo(accent, number, scene):
    from PIL import Image, ImageDraw

    w, h = 1200, 900
    img = Image.new("RGB", (w, h), "#EEF2F0")
    d = ImageDraw.Draw(img)
    ac = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    soft = tuple(int(c + (255 - c) * .78) for c in ac)
    d.rectangle([0, 0, w, int(h * .68)], fill=soft)                     # wall
    d.rectangle([0, int(h * .68), w, h], fill=(214, 196, 168))          # floor
    for x in range(0, w, 120):
        d.line([x, int(h * .68), x - 160, h], fill=(198, 178, 148), width=3)
    # window with sky and river
    d.rounded_rectangle([720, 110, 1080, 470], 18, fill=(255, 255, 255))
    d.rectangle([740, 130, 1060, 330], fill=(160, 210, 230))
    d.rectangle([740, 330, 1060, 450], fill=(40, 120, 135))
    d.ellipse([940, 160, 1010, 230], fill=(242, 183, 5))
    d.line([900, 130, 900, 450], fill=(255, 255, 255), width=10)
    if scene == "living":
        d.rounded_rectangle([90, 470, 610, 680], 30, fill=ac)               # sofa
        d.rounded_rectangle([120, 410, 330, 520], 26, fill=tuple(min(255, c + 40) for c in ac))
        d.rounded_rectangle([360, 410, 580, 520], 26, fill=tuple(min(255, c + 40) for c in ac))
        d.rounded_rectangle([240, 720, 520, 760], 10, fill=(120, 84, 52))  # table
        d.ellipse([620, 560, 700, 640], fill=(31, 111, 80))                # plant
        d.rectangle([648, 630, 672, 700], fill=(120, 84, 52))
    elif scene == "bedroom":
        d.rounded_rectangle([140, 430, 760, 720], 24, fill=(250, 250, 248))  # bed
        d.rounded_rectangle([140, 330, 760, 450], 24, fill=ac)               # headboard
        d.rounded_rectangle([190, 400, 400, 470], 20, fill=(235, 240, 238))
        d.rounded_rectangle([480, 400, 690, 470], 20, fill=(235, 240, 238))
        d.rectangle([140, 560, 760, 720], fill=tuple(int(c * .85) for c in ac))
        d.ellipse([800, 520, 860, 580], fill=(242, 183, 5))                 # lamp
        d.rectangle([826, 580, 834, 690], fill=(60, 60, 60))
    else:  # kitchen
        d.rectangle([60, 430, 680, 680], fill=(250, 250, 248))
        d.rectangle([60, 410, 680, 440], fill=(70, 70, 70))
        for x in (80, 290, 500):
            d.rectangle([x, 470, x + 170, 660], outline=ac, width=6)
        d.rectangle([60, 150, 680, 300], fill=tuple(int(c * .9) for c in soft))
        d.ellipse([140, 340, 200, 400], fill=(184, 51, 106))
        d.ellipse([220, 350, 270, 400], fill=(242, 183, 5))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Command(BaseCommand):
    help = "Load demo apartments, guests, bookings and payments."

    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="Only seed if there are no apartments yet")

    def handle(self, *args, **opts):
        from stays.models import (Amenity, Apartment, ApartmentPhoto, Booking, ContactInquiry, MaintenanceTicket,
                                  Payment)
        from stays.services import BookingError, confirm_payment, create_booking, get_or_create_guest

        User = get_user_model()
        username = os.environ.get("ADMIN_USERNAME", "admin")
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username, os.environ.get("ADMIN_EMAIL", "admin@kunda.gm"), os.environ.get("ADMIN_PASSWORD", "admin12345"))
            self.stdout.write(self.style.SUCCESS(f"Created admin user '{username}'"))
        admin = User.objects.get(username=username)

        if opts["if_empty"] and Apartment.objects.exists():
            self.stdout.write("Apartments already exist — skipping demo data.")
            return

        random.seed(7)
        amenities = [Amenity.objects.get_or_create(name=n, defaults={"icon": i})[0] for n, i in AMENITIES]
        floors = {0: "ground floor", 1: "first floor", 2: "second floor"}
        apts = []
        for num, name, tag, floor, beds, baths, cap, size, rate, monthly, accent in APARTMENTS:
            apt, created = Apartment.objects.get_or_create(number=num, defaults=dict(
                name=name, tagline=tag, floor=floor, bedrooms=beds, bathrooms=baths, capacity=cap, size_sqm=size,
                daily_rate=Decimal(rate), monthly_rate=Decimal(monthly), cleaning_fee=Decimal(300 if beds < 2 else 500),
                description=DESCRIPTION.format(name=name, floor=floors[floor], beds=beds, s="s" if beds > 1 else ""),
                accent=accent, is_featured=num in ("201", "301", "102"),
            ))
            if created:
                apt.amenities.set(random.sample(amenities[:4], 4) + random.sample(amenities[4:], 5))
                for i, (scene, caption) in enumerate([("living", "Living room"), ("bedroom", "Bedroom"), ("kitchen", "Kitchen")]):
                    ph = ApartmentPhoto(apartment=apt, caption=caption, order=i, is_cover=i == 0)
                    ph.image.save(f"apt-{num}-{scene}.jpg", ContentFile(_photo(accent, num, scene)), save=True)
            apts.append(apt)

        today = timezone.localdate()
        guests = [get_or_create_guest(n, p, country=c, email=n.split()[0].lower() + "@example.com") for n, p, c in GUESTS]

        plans = [  # (apt index, start offset, nights, flow)
            (0, -12, 5, "out"), (1, -6, 9, "in"), (2, -3, 6, "in_partial"), (3, -20, 4, "out"),
            (4, -1, 4, "in"), (5, 0, 3, "arrive_today"), (6, 2, 35, "confirmed"), (2, 4, 3, "pending"),
            (0, 3, 7, "confirmed_partial"), (7, 6, 5, "pending_guest_paid"), (3, 10, 6, "confirmed"),
            (1, 15, 4, "pending"), (5, 9, 2, "confirmed"), (4, -40, 10, "out"), (7, -30, 30, "out"),
        ]
        sources = ["website", "website", "whatsapp", "walk_in", "phone", "agent"]
        for idx, (ai, off, nights, flow) in enumerate(plans):
            apt, guest = apts[ai], guests[idx % len(guests)]
            ci = today + timedelta(days=off)
            try:
                b = create_booking(apartment=apt, guest=guest, check_in=ci, check_out=ci + timedelta(days=nights),
                                   adults=min(2, apt.capacity), source=random.choice(sources), allow_past=True,
                                   payment_option="full" if idx % 4 == 0 else "deposit", created_by=admin)
            except BookingError:
                continue
            method = random.choice(["wave", "afrimoney", "qmoney", "bank", "cash"])
            def pay(amount, kind):
                p = Payment.objects.create(booking=b, amount=amount, kind=kind, method=method, reference=f"TX{random.randint(100000, 999999)}")
                confirm_payment(p, admin, notify=False)
                # backdate so reports have history
                Payment.objects.filter(pk=p.pk).update(paid_at=timezone.now() + timedelta(days=min(off, 0) - 2))
            if flow in ("out", "in", "arrive_today", "confirmed"):
                pay(b.total_amount, Payment.FULL)
            elif flow in ("in_partial", "confirmed_partial"):
                pay(b.deposit_amount, Payment.DEPOSIT)
            elif flow == "pending_guest_paid":
                Payment.objects.create(booking=b, amount=b.deposit_amount, kind=Payment.DEPOSIT, method="wave",
                                       reference="WV83KD92", submitted_by_guest=True)
            b.refresh_from_db()
            if flow == "out":
                b.status, b.checked_in_at, b.checked_out_at = Booking.CHECKED_OUT, timezone.now(), timezone.now()
            elif flow in ("in", "in_partial"):
                b.status, b.checked_in_at = Booking.CHECKED_IN, timezone.now()
            b.save()

        # A few months of older paid stays for the revenue chart
        for m in range(1, 6):
            apt = apts[m % len(apts)]
            ci = today - timedelta(days=30 * m + 45)
            try:
                b = create_booking(apartment=apt, guest=guests[m], check_in=ci, check_out=ci + timedelta(days=6 + m), allow_past=True, source="website")
            except BookingError:
                continue
            p = Payment.objects.create(booking=b, amount=b.total_amount, kind=Payment.FULL, method="wave", reference=f"HX{m}0021")
            confirm_payment(p, admin, notify=False)
            Payment.objects.filter(pk=p.pk).update(paid_at=timezone.now() - timedelta(days=30 * m))
            b.refresh_from_db()
            b.status = Booking.CHECKED_OUT
            b.save()

        MaintenanceTicket.objects.get_or_create(
            apartment=apts[7], title="Replace bathroom water heater",
            defaults=dict(priority="high", description="Guest reported lukewarm water.", assigned_to="Modou (plumber)",
                          block_from=today + timedelta(days=20), block_until=today + timedelta(days=22)),
        )
        MaintenanceTicket.objects.get_or_create(apartment=apts[2], title="Balcony door handle loose", defaults=dict(priority="low"))
        ContactInquiry.objects.get_or_create(name="Isatou Bah", defaults=dict(phone="+220 7001122", message="Do you offer airport pickup for a family of 5 arriving on the 14th?", apartment=apts[3]))
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(apts)} apartments and {Booking.objects.count()} bookings."))
