import secrets
import uuid
from datetime import timedelta
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

    HK_DIRTY = "dirty"
    HK_CLEANING = "cleaning"
    HK_CLEAN = "clean"
    HK_INSPECTED = "inspected"
    HK_CHOICES = [(HK_DIRTY, "Needs cleaning"), (HK_CLEANING, "Being cleaned"), (HK_CLEAN, "Clean"), (HK_INSPECTED, "Inspected · guest-ready")]
    HK_FLOW = [HK_DIRTY, HK_CLEANING, HK_CLEAN, HK_INSPECTED]
    housekeeping = models.CharField(max_length=12, choices=HK_CHOICES, default=HK_INSPECTED)
    housekeeping_note = models.CharField(max_length=200, blank=True)
    housekeeping_at = models.DateTimeField(null=True, blank=True)
    housekeeping_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

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

    @property
    def is_guest_ready(self):
        return self.housekeeping == self.HK_INSPECTED


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
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, help_text="Accommodation total (room, cleaning, discount)")
    extras_total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, help_text="Room charges on the tab (kept in sync automatically)")
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
    def grand_total(self):
        """Everything the guest owes: accommodation plus room charges."""
        return self.total_amount + (self.extras_total or ZERO)

    @property
    def balance(self):
        return max(self.grand_total - self.amount_paid, ZERO)

    @property
    def credit(self):
        """Overpayment to refund or carry over."""
        return max(self.amount_paid - self.grand_total, ZERO)

    @property
    def accepts_charges(self):
        """Extras can be posted while the guest is in, and for two days after they leave (late minibar, damages)."""
        if self.status == self.CHECKED_IN or self.status == self.CONFIRMED:
            return True
        if self.status == self.CHECKED_OUT:
            return self.check_out >= timezone.localdate() - timedelta(days=2)
        return False

    def recompute_extras(self):
        total = self.charges.filter(voided_at__isnull=True).aggregate(s=models.Sum("amount"))["s"] or ZERO
        Booking.objects.filter(pk=self.pk).update(extras_total=total)
        self.extras_total = total
        return total

    @property
    def deposit_required(self):
        return self.total_amount if self.payment_option == self.OPTION_FULL else self.deposit_amount

    @property
    def deposit_outstanding(self):
        return max(self.deposit_required - self.amount_paid, ZERO)

    @property
    def paid_percent(self):
        if not self.grand_total:
            return 0
        return min(100, int(self.amount_paid / self.grand_total * 100))

    @property
    def payment_state(self):
        if self.grand_total and self.balance <= 0:
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
    def can_pay_online(self):
        """Active bookings, and guests who left owing something (e.g. room charges)."""
        return self.balance > 0 and (self.is_active or self.status == self.CHECKED_OUT)

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
        ("bill", "Room bill"),
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


# ===================== Operations portal =====================

