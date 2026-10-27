"""Starter extras menu (drinks, meals, laundry, transfers…). Safe to run more than once."""
from decimal import Decimal

from django.core.management.base import BaseCommand

from stays.models import ExtraItem

MENU = [
    # name, category, price, unit, emoji, stock, guest_can_order
    ("Bottled water 1.5L", "minibar", 60, "bottle", "💧", 48, True),
    ("Soft drink", "minibar", 75, "can", "🥤", 36, True),
    ("Julbrew beer", "minibar", 120, "bottle", "🍺", 24, True),
    ("Cashew nuts", "minibar", 150, "pack", "🥜", 20, True),
    ("Baobab juice (bouye)", "drinks", 100, "glass", "🥛", None, True),
    ("Wonjo (hibiscus) juice", "drinks", 100, "glass", "🍹", None, True),
    ("Attaya green tea", "drinks", 75, "pot", "🍵", None, True),
    ("Coffee", "drinks", 90, "cup", "☕", None, True),
    ("Glass of wine", "drinks", 300, "glass", "🍷", None, True),
    ("Breakfast", "food", 450, "person", "🍳", None, True),
    ("Domoda with rice", "food", 600, "plate", "🍛", None, True),
    ("Benachin", "food", 600, "plate", "🍲", None, True),
    ("Chicken yassa", "food", 650, "plate", "🍗", None, True),
    ("Grilled fish & chips", "food", 750, "plate", "🐟", None, True),
    ("Laundry", "laundry", 250, "kg", "🧺", None, True),
    ("Ironing", "laundry", 50, "piece", "👔", None, True),
    ("Airport transfer (Banjul)", "transport", 1500, "trip", "✈️", None, True),
    ("Taxi to Senegambia strip", "transport", 400, "trip", "🚕", None, True),
    ("Late check-out (to 16:00)", "services", 1000, "", "⏰", None, True),
    ("Extra bed", "services", 500, "night", "🛏️", None, True),
    ("Baby cot", "services", 0, "stay", "👶", None, True),
    ("Lost key card", "damages", 300, "", "🔑", None, False),
    ("Broken glass", "damages", 150, "", "🥂", None, False),
]


class Command(BaseCommand):
    help = "Add a starter extras menu for room charges (skips items that already exist)."

    def handle(self, *args, **opts):
        added = 0
        for i, (name, cat, price, unit, emoji, stock, guest) in enumerate(MENU):
            _, created = ExtraItem.objects.get_or_create(name=name, defaults=dict(
                category=cat, price=Decimal(price), unit=unit, emoji=emoji, stock=stock, guest_can_order=guest, sort=i * 10,
            ))
            added += created
        self.stdout.write(self.style.SUCCESS(f"Extras menu ready: {added} new item(s), {ExtraItem.objects.count()} in total."))
