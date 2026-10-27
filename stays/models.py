import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.db import models, transaction
from django.db.models import F, Func, Q, Value
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ZERO = Decimal("0.00")


def make_reference():
    return "KS-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(6))


class Base(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Sequence(models.Model):
    """Gap-free counters (receipt numbers)."""
    name = models.CharField(max_length=40, unique=True)
    value = models.PositiveIntegerField(default=0)

    @classmethod
    def next(cls, name):
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(name=name)
            seq.value += 1
            seq.save(update_fields=["value"])
            return seq.value


class Amenity(Base):
    name = models.CharField(max_length=80, unique=True)
    icon = models.CharField(max_length=60, default="check2-circle", help_text="Bootstrap Icons name, e.g. wifi, snow, tv")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "amenities"

    def __str__(self):
        return self.name


class Apartment(Base):
    AVAILABLE = "available"
    MAINTENANCE = "maintenance"
    INACTIVE = "inactive"
    STATUS_CHOICES = [
        (AVAILABLE, "Open for booking"),
        (MAINTENANCE, "Under maintenance"),
        (INACTIVE, "Hidden from website"),
    ]

    number = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    tagline = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    floor = models.PositiveSmallIntegerField(default=0)
    bedrooms = models.PositiveSmallIntegerField(default=1)
    bathrooms = models.PositiveSmallIntegerField(default=1)
    capacity = models.PositiveSmallIntegerField(default=2)
    size_sqm = models.PositiveIntegerField(null=True, blank=True)
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    monthly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cleaning_fee = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    deposit_percent = models.PositiveSmallIntegerField(default=30)
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="apartments")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=AVAILABLE)
    is_featured = models.BooleanField(default=False)
    accent = models.CharField(max_length=7, default="#0B4F5C", help_text="Colour used for this unit on the occupancy chart")

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"Apt {self.number} – {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.number}-{self.name}")[:140]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("stays:apartment", args=[self.slug])

    @property
    def cover(self):
        photos = list(self.photos.all())
        for p in photos:
            if p.is_cover:
                return p
        return photos[0] if photos else None

    @property
    def is_bookable(self):
        return self.status == self.AVAILABLE


class ApartmentPhoto(Base):
    apartment = models.ForeignKey(Apartment, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="apartments/%Y/%m/")
    caption = models.CharField(max_length=120, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_cover", "order", "created_at"]

    def __str__(self):
        return self.caption or f"Photo of {self.apartment.number}"


class Guest(Base):
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, db_index=True)
    whatsapp = models.CharField(max_length=30, blank=True, help_text="Leave blank if same as phone")
    email = models.EmailField(blank=True)
    country = models.CharField(max_length=80, blank=True)
    id_type = models.CharField(max_length=40, blank=True)
    id_number = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    @property
    def wa_number(self):
        return self.whatsapp or self.phone

    @property
    def first_name(self):
        return (self.full_name or "").split(" ")[0]


class Booking(Base):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    STATUS_CHOICES = [
        (PENDING, "Awaiting deposit"),
        (CONFIRMED, "Confirmed"),
        (CHECKED_IN, "In house"),
        (CHECKED_OUT, "Checked out"),
        (CANCELLED, "Cancelled"),
        (NO_SHOW, "No-show"),
    ]
    ACTIVE = (PENDING, CONFIRMED, CHECKED_IN)

    OPTION_DEPOSIT = "deposit"
    OPTION_FULL = "full"
    OPTION_CHOICES = [(OPTION_DEPOSIT, "Pay a deposit now"), (OPTION_FULL, "Pay in full")]

    SOURCE_CHOICES = [
        ("website", "Website"),
        ("walk_in", "Walk-in"),
        ("phone", "Phone call"),
        ("whatsapp", "WhatsApp"),
        ("agent", "Agent / partner"),
    ]
    PLAN_CHOICES = [("daily", "Nightly rate"), ("monthly", "Monthly rate")]

    reference = models.CharField(max_length=12, unique=True, default=make_reference, editable=False)
    apartment = models.ForeignKey(Apartment, on_delete=models.PROTECT, related_name="bookings")
    guest = models.ForeignKey(Guest, on_delete=models.PROTECT, related_name="bookings")
    check_in = models.DateField()
    check_out = models.DateField()
    adults = models.PositiveSmallIntegerField(default=1)
    children = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="website")
    payment_option = models.CharField(max_length=10, choices=OPTION_CHOICES, default=OPTION_DEPOSIT)
    rate_plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default="daily")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    cleaning_fee = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    special_requests = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-check_in"]
        constraints = [
            models.CheckConstraint(condition=Q(check_out__gt=F("check_in")), name="booking_checkout_after_checkin"),
            # The database itself refuses two active bookings whose nights overlap
            # on the same apartment — double bookings are impossible, even under race conditions.
            ExclusionConstraint(
                name="booking_no_overlap",
                expressions=[
                    (
                        Func(F("check_in"), F("check_out"), Value("[)"), function="daterange", output_field=DateRangeField()),
                        RangeOperators.OVERLAPS,
                    ),
                    ("apartment", RangeOperators.EQUAL),
                ],
                condition=Q(status__in=["pending", "confirmed", "checked_in"]),
            ),
        ]

    def __str__(self):
        return f"{self.reference} · {self.guest} · Apt {self.apartment.number}"

    def get_absolute_url(self):
        return reverse("stays:booking", args=[self.pk])

    @property
    def nights(self):
        return (self.check_out - self.check_in).days

    @property
    def guests_count(self):
        return self.adults + self.children

    def _confirmed_payments(self):
        return [p for p in self.payments.all() if p.status == Payment.CONFIRMED]

    @property
    def amount_paid(self):
        total = ZERO
        for p in self._confirmed_payments():
            total += -p.amount if p.kind == Payment.REFUND else p.amount
        return total

    @property
    def balance(self):
        return max(self.total_amount - self.amount_paid, ZERO)

    @property
    def deposit_required(self):
        return self.total_amount if self.payment_option == self.OPTION_FULL else self.deposit_amount

    @property
    def deposit_outstanding(self):
        return max(self.deposit_required - self.amount_paid, ZERO)

    @property
    def paid_percent(self):
        if not self.total_amount:
            return 0
        return min(100, int(self.amount_paid / self.total_amount * 100))

    @property
    def payment_state(self):
        if self.total_amount and self.balance <= 0:
            return "paid"
        if self.amount_paid > 0:
            return "partial"
        return "unpaid"

    @property
    def pending_payments(self):
        return [p for p in self.payments.all() if p.status == Payment.PENDING]

    @property
    def is_active(self):
        return self.status in self.ACTIVE

    @property
    def can_guest_cancel(self):
        return self.status == self.PENDING and self.amount_paid == 0 and not self.pending_payments

    @property
    def hold_seconds_left(self):
        if self.status != self.PENDING or not self.hold_expires_at:
            return None
        return max(0, int((self.hold_expires_at - timezone.now()).total_seconds()))


