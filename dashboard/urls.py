from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("occupancy/", views.TapeChartView.as_view(), name="tape"),
    path("apartments/", views.ApartmentListView.as_view(), name="apartments"),
    path("apartments/new/", views.ApartmentEditView.as_view(), name="apartment_new"),
    path("apartments/<uuid:pk>/", views.ApartmentEditView.as_view(), name="apartment_edit"),
    path("bookings/", views.BookingListView.as_view(), name="bookings"),
    path("bookings/new/", views.BookingCreateView.as_view(), name="booking_new"),
    path("bookings/<uuid:pk>/", views.BookingDetailView.as_view(), name="booking"),
    path("payments/", views.PaymentListView.as_view(), name="payments"),
    path("guests/", views.GuestListView.as_view(), name="guests"),
    path("guests/<uuid:pk>/", views.GuestDetailView.as_view(), name="guest"),
    path("maintenance/", views.MaintenanceView.as_view(), name="maintenance"),
    path("reports/", views.ReportsView.as_view(), name="reports"),
    path("messages/", views.MessagesView.as_view(), name="messages"),
]
