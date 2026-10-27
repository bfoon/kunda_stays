# Kunda Stays — apartment booking platform

Django 5.2 · PostgreSQL 16 · Redis + Celery · Bootstrap 5 · Docker Compose

A serviced-apartment website with live availability, online booking, mobile-money
friendly payments, WhatsApp guest communication and a full staff dashboard.

## Run it

```bash
cp .env.example .env        # edit business details, numbers and secrets
docker compose up --build
```

- Website: http://localhost:8000
- Dashboard: http://localhost:8000/dashboard/ (login `admin` / `admin12345` — change in `.env`)
- Django admin: http://localhost:8000/admin/

With `SEED_DEMO=1` the first start loads 8 demo apartments (with generated photos),
guests, bookings, payments and a maintenance ticket. Set it to `0` for production.

## What's inside

**Guest website**
- Home page "door board": every apartment as a door, showing who's free tonight
- Listings with filters (dates, guests, bedrooms, price, amenities) and live per-stay prices
- Apartment pages with photo gallery, amenities, nightly + monthly rates
- Inline availability calendar: taken nights are struck through and can't be selected;
  checkout on someone else's arrival day is allowed
- Live quote (monthly pricing kicks in automatically at 30+ nights) and deposit vs. full payment choice
- Booking page styled like a ticket: QR code for reception, status timeline, hold countdown,
  payment instructions (Wave / Afrimoney / QMoney / bank / cash), "I've paid" form,
  PDF receipts and statement, add-to-calendar (.ics), directions and WhatsApp
- Booking lookup by reference + phone/email, contact form, Google Maps everywhere

**Double-booking prevention (three layers)**
1. Calendar UI blocks taken nights
2. Server re-checks availability inside a transaction with a row lock on the apartment
3. PostgreSQL exclusion constraint (`btree_gist`, `daterange && daterange`) — the database
   itself refuses overlapping active bookings, even under simultaneous requests

**Payments**
- Deposit % per apartment, or pay in full
- Guest-submitted mobile-money references wait for staff verification
- Gap-free receipt numbers (`KS2026-00001`), ReportLab PDF receipts and statements with QR codes
- Balances, part payments, refunds, payment status everywhere

**Dashboard**
- Today: occupancy gauge, money collected, outstanding balances, arrivals/departures with
  one-click check-in/out, payments to verify, holds with countdowns, 6-month revenue chart
- Occupancy chart (tape chart): apartments × days, colour-coded bars, click an empty night to book it
- Bookings: filters, walk-in/phone booking form, change dates with automatic re-pricing,
  discounts, notes, cancel / no-show
- Apartments: photos (drag-and-drop upload, choose cover), amenities, rates, visibility
- Guests with stay history, maintenance tickets that can close a unit's calendar,
  reports (occupancy, ADR, RevPAR, revenue by apartment/method, sources, CSV export)

**WhatsApp**
- Automatic messages: booking received, confirmed, payment receipt, payment reminder,
  arrival reminder (with map link), hold released
- If `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` are set, messages go out through the
  WhatsApp Cloud API. Otherwise they queue in **Dashboard → Messages** with an
  "Open WhatsApp" button that opens the chat with the text already filled in.
- Note: Meta only allows free-form text within 24 hours of the guest's last message. For
  cold reminders in production, register message templates and switch `stays/whatsapp.py`
  to send `"type": "template"`.

**Background jobs (Celery beat)**
- Every 15 min: release unpaid holds after `BOOKING_HOLD_HOURS`
- 09:00: payment reminders for guests arriving within 3 days with a balance
- 10:00: arrival reminders for tomorrow's check-ins
- Run them manually: `docker compose exec web python manage.py send_reminders`

## Project layout

```
config/            settings, urls, celery
stays/             models, services (pricing/availability/payments), public views,
                   whatsapp, receipts (PDF), tasks, seed_demo command
dashboard/         staff views (manual POST handling, StaffMixin)
templates/         base + stays/* (public) + dashboard/*
static/css/ks.css  ks-* design system
static/js/ks.js    calendar, live quote, countdowns, dropzone
```

## Production notes
- Set `DJANGO_DEBUG=0`, a long `DJANGO_SECRET_KEY`, real `DJANGO_ALLOWED_HOSTS`,
  `DJANGO_CSRF_TRUSTED_ORIGINS` and `SITE_URL` (used in WhatsApp links and QR codes).
- Uploaded photos are served by Django at `/media/`; behind heavy traffic put nginx in front
  and serve the `media` volume directly.
- Back up the `pgdata` and `media` volumes.
