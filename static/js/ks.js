/* Kunda Stays front-end helpers */
(function () {
  "use strict";

  const money = (v) => {
    const sym = document.body.dataset.currency || "D";
    const n = Number(v || 0);
    return sym + " " + n.toLocaleString(undefined, { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
  };
  const ymd = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const parseYmd = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };

  /* ---------- copy buttons ---------- */
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(btn.dataset.copy).then(() => {
        const old = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check2"></i> Copied';
        setTimeout(() => (btn.innerHTML = old), 1500);
      });
    });
  });

  /* ---------- hold countdown ---------- */
  document.querySelectorAll("[data-countdown]").forEach((el) => {
    let left = parseInt(el.dataset.countdown, 10);
    const tick = () => {
      if (left <= 0) { el.textContent = "expired"; return; }
      const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
      el.textContent = (h ? h + "h " : "") + String(m).padStart(2, "0") + "m " + String(s).padStart(2, "0") + "s";
      left -= 1;
    };
    tick();
    setInterval(tick, 1000);
  });

  /* ---------- toasts ---------- */
  document.querySelectorAll(".toast").forEach((t) => new bootstrap.Toast(t, { delay: 6000 }).show());

  /* ---------- dashboard sidebar ---------- */
  const side = document.querySelector(".ks-side");
  document.querySelectorAll("[data-side-toggle]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); side && side.classList.toggle("open"); }));
  document.addEventListener("click", (e) => { if (side && side.classList.contains("open") && !side.contains(e.target)) side.classList.remove("open"); });

  /* ---------- photo dropzone ---------- */
  document.querySelectorAll(".ks-dropzone").forEach((zone) => {
    const input = document.getElementById(zone.dataset.input);
    const list = zone.querySelector(".ks-drop-list");
    const show = () => { list.textContent = input.files.length ? Array.from(input.files).map((f) => f.name).join(", ") : ""; };
    zone.addEventListener("click", () => input.click());
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
    zone.addEventListener("drop", (e) => { input.files = e.dataTransfer.files; show(); });
  });

  /* ---------- hero date range search ---------- */
  document.querySelectorAll("[data-range-picker]").forEach((input) => {
    const form = input.closest("form");
    const ci = form.querySelector("[name=check_in]"), co = form.querySelector("[name=check_out]");
    flatpickr(input, {
      mode: "range", minDate: "today", dateFormat: "Y-m-d", altInput: true, altFormat: "D j M",
      showMonths: window.innerWidth > 768 ? 2 : 1,
      defaultDate: ci.value && co.value ? [ci.value, co.value] : null,
      onChange: (sel) => { ci.value = sel[0] ? ymd(sel[0]) : ""; co.value = sel[1] ? ymd(sel[1]) : ""; },
    });
  });

  /* ---------- apartment booking calendar ---------- */
  const panel = document.getElementById("ks-booking");
  if (!panel) return;
  const api = panel.dataset.api;
  const ci = panel.querySelector("[name=check_in]");
  const co = panel.querySelector("[name=check_out]");
  const quoteBox = document.getElementById("ks-quote");
  const submit = panel.querySelector("[type=submit]");
  const mobilePrice = document.getElementById("ks-mobile-price");
  let booked = []; // [{from: Date, to: Date}] inclusive nights
  let anchor = null;
  const today = new Date(); today.setHours(0, 0, 0, 0);

  const isBookedNight = (d) => booked.some((r) => d >= r.from && d <= r.to);
  const nextBookedAfter = (d) => {
    let best = null;
    booked.forEach((r) => { if (r.from > d && (!best || r.from < best)) best = r.from; });
    return best;
  };

  const renderQuote = (data) => {
    if (!data) { quoteBox.innerHTML = '<p class="ks-muted mb-0">Pick your arrival and departure on the calendar to see the price.</p>'; submit.disabled = true; return; }
    if (data.error) { quoteBox.innerHTML = '<p class="text-danger mb-0">' + data.error + "</p>"; submit.disabled = true; return; }
    const q = data.quote;
    const nightsLabel = q.nights + " night" + (q.nights > 1 ? "s" : "");
    const adj = q.adjustments || [];
    let html = "";
    if (q.rate_plan === "monthly") {
      html += '<div class="ks-quote-row"><span>Monthly rate applied</span><span>' + money(q.subtotal) + "</span></div>";
    } else if (adj.length) {
      html += '<div class="ks-quote-row"><span>' + money(q.nightly_rate) + " × " + nightsLabel + "</span><span>" + money(q.base_subtotal) + "</span></div>";
      adj.forEach((a) => {
        const n = Number(a.amount);
        html += '<div class="ks-quote-row' + (n < 0 ? " text-success" : "") + '"><span>' + a.name + "</span><span>" + (n < 0 ? "−" : "+") + money(Math.abs(n)) + "</span></div>";
      });
    } else {
      html += '<div class="ks-quote-row"><span>' + money(q.nightly_rate) + " × " + nightsLabel + "</span><span>" + money(q.subtotal) + "</span></div>";
    }
    if (Number(q.savings) > 0) html += '<div class="ks-quote-row text-success"><span>You save with monthly pricing</span><span>' + money(q.savings) + "</span></div>";
    if (Number(q.cleaning_fee) > 0) html += '<div class="ks-quote-row"><span>Cleaning fee</span><span>' + money(q.cleaning_fee) + "</span></div>";
    html += '<div class="ks-quote-row ks-quote-total"><span>Total</span><span>' + money(q.total) + "</span></div>";
    html += '<div class="ks-quote-row ks-muted"><span>Deposit to confirm (' + q.deposit_percent + "%)</span><span>" + money(q.deposit) + "</span></div>";
    if (!data.available) html += '<p class="text-danger mt-2 mb-0"><i class="bi bi-x-circle"></i> These dates are no longer free.</p>';
    quoteBox.innerHTML = html;
    submit.disabled = !data.available;
    document.querySelectorAll("[data-deposit-label]").forEach((el) => (el.textContent = money(q.deposit)));
    document.querySelectorAll("[data-total-label]").forEach((el) => (el.textContent = money(q.total)));
    if (mobilePrice) mobilePrice.innerHTML = "<strong>" + money(q.total) + "</strong> <span class='ks-muted ks-small'>" + q.nights + " night" + (q.nights > 1 ? "s" : "") + "</span>";
  };

  const fetchQuote = () => {
    if (!(ci.value && co.value)) { renderQuote(null); return; }
    quoteBox.innerHTML = '<div class="placeholder-glow"><span class="placeholder col-12"></span><span class="placeholder col-8"></span></div>';
    fetch(api + "?check_in=" + ci.value + "&check_out=" + co.value).then((r) => r.json()).then(renderQuote).catch(() => renderQuote({ error: "Couldn't load the price. Check your connection." }));
  };

  fetch(api).then((r) => r.json()).then((data) => {
    booked = data.ranges.map((r) => ({ from: parseYmd(r.from), to: parseYmd(r.to) }));
    const fp = flatpickr("#ks-calendar", {
      inline: true, mode: "range", minDate: "today", dateFormat: "Y-m-d",
      // Two months only when the panel itself has room for them (~300px each), not the window
      showMonths: document.getElementById("ks-calendar").clientWidth >= 600 ? 2 : 1,
      defaultDate: ci.value && co.value ? [ci.value, co.value] : null,
      disable: [function (d) {
        if (!data.bookable) return true;
        if (anchor) {
          if (d <= anchor) return isBookedNight(d);
          const nb = nextBookedAfter(anchor);
          return !!(nb && d > nb);
        }
        return isBookedNight(d);
      }],
      onDayCreate: (dObj, dStr, inst, dayElem) => { if (isBookedNight(dayElem.dateObj)) dayElem.classList.add("ks-booked"); },
      onChange: (sel, str, inst) => {
        anchor = sel.length === 1 ? sel[0] : null;
        ci.value = sel[0] ? ymd(sel[0]) : "";
        co.value = sel[1] ? ymd(sel[1]) : "";
        inst.redraw();
        if (sel.length === 2) fetchQuote(); else renderQuote(null);
      },
    });
    if (ci.value && co.value) fetchQuote(); else renderQuote(null);
    panel.querySelector("[data-clear-dates]")?.addEventListener("click", () => { anchor = null; fp.clear(); ci.value = co.value = ""; renderQuote(null); });
  });

  const same = panel.querySelector("[name=same_whatsapp]");
  const waWrap = document.getElementById("ks-wa-wrap");
  if (same && waWrap) same.addEventListener("change", () => waWrap.classList.toggle("d-none", same.checked));
})();

