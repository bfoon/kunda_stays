from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Release expired holds and prepare payment / arrival reminders (same as the Celery beat jobs)."

    def handle(self, *args, **opts):
        from stays.tasks import release_expired_holds, send_checkin_reminders, send_payment_reminders

        self.stdout.write(f"Holds released: {release_expired_holds()}")
        self.stdout.write(f"Payment reminders: {send_payment_reminders()}")
        self.stdout.write(f"Arrival reminders: {send_checkin_reminders()}")
