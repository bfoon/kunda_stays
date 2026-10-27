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
        ("Bill total" if b.extras_total else "Booking total", _money(b.grand_total)),
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


class _Pager:
    """Writes rows down an A4 page and starts a new page (with a slim header) when it runs out of room."""

    def __init__(self, c, w, h, title, number):
        self.c, self.w, self.h, self.title, self.number = c, w, h, title, number
        self.page = 1
        self.x, self.width = 16 * mm, w - 32 * mm

    def need(self, y, space):
        if y - space >= 36 * mm:
            return y
        self.footer()
        self.c.showPage()
        self.page += 1
        c, w, h = self.c, self.w, self.h
        c.setFillColor(RIVER)
        c.rect(0, h - 16 * mm, w, 16 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(14 * mm, h - 10 * mm, settings.KUNDA["name"])
        c.drawRightString(w - 14 * mm, h - 10 * mm, f"{self.title} {self.number} · continued")
        return h - 28 * mm

    def footer(self):
        self.c.setFont("Helvetica", 7.5)
        self.c.setFillColor(MUTED)
        self.c.drawRightString(self.w - 16 * mm, 10 * mm, f"Page {self.page}")

    def heading(self, y, text, right=""):
        y = self.need(y, 16 * mm)
        c = self.c
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(RIVER)
        c.drawString(self.x, y, text)
        if right:
            c.setFont("Helvetica", 8.5)
            c.setFillColor(MUTED)
            c.drawRightString(self.x + self.width, y, right)
        return y - 8 * mm

    def row(self, y, label, value, *, muted=False, strike=False, bold=False, indent=0):
        y = self.need(y, 8 * mm)
        c = self.c
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        c.setFillColor(MUTED if muted else INK)
        c.drawString(self.x + indent, y, label[:95])
        c.setFont("Helvetica-Bold", 9.5)
        c.drawRightString(self.x + self.width, y, str(value))
        if strike:
            c.setStrokeColor(MUTED)
            c.line(self.x + indent, y + 1.2 * mm, self.x + self.width, y + 1.2 * mm)
        c.setStrokeColor(LINE)
        c.line(self.x, y - 2.5 * mm, self.x + self.width, y - 2.5 * mm)
        return y - 7 * mm


def statement_pdf(booking):
    """The guest's bill: accommodation, every room charge by day, payments and the balance.

    Before arrival it is titled "Booking statement"; once the guest is in or has left it is the "Guest bill".
    """
    from .services import tab_summary

    b = booking
    k = settings.KUNDA
    tab = tab_summary(b)
    title = "GUEST BILL" if b.status in ("checked_in", "checked_out") else "BOOKING STATEMENT"
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"{title.title()} {b.reference}")
    _header(c, w, h, title, b.reference)
    pg = _Pager(c, w, h, title.title(), b.reference)

    y = h - 50 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(16 * mm, y, b.guest.full_name)
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED)
    c.drawString(16 * mm, y - 5 * mm, f"{b.guest.phone}   {b.guest.email}")
    c.drawRightString(w - 16 * mm, y, f"Apt {b.apartment.number} – {b.apartment.name}")
    c.drawRightString(w - 16 * mm, y - 5 * mm, f"{b.check_in:%d %b %Y} → {b.check_out:%d %b %Y} · {b.nights} night{'s' if b.nights != 1 else ''}")
    y -= 16 * mm

    y = pg.heading(y, "Accommodation")
    y = pg.row(y, f"{b.nights} night{'s' if b.nights != 1 else ''} · {b.get_rate_plan_display().lower()}", _money(b.subtotal))
    if b.cleaning_fee:
        y = pg.row(y, "Cleaning fee", _money(b.cleaning_fee))
    if b.discount:
        y = pg.row(y, "Discount", f"− {_money(b.discount)}")
    y = pg.row(y, "Accommodation total", _money(b.total_amount), bold=True)

    if tab["days"]:
        y -= 4 * mm
        y = pg.heading(y, "Room charges", f"{len(tab['charges'])} item{'s' if len(tab['charges']) != 1 else ''}")
        for d in tab["days"]:
            y = pg.need(y, 16 * mm)
            c.setFont("Helvetica-Bold", 8.5)
            c.setFillColor(MUTED)
            c.drawString(16 * mm, y, f"{d['day']:%A %d %B}".upper())
            c.drawRightString(w - 16 * mm, y, _money(d["total"]))
            y -= 6 * mm
            for ch in d["grouped"]:
                qty = f"{ch['quantity']} × " if ch["quantity"] > 1 else ""
                each = f"  @ {_money(ch['unit_price'])}" if ch["quantity"] > 1 else ""
                y = pg.row(y, f"{qty}{ch['description']}{each}", _money(ch["amount"]), indent=3 * mm)
        y = pg.row(y, "Room charges total", _money(tab["total"]), bold=True)

    y -= 4 * mm
    y = pg.heading(y, "Payments")
    paid_rows = 0
    for p in b.payments.all().order_by("created_at"):
        if p.status != "confirmed":
            continue
        sign = "− " if p.kind == "refund" else ""
        y = pg.row(y, f"{p.paid_at:%d %b %Y} · {p.get_kind_display()} · {p.get_method_display()} · {p.receipt_number}", f"{sign}{_money(p.amount)}")
        paid_rows += 1
    if not paid_rows:
        y = pg.row(y, "No confirmed payments yet", "", muted=True)

    y = pg.need(y, 30 * mm) - 4 * mm
    c.setFillColor(colors.HexColor("#EEF4F3"))
    c.roundRect(16 * mm, y - 22 * mm, w - 32 * mm, 26 * mm, 3 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica", 9.5)
    c.drawString(22 * mm, y - 3 * mm, f"Accommodation {_money(b.total_amount)}" + (f"  +  room charges {_money(b.extras_total)}" if b.extras_total else ""))
    c.drawString(22 * mm, y - 9 * mm, f"Total {_money(b.grand_total)}  ·  paid {_money(b.amount_paid)}")
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(RIVER if b.balance else colors.HexColor("#1F6F50"))
    c.drawRightString(w - 22 * mm, y - 8 * mm, f"Balance {_money(b.balance)}" if b.balance else "Paid in full")
    if b.credit:
        c.setFont("Helvetica", 9)
        c.drawRightString(w - 22 * mm, y - 15 * mm, f"Credit due to guest {_money(b.credit)}")
    # need() above keeps the summary box above 50 mm, so the footer block below never overlaps it
    _qr(c, k["site_url"] + b.get_absolute_url(), w - 40 * mm, 12 * mm, 24 * mm)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(16 * mm, 28 * mm, "Pay by Wave, Afrimoney, QMoney, bank transfer or cash at reception.")
    c.drawString(16 * mm, 23 * mm, "Quote your booking reference with every payment. Scan the code for your live bill.")
    if title == "GUEST BILL":
        c.drawString(16 * mm, 16 * mm, "Guest signature: ______________________________")
    pg.footer()
    c.showPage()
    c.save()
    return buf.getvalue()