class Payment(Base):
    DEPOSIT = "deposit"
    INSTALLMENT = "installment"
    FULL = "full"
    REFUND = "refund"
    KIND_CHOICES = [(DEPOSIT, "Deposit"), (INSTALLMENT, "Part payment"), (FULL, "Full payment"), (REFUND, "Refund")]

    METHOD_CHOICES = [
        ("wave", "Wave"),
        ("afrimoney", "Afrimoney"),
        ("qmoney", "QMoney"),
        ("bank", "Bank transfer"),
        ("cash", "Cash at reception"),
        ("card", "Card"),
    ]

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    STATUS_CHOICES = [(PENDING, "Awaiting verification"), (CONFIRMED, "Confirmed"), (REJECTED, "Rejected")]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default=DEPOSIT)
    method = models.CharField(max_length=15, choices=METHOD_CHOICES, default="wave")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    reference = models.CharField(max_length=80, blank=True, help_text="Mobile money / bank transaction ID")
    receipt_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    note = models.CharField(max_length=255, blank=True)
    submitted_by_guest = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} · {self.booking.reference}"

    @staticmethod
    def next_receipt_number():
        year = timezone.localdate().year
        return f"KS{year}-{Sequence.next(f'receipt-{year}'):05d}"


class MaintenanceTicket(Base):
    PRIORITY_CHOICES = [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")]
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    STATUS_CHOICES = [(OPEN, "Open"), (IN_PROGRESS, "In progress"), (RESOLVED, "Resolved")]

    apartment = models.ForeignKey(Apartment, on_delete=models.CASCADE, related_name="tickets")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    block_from = models.DateField(null=True, blank=True, help_text="Close the unit to bookings from this date")
    block_until = models.DateField(null=True, blank=True, help_text="…until this date (inclusive)")
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    reported_by = models.CharField(max_length=100, blank=True)
    assigned_to = models.CharField(max_length=100, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Apt {self.apartment.number}: {self.title}"


class MessageLog(Base):
    STATUS_CHOICES = [("sent", "Sent"), ("manual", "Ready to send"), ("failed", "Failed")]
    KIND_CHOICES = [
        ("received", "Booking received"),
        ("confirmation", "Booking confirmed"),
        ("payment", "Payment receipt"),
        ("reminder", "Payment reminder"),
        ("checkin", "Arrival reminder"),
        ("released", "Hold released"),
        ("custom", "Custom message"),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    to = models.CharField(max_length=30)
    channel = models.CharField(max_length=15, default="whatsapp")
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default="custom")
    body = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="manual")
    provider_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.to}"

    @property
    def wa_link(self):
        from .whatsapp import link
        return link(self.to, self.body)


class ContactInquiry(Base):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    message = models.TextField()
    apartment = models.ForeignKey(Apartment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    handled = models.BooleanField(default=False)

    class Meta:
        ordering = ["handled", "-created_at"]
        verbose_name_plural = "contact inquiries"

    def __str__(self):
        return f"{self.name}: {self.message[:40]}"
