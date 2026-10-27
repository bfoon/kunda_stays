"""PDF receipts and booking statements (ReportLab)."""
from io import BytesIO

from django.conf import settings
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

RIVER = colors.HexColor("#0B4F5C")
SUN = colors.HexColor("#F2B705")
INK = colors.HexColor("#10262B")
MUTED = colors.HexColor("#5B7378")
LINE = colors.HexColor("#D6E3E1")


def _money(v):
    v = float(v or 0)
    s = f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"
    return f"{settings.KUNDA['currency_symbol']} {s}"


def _header(c, w, h, title, number):
    k = settings.KUNDA
    c.setFillColor(RIVER)
    c.rect(0, h - 34 * mm, w, 34 * mm, stroke=0, fill=1)
    c.setFillColor(SUN)
    c.rect(0, h - 36 * mm, w, 2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(14 * mm, h - 15 * mm, k["name"])
    c.setFont("Helvetica", 8.5)
    c.drawString(14 * mm, h - 21 * mm, k["address"])
    c.drawString(14 * mm, h - 26 * mm, f"{k['phone']}   {k['email']}")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(w - 14 * mm, h - 15 * mm, title)
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 14 * mm, h - 21 * mm, number)


def _qr(c, url, x, y, size):
    widget = QrCodeWidget(url)
    b = widget.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


def _rows(c, x, y, w, rows, lead=7 * mm):
    for label, value in rows:
        c.setFont("Helvetica", 9)
        c.setFillColor(MUTED)
        c.drawString(x, y, label)
        c.setFont("Helvetica-Bold", 9.5)
        c.setFillColor(INK)
        c.drawRightString(x + w, y, str(value))
        c.setStrokeColor(LINE)
        c.line(x, y - 2.5 * mm, x + w, y - 2.5 * mm)
        y -= lead
    return y


def receipt_pdf(payment):
    b = payment.booking
    buf = BytesIO()
    w, h = A5
    c = canvas.Canvas(buf, pagesize=A5)
    c.setTitle(f"Receipt {payment.receipt_number}")
    _header(c, w, h, "RECEIPT", payment.receipt_number or "")
    y = h - 48 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica", 9)
    c.drawString(14 * mm, y, "Received from")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(14 * mm, y - 6 * mm, b.guest.full_name)
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED)
    c.drawString(14 * mm, y - 11 * mm, b.guest.phone)

    c.setFillColor(colors.HexColor("#EEF4F3"))
    c.roundRect(w - 64 * mm, y - 14 * mm, 50 * mm, 20 * mm, 3 * mm, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(w - 60 * mm, y + 1 * mm, "Amount paid")
    c.setFillColor(RIVER)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(w - 60 * mm, y - 8 * mm, _money(payment.amount))

    y -= 26 * mm
    paid_at = payment.paid_at.astimezone().strftime("%d %b %Y, %H:%M") if payment.paid_at else ""
    y = _rows(c, 14 * mm, y, w - 28 * mm, [
        ("Booking", b.reference),
        ("Apartment", f"{b.apartment.number} – {b.apartment.name}"),
        ("Stay", f"{b.check_in:%d %b} – {b.check_out:%d %b %Y} ({b.nights} nights)"),
        ("Payment", payment.get_kind_display()),
        ("Method", payment.get_method_display()),
        ("Transaction ref.", payment.reference or "—"),
        ("Date", paid_at),
        ("Booking total", _money(b.total_amount)),
        ("Paid to date", _money(b.amount_paid)),
        ("Balance due", _money(b.balance)),
    ])
    _qr(c, settings.KUNDA["site_url"] + b.get_absolute_url(), 14 * mm, 12 * mm, 22 * mm)
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(40 * mm, 26 * mm, "Scan to open your booking.")
    c.drawString(40 * mm, 21 * mm, f"Received by: {payment.received_by or 'Kunda Stays'}")
    c.drawString(40 * mm, 16 * mm, "Thank you for staying with us.")
    c.showPage()
    c.save()
    return buf.getvalue()


def statement_pdf(booking):
    b = booking
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Statement {b.reference}")
    _header(c, w, h, "BOOKING STATEMENT", b.reference)
    y = h - 50 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(16 * mm, y, b.guest.full_name)
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED)
    c.drawString(16 * mm, y - 5 * mm, f"{b.guest.phone}   {b.guest.email}")
    c.drawRightString(w - 16 * mm, y, f"Status: {b.get_status_display()}")
    y -= 16 * mm
    y = _rows(c, 16 * mm, y, w - 32 * mm, [
        ("Apartment", f"{b.apartment.number} – {b.apartment.name}"),
        ("Check-in", f"{b.check_in:%A %d %B %Y} from {settings.KUNDA['checkin_time']}"),
        ("Check-out", f"{b.check_out:%A %d %B %Y} by {settings.KUNDA['checkout_time']}"),
        ("Guests", f"{b.adults} adult(s), {b.children} child(ren)"),
        (f"Accommodation ({b.nights} nights, {b.get_rate_plan_display().lower()})", _money(b.subtotal)),
        ("Cleaning fee", _money(b.cleaning_fee)),
        ("Discount", f"− {_money(b.discount)}"),
        ("Total", _money(b.total_amount)),
    ])
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(RIVER)
    c.drawString(16 * mm, y, "Payments")
    y -= 8 * mm
    rows = []
    for p in b.payments.all().order_by("created_at"):
        if p.status != "confirmed":
            continue
        sign = "− " if p.kind == "refund" else ""
        rows.append((f"{p.paid_at:%d %b %Y} · {p.get_kind_display()} · {p.get_method_display()} · {p.receipt_number}", f"{sign}{_money(p.amount)}"))
    if not rows:
        rows = [("No confirmed payments yet", "")]
    y = _rows(c, 16 * mm, y, w - 32 * mm, rows)
    y -= 4 * mm
    c.setFillColor(colors.HexColor("#EEF4F3"))
    c.roundRect(16 * mm, y - 14 * mm, w - 32 * mm, 18 * mm, 3 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica", 10)
    c.drawString(22 * mm, y - 4 * mm, f"Paid {_money(b.amount_paid)} of {_money(b.total_amount)}")
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(RIVER)
    c.drawRightString(w - 22 * mm, y - 6 * mm, f"Balance {_money(b.balance)}")
    _qr(c, settings.KUNDA["site_url"] + b.get_absolute_url(), w - 46 * mm, 16 * mm, 30 * mm)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(16 * mm, 30 * mm, "Pay by Wave, Afrimoney, QMoney, bank transfer or cash at reception.")
    c.drawString(16 * mm, 25 * mm, "Quote your booking reference with every payment.")
    c.showPage()
    c.save()
    return buf.getvalue()