class RateRule(Base):
    """A pricing rule. Rules stack in priority order for every night they cover:
    a fixed price replaces the running nightly price, percent and amount rules adjust it."""
    PERCENT = "percent"
    AMOUNT = "amount"
    FIXED = "fixed"
    TYPE_CHOICES = [(PERCENT, "Change by %"), (AMOUNT, "Change by amount per night"), (FIXED, "Set nightly price")]
    WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    name = models.CharField(max_length=80)
    apartments = models.ManyToManyField(Apartment, blank=True, related_name="rate_rules", help_text="Leave empty for every apartment")
    start = models.DateField()
    end = models.DateField(help_text="Last night covered (inclusive)")
    weekdays = models.CharField(max_length=7, default="0123456", help_text="Nights of the week, 0 = Monday")
    adjust_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_nights = models.PositiveSmallIntegerField(default=0, help_text="Only for stays at least this long (0 = any stay)")
    priority = models.SmallIntegerField(default=10, help_text="Lower runs first")
    is_active = models.BooleanField(default=True)
    colour = models.CharField(max_length=7, default="#F2B705")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["priority", "start", "created_at"]
        constraints = [models.CheckConstraint(condition=Q(end__gte=F("start")), name="raterule_end_after_start")]

    def __str__(self):
        return self.name

    @property
    def weekday_labels(self):
        if len(self.weekdays) == 7:
            return "Every night"
        return ", ".join(self.WEEKDAYS[int(c)] for c in self.weekdays if c.isdigit())

    @property
    def effect_label(self):
        v = self.value.normalize() if self.value == self.value.to_integral_value() else self.value
        v = Decimal(int(v)) if v == v.to_integral_value() else v
        sym = settings.KUNDA["currency_symbol"]
        if self.adjust_type == self.FIXED:
            return f"{sym} {v:,.0f} a night"
        sign = "+" if v >= 0 else "−"
        if self.adjust_type == self.PERCENT:
            return f"{sign}{abs(v)}%"
        return f"{sign}{sym} {abs(v):,.0f} a night"

    def covers(self, day, stay_nights):
        return (
            self.is_active and self.start <= day <= self.end and str(day.weekday()) in self.weekdays
            and stay_nights >= self.min_nights
        )

    def apply(self, price):
        if self.adjust_type == self.FIXED:
            return self.value
        if self.adjust_type == self.PERCENT:
            return price * (Decimal(100) + self.value) / Decimal(100)
        return price + self.value


