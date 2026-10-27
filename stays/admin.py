from django.contrib import admin

from .models import (ActivityLog, Amenity, Apartment, ApartmentPhoto, Booking, CashUp, ContactInquiry, Expense, ExtraItem,
                     Guest, MaintenanceTicket, MessageLog, Payment, PropertyProfile, RateRule, RoomCharge)


class PhotoInline(admin.TabularInline):
    model = ApartmentPhoto
    extra = 1


@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "capacity", "daily_rate", "monthly_rate", "status", "is_featured")
    list_filter = ("status", "is_featured", "bedrooms")
    search_fields = ("number", "name")
    filter_horizontal = ("amenities",)
    inlines = [PhotoInline]


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("receipt_number",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "guest", "apartment", "check_in", "check_out", "status", "total_amount")
    list_filter = ("status", "source", "apartment")
    search_fields = ("reference", "guest__full_name", "guest__phone")
    date_hierarchy = "check_in"
    inlines = [PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "booking", "amount", "kind", "method", "status", "paid_at")
    list_filter = ("status", "method", "kind")
    search_fields = ("receipt_number", "reference", "booking__reference")


admin.site.register(Amenity)
admin.site.register(Guest, search_fields=("full_name", "phone", "email"), list_display=("full_name", "phone", "email", "country"))
admin.site.register(MaintenanceTicket, list_display=("title", "apartment", "priority", "status"), list_filter=("status", "priority"))
admin.site.register(MessageLog, list_display=("kind", "to", "status", "created_at"), list_filter=("status", "kind"))
admin.site.register(ContactInquiry, list_display=("name", "phone", "handled", "created_at"))


@admin.register(RateRule)
class RateRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "adjust_type", "value", "start", "end", "min_nights", "priority", "is_active")
    list_filter = ("is_active", "adjust_type")
    filter_horizontal = ("apartments",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("spent_on", "category", "description", "amount", "apartment", "recorded_by")
    list_filter = ("category", "method")
    search_fields = ("description", "payee", "reference")
    date_hierarchy = "spent_on"


@admin.register(CashUp)
class CashUpAdmin(admin.ModelAdmin):
    list_display = ("business_date", "staff", "expected_cash", "counted_cash", "float_amount", "reviewed_by")
    list_filter = ("staff",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "category", "summary", "user", "actor", "ip")
    list_filter = ("category",)
    search_fields = ("summary",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(PropertyProfile)


@admin.register(ExtraItem)
class ExtraItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "unit", "stock", "is_active", "guest_can_order")
    list_filter = ("category", "is_active")
    list_editable = ("price", "stock", "is_active")
    search_fields = ("name",)


@admin.register(RoomCharge)
class RoomChargeAdmin(admin.ModelAdmin):
    list_display = ("charged_on", "booking", "quantity", "description", "amount", "source", "posted_by", "voided_at")
    list_filter = ("category", "source", "charged_on")
    search_fields = ("description", "booking__reference", "booking__guest__full_name")
    readonly_fields = ("booking", "item", "amount", "posted_by", "voided_at", "voided_by")

    def has_delete_permission(self, request, obj=None):
        return False  # void from the portal instead, so the tab stays honest
