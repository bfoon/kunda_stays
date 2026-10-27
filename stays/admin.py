from django.contrib import admin

from .models import (Amenity, Apartment, ApartmentPhoto, Booking, ContactInquiry, Guest, MaintenanceTicket,
                     MessageLog, Payment)


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