class Expense(Base):
    CATEGORY_CHOICES = [
        ("electricity", "Electricity (NAWEC)"),
        ("water", "Water"),
        ("fuel", "Generator fuel"),
        ("internet", "Internet"),
        ("salaries", "Salaries & wages"),
        ("cleaning", "Cleaning & laundry"),
        ("supplies", "Guest supplies"),
        ("repairs", "Repairs & parts"),
        ("security", "Security"),
        ("marketing", "Marketing & commissions"),
        ("tax", "Taxes & licences"),
        ("rent", "Rent & lease"),
        ("other", "Other"),
    ]
    METHOD_CHOICES = [("cash", "Cash"), ("wave", "Wave"), ("afrimoney", "Afrimoney"), ("qmoney", "QMoney"), ("bank", "Bank transfer"), ("card", "Card")]

    spent_on = models.DateField(db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other", db_index=True)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payee = models.CharField(max_length=120, blank=True)
    method = models.CharField(max_length=15, choices=METHOD_CHOICES, default="cash")
    reference = models.CharField(max_length=80, blank=True)
    apartment = models.ForeignKey(Apartment, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses", help_text="Leave empty for the whole property")
    receipt = models.FileField(upload_to="expenses/%Y/%m/", blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-spent_on", "-created_at"]

    def __str__(self):
        return f"{self.get_category_display()}: {self.amount}"


class CashUp(Base):
    """End-of-shift till count: what the system says a staff member took in vs. what they counted."""
    business_date = models.DateField(db_index=True)
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cashups")
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    float_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, help_text="Opening float left in the till")
    counts = models.JSONField(default=dict, blank=True, help_text="Denomination → number of notes/coins")
    methods = models.JSONField(default=dict, blank=True, help_text="Method → {total, count, checked}")
    note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-business_date", "-created_at"]

    def __str__(self):
        return f"Till {self.business_date} · {self.staff}"

    @property
    def variance(self):
        return self.counted_cash - self.float_amount - self.expected_cash


class ActivityLog(Base):
    CATEGORY_CHOICES = [
        ("auth", "Sign-in"), ("booking", "Bookings"), ("payment", "Payments"), ("rates", "Pricing"),
        ("finance", "Finance"), ("property", "Property"), ("housekeeping", "Housekeeping"), ("staff", "Staff"),
        ("charges", "Room charges"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity")
    actor = models.CharField(max_length=80, blank=True, help_text="Shown when there is no user, e.g. Guest or System")
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, db_index=True)
    summary = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.summary

    @property
    def who(self):
        if self.user_id:
            return self.user.get_full_name() or self.user.get_username()
        return self.actor or "System"


class PropertyProfile(models.Model):
    """Business details editable from the portal. Blank fields fall back to the .env values."""
    FIELD_MAP = [  # model field -> settings.KUNDA key
        "name", "tagline", "phone", "whatsapp", "email", "address", "lat", "lng", "checkin_time", "checkout_time",
        "wave_number", "afrimoney_number", "qmoney_number", "bank_details", "house_rules", "cancellation_policy",
    ]

    name = models.CharField(max_length=120, blank=True)
    tagline = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    lat = models.CharField(max_length=20, blank=True)
    lng = models.CharField(max_length=20, blank=True)
    checkin_time = models.CharField(max_length=5, blank=True)
    checkout_time = models.CharField(max_length=5, blank=True)
    hold_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    wave_number = models.CharField(max_length=40, blank=True)
    afrimoney_number = models.CharField(max_length=40, blank=True)
    qmoney_number = models.CharField(max_length=40, blank=True)
    bank_details = models.CharField(max_length=255, blank=True)
    house_rules = models.TextField(blank=True)
    cancellation_policy = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    def __str__(self):
        return "Property profile"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ===================== Room charges (the guest's tab) =====================

class ExtraItem(Base):
    """Something staff can charge to a room: a drink, a meal, laundry, a taxi…"""
    CATEGORY_CHOICES = [
        ("drinks", "Drinks"), ("food", "Food"), ("minibar", "Minibar"), ("laundry", "Laundry"),
        ("transport", "Transport"), ("services", "Services"), ("damages", "Damages & losses"), ("other", "Other"),
    ]
    ICONS = {
        "drinks": "cup-straw", "food": "egg-fried", "minibar": "box2-heart", "laundry": "basket2", "transport": "car-front",
        "services": "bell", "damages": "exclamation-triangle", "other": "three-dots",
    }

    name = models.CharField(max_length=80)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default="drinks", db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=20, blank=True, help_text="e.g. bottle, plate, kg, trip")
    emoji = models.CharField(max_length=4, blank=True, help_text="Shown on the tap-to-charge tile, e.g. 🍺")
    stock = models.PositiveIntegerField(null=True, blank=True, help_text="Leave empty if you don't count stock")
    low_stock_at = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)
    guest_can_order = models.BooleanField(default=True, help_text="Show on the guest's in-stay order menu")
    sort = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["category", "sort", "name"]

    def __str__(self):
        return self.name

    @property
    def icon(self):
        return self.ICONS.get(self.category, "tag")

    @property
    def tracks_stock(self):
        return self.stock is not None

    @property
    def low_stock(self):
        return self.stock is not None and self.stock <= self.low_stock_at

    @property
    def sold_out(self):
        return self.stock is not None and self.stock <= 0


class RoomCharge(Base):
    """One line on a guest's tab. Never deleted: mistakes are voided with a reason."""
    SOURCE_CHOICES = [
        ("desk", "Front desk"), ("bar", "Bar / kitchen"), ("minibar", "Minibar check"), ("housekeeping", "Housekeeping"),
        ("guest", "Guest order"), ("checkout", "Check-out"),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="charges")
    item = models.ForeignKey(ExtraItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="charges")
    description = models.CharField(max_length=120)
    category = models.CharField(max_length=15, choices=ExtraItem.CATEGORY_CHOICES, default="other")
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    charged_on = models.DateField(db_index=True)
    source = models.CharField(max_length=15, choices=SOURCE_CHOICES, default="desk")
    note = models.CharField(max_length=200, blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    void_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["charged_on", "created_at"]
        indexes = [models.Index(fields=["booking", "voided_at"])]

    def __str__(self):
        return f"{self.quantity} × {self.description}"

    @property
    def is_void(self):
        return self.voided_at is not None

    @property
    def icon(self):
        return ExtraItem.ICONS.get(self.category, "tag")
