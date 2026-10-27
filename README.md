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
- Staff portal: http://localhost:8000/accounts/login/ (superuser `admin` / `admin12345` — change in `.env`)
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

**Operations portal**
- Sign-in “key rack”: every apartment is a key tag — on its hook means free tonight. Sign in with
  username or email, show-password, Caps Lock warning, “keep me signed in”, lockout after
  `LOGIN_MAX_ATTEMPTS` failures, and a start page chosen by role
- Roles (Django groups): **Manager** (everything), **Front desk** (bookings, guests, payments, own till,
  housekeeping, maintenance), **Finance** (payments, finance, expenses, till sign-off, reports, logbook),
  **Housekeeping** (housekeeping board + maintenance). Superusers are managers; staff with no group are front desk
- Rates & pricing: stacking price rules (percent / amount / fixed price) by date range, nights of the week,
  minimum stay and apartment, with presets (high season, festive peak, weekends, rainy season, week-long stays).
  Month heatmap of the real nightly price, quote checker, bulk rate change, inline base-rate table.
  Rules feed `quote()`, so the website, walk-ins and date changes all use them; guests see each adjustment
- Finance: profit & loss by period, 12-month in/out/profit chart, profit by apartment, money owed by age,
  CSV ledger. Expenses with categories and receipt photos (opens the phone camera)
- Close the till: count notes per denomination (`CASH_DENOMINATIONS`), float, tick off mobile-money totals
  against statements, balanced/short/over verdict; finance signs off (never your own)
- Housekeeping board: phone-first cards sorted by urgency, Dirty → Cleaning → Clean → Ready. Check-out marks
  the room dirty automatically; Today warns when an arriving guest's room isn't ready
- Property profile: business details, payment numbers, times, house rules and cancellation policy edited live,
  with a WhatsApp preview. Overrides `.env` everywhere (pages, receipts, messages, Celery reminders)
- Staff & roles (one-time readable passwords), Logbook (automatic audit trail via signals), My account,
  Ctrl+K / “/” search across pages, bookings and guests, photo drag-to-reorder with captions and a listing score

With `SEED_DEMO=1` you also get staff `awa` (front desk), `musa` (finance), `binta` (housekeeping) and
`ida` (manager), password `DEMO_STAFF_PASSWORD` (default `kunda-demo-2026`), plus starter price rules,
six months of expenses and a till close. **Change or delete these accounts before going live.**

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
dashboard/         staff portal: views.py (core), accounts.py (sign-in, staff, logbook, search),
                   pricing.py, finance.py, operations.py (housekeeping, property profile), roles.py
templates/         base + stays/* (public) + dashboard/*
static/css/ks.css  ks-* design system
static/js/ks.js    calendar, live quote, countdowns, dropzone
static/js/portal.js  command palette, till counter, photo reorder, rule presets, quote checker
```

## Production notes
- Set `DJANGO_DEBUG=0`, a long `DJANGO_SECRET_KEY`, real `DJANGO_ALLOWED_HOSTS`,
  `DJANGO_CSRF_TRUSTED_ORIGINS` and `SITE_URL` (used in WhatsApp links and QR codes).
- Uploaded photos are served by Django at `/media/`; behind heavy traffic put nginx in front
  and serve the `media` volume directly.
- Back up the `pgdata` and `media` volumes.
