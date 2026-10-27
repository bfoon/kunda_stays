from django.urls import path

from . import views

app_name = "stays"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("apartments/", views.ApartmentListView.as_view(), name="apartments"),
    path("apartments/<slug:slug>/", views.ApartmentDetailView.as_view(), name="apartment"),
    path("apartments/<slug:slug>/book/", views.BookView.as_view(), name="book"),
    path("api/apartments/<slug:slug>/availability/", views.AvailabilityApiView.as_view(), name="availability"),
    path("booking/find/", views.BookingLookupView.as_view(), name="lookup"),
    path("booking/<uuid:pk>/", views.BookingDetailView.as_view(), name="booking"),
    path("booking/<uuid:pk>/statement.pdf", views.StatementPdfView.as_view(), name="statement"),
    path("booking/<uuid:pk>/calendar.ics", views.BookingIcsView.as_view(), name="ics"),
    path("receipt/<uuid:pk>.pdf", views.ReceiptPdfView.as_view(), name="receipt"),
    path("contact/", views.ContactView.as_view(), name="contact"),
]
