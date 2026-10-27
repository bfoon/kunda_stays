from django.urls import path

from . import accounts, charges, finance, operations, pricing, views

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
    # Operations portal
    path("rates/", pricing.RatesView.as_view(), name="rates"),
    path("charges/", charges.ChargeToRoomView.as_view(), name="charges"),
    path("charges/menu/", charges.ExtrasMenuView.as_view(), name="extras_menu"),
    path("finance/", finance.FinanceView.as_view(), name="finance"),
    path("finance/expenses/", finance.ExpensesView.as_view(), name="expenses"),
    path("finance/till/", finance.TillView.as_view(), name="till"),
    path("housekeeping/", operations.HousekeepingView.as_view(), name="housekeeping"),
    path("property/", operations.PropertyProfileView.as_view(), name="property"),
    path("staff/", accounts.StaffView.as_view(), name="staff"),
    path("logbook/", accounts.LogbookView.as_view(), name="logbook"),
    path("account/", accounts.AccountView.as_view(), name="account"),
    path("search.json", accounts.SearchView.as_view(), name="search"),
]