/* In-stay ordering: guest builds an order, it opens WhatsApp to reception with an itemized message */
(function () {
  "use strict";
  const box = document.querySelector("[data-guest-order]");
  if (!box) return;
  const sym = document.body.dataset.currency || "D";
  const fmt = (n) => sym + " " + Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const rows = box.querySelectorAll(".ks-order-row");
  const send = box.querySelector("[data-order-send]"), label = box.querySelector("[data-order-label]"), note = box.querySelector("[data-order-note]");
  const update = () => {
    const lines = [];
    let total = 0, count = 0;
    rows.forEach((r) => {
      const q = Number(r.querySelector("output").value || r.querySelector("output").textContent);
      r.classList.toggle("on", q > 0);
      if (q > 0) { lines.push(q + " × " + r.dataset.name); total += q * Number(r.dataset.price); count += q; }
    });
    if (!count) {
      send.classList.add("disabled"); send.setAttribute("aria-disabled", "true"); send.href = "#";
      label.textContent = "Choose something to order";
      return;
    }
    let msg = "🛎️ *Order for Apt " + box.dataset.apt + "* (" + box.dataset.ref + ")\n\n" + lines.map((l) => "• " + l).join("\n") + "\n\nAbout " + fmt(total) + " — please add it to my room tab.";
    if (note.value.trim()) msg += "\nNote: " + note.value.trim();
    send.href = "https://wa.me/" + box.dataset.wa + "?text=" + encodeURIComponent(msg);
    send.classList.remove("disabled"); send.removeAttribute("aria-disabled");
    label.textContent = "Send order · " + count + " item" + (count > 1 ? "s" : "") + " · " + fmt(total);
  };
  rows.forEach((r) => {
    const out = r.querySelector("output");
    r.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
      const v = Math.max(0, Math.min(20, Number(out.textContent) + Number(b.dataset.step)));
      out.textContent = v; out.value = v; update();
    }));
  });
  note.addEventListener("input", update);
  update();
})();
