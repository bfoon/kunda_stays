/* Kunda Stays operations portal */
(function () {
  "use strict";

  const money = (v) => {
    const sym = document.body.dataset.currency || "D";
    const n = Number(v || 0);
    return sym + " " + n.toLocaleString(undefined, { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ---------- Ctrl+K command palette ---------- */
  const paletteEl = document.getElementById("ks-palette");
  if (paletteEl) {
    const modal = new bootstrap.Modal(paletteEl);
    const input = paletteEl.querySelector("[data-palette-input]");
    const list = paletteEl.querySelector("[data-palette-list]");
    let items = [], active = 0, timer = null, seq = 0;

    const render = () => {
      if (!items.length) { list.innerHTML = '<li class="ks-empty">Nothing matches. Try a booking reference like KS-7QX2MD or a phone number.</li>'; return; }
      list.innerHTML = items.map((r, i) =>
        '<li><a href="' + esc(r.url) + '" class="' + (i === active ? "on" : "") + '" role="option"><i class="bi bi-' + esc(r.icon) + '"></i><span>' + esc(r.label) + "<small>" + esc(r.kind) + "</small></span></a></li>"
      ).join("");
      const on = list.querySelector("a.on");
      if (on) on.scrollIntoView({ block: "nearest" });
    };
    const search = () => {
      const mine = ++seq;
      fetch(input.dataset.url + "?q=" + encodeURIComponent(input.value.trim()), { headers: { Accept: "application/json" } })
        .then((r) => r.json()).then((d) => { if (mine !== seq) return; items = d.results || []; active = 0; render(); })
        .catch(() => { list.innerHTML = '<li class="ks-empty">Search is unavailable. Check your connection.</li>'; });
    };
    const open = () => { modal.show(); };
    document.querySelectorAll("[data-palette-open]").forEach((b) => b.addEventListener("click", open));
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); open(); }
      if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); open(); }
    });
    paletteEl.addEventListener("shown.bs.modal", () => { input.value = ""; input.focus(); search(); });
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 160); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, items.length - 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
      else if (e.key === "Enter" && items[active]) { e.preventDefault(); window.location = items[active].url; }
    });
  }

  /* ---------- till counter ---------- */
  const till = document.querySelector("[data-till]");
  if (till) {
    const expected = Number(till.dataset.expected || 0);
    const notes = till.querySelectorAll("[data-denom]");
    const loose = till.querySelector("[name=loose]");
    const flt = till.querySelector("[name=float]");
    const out = {
      counted: till.querySelector("[data-counted]"), net: till.querySelector("[data-net]"),
      verdict: till.querySelector("[data-verdict]"), vAmount: till.querySelector("[data-verdict-amount]"), vText: till.querySelector("[data-verdict-text]"),
    };
    const recalc = () => {
      let counted = 0;
      notes.forEach((n) => {
        const d = Number(n.dataset.denom), input = n.querySelector("input"), c = Math.max(0, parseInt(input.value || "0", 10) || 0);
        counted += d * c;
        n.classList.toggle("has", c > 0);
        n.querySelector("[data-line]").textContent = c ? money(d * c) : "";
      });
      counted += Number(loose.value || 0);
      const net = counted - Number(flt.value || 0);
      const diff = Math.round((net - expected) * 100) / 100;
      out.counted.textContent = money(counted);
      out.net.textContent = money(net);
      out.verdict.classList.remove("ok", "short", "over");
      if (counted === 0 && expected !== 0) { out.vAmount.textContent = money(expected); out.vText.textContent = "to find in the drawer — start counting"; return; }
      if (diff === 0) { out.verdict.classList.add("ok"); out.vAmount.textContent = "Balanced"; out.vText.textContent = "Counted cash matches the system"; }
      else if (diff < 0) { out.verdict.classList.add("short"); out.vAmount.textContent = "−" + money(-diff); out.vText.textContent = "Short — recount, or explain in the note"; }
      else { out.verdict.classList.add("over"); out.vAmount.textContent = "+" + money(diff); out.vText.textContent = "Over — a payment may not be recorded"; }
    };
    notes.forEach((n) => {
      const input = n.querySelector("input");
      n.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
        input.value = Math.max(0, (parseInt(input.value || "0", 10) || 0) + Number(b.dataset.step));
        recalc();
      }));
      input.addEventListener("input", recalc);
    });
    [loose, flt].forEach((i) => i.addEventListener("input", recalc));
    recalc();
  }

  /* ---------- apartment photos: drag to reorder ---------- */
  const grid = document.querySelector("[data-photo-grid]");
  if (grid) {
    const orderInput = document.querySelector("[name=photo_order]");
    let dragged = null;
    const sync = () => { orderInput.value = Array.from(grid.querySelectorAll("[data-photo]")).map((c) => c.dataset.photo).join(","); };
    grid.querySelectorAll("[data-photo]").forEach((col) => {
      const tile = col.querySelector(".ks-photo-tile");
      tile.setAttribute("draggable", "true");
      tile.addEventListener("dragstart", (e) => { dragged = col; tile.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; });
      tile.addEventListener("dragend", () => { tile.classList.remove("dragging"); grid.querySelectorAll(".drop-target").forEach((t) => t.classList.remove("drop-target")); sync(); });
      col.addEventListener("dragover", (e) => { e.preventDefault(); if (col !== dragged) tile.classList.add("drop-target"); });
      col.addEventListener("dragleave", () => tile.classList.remove("drop-target"));
      col.addEventListener("drop", (e) => {
        e.preventDefault(); tile.classList.remove("drop-target");
        if (!dragged || dragged === col) return;
        const cols = Array.from(grid.children);
        grid.insertBefore(dragged, cols.indexOf(dragged) < cols.indexOf(col) ? col.nextSibling : col);
        sync();
      });
    });
    sync();
  }

  /* ---------- price rule presets ---------- */
  const ruleForm = document.querySelector("[data-rule-form]");
  if (ruleForm) {
    document.querySelectorAll("[data-preset]").forEach((btn) => btn.addEventListener("click", () => {
      const p = JSON.parse(btn.dataset.preset);
      ruleForm.querySelector("[name=rule]").value = "";
      ruleForm.querySelector("[name=name]").value = p.name;
      ruleForm.querySelector("[name=start]").value = p.start;
      ruleForm.querySelector("[name=end]").value = p.end;
      ruleForm.querySelector("[name=adjust_type]").value = p.type;
      ruleForm.querySelector("[name=value]").value = p.value;
      ruleForm.querySelector("[name=min_nights]").value = p.min_nights;
      ruleForm.querySelector("[name=colour]").value = p.colour;
      ruleForm.querySelectorAll("[name=weekdays]").forEach((c) => (c.checked = p.weekdays.includes(c.value)));
      ruleForm.querySelector("[data-rule-title]").textContent = "New rule: " + p.label;
      ruleForm.scrollIntoView({ behavior: "smooth", block: "start" });
      ruleForm.querySelector("[name=name]").focus({ preventScroll: true });
      updateHint();
    }));
    const typeSel = ruleForm.querySelector("[name=adjust_type]"), hint = ruleForm.querySelector("[data-value-hint]");
    const updateHint = () => {
      hint.textContent = { percent: "e.g. 15 for +15%, or -10 for 10% off", amount: "e.g. 500 to add, or -300 to take off each night", fixed: "The nightly price on covered nights" }[typeSel.value];
    };
    typeSel.addEventListener("change", updateHint);
    updateHint();
  }

  /* ---------- quote tester (uses the public availability API) ---------- */
  const tester = document.querySelector("[data-quote-tester]");
  if (tester) {
    const out = tester.querySelector("[data-quote-out]");
    tester.addEventListener("submit", (e) => {
      e.preventDefault();
      const apt = tester.querySelector("[name=apt]"), ci = tester.querySelector("[name=t_ci]").value, co = tester.querySelector("[name=t_co]").value;
      if (!ci || !co) { out.innerHTML = '<p class="text-danger mb-0">Choose both dates.</p>'; return; }
      out.innerHTML = '<div class="placeholder-glow"><span class="placeholder col-12"></span><span class="placeholder col-7"></span></div>';
      fetch(apt.value + "?check_in=" + ci + "&check_out=" + co).then((r) => r.json()).then((d) => {
        if (d.error) { out.innerHTML = '<p class="text-danger mb-0">' + esc(d.error) + "</p>"; return; }
        const q = d.quote;
        let h = '<div class="ks-quote">';
        h += '<div class="ks-quote-row"><span>Base ' + money(q.nightly_rate) + " × " + q.nights + "</span><span>" + money(q.base_subtotal) + "</span></div>";
        (q.adjustments || []).forEach((a) => { const n = Number(a.amount); h += '<div class="ks-quote-row ' + (n < 0 ? "text-success" : "") + '"><span>' + esc(a.name) + "</span><span>" + (n < 0 ? "−" : "+") + money(Math.abs(n)) + "</span></div>"; });
        if (q.rate_plan === "monthly") h += '<div class="ks-quote-row"><span>Monthly rate applied</span><span>' + money(q.subtotal) + "</span></div>";
        if (Number(q.cleaning_fee)) h += '<div class="ks-quote-row"><span>Cleaning</span><span>' + money(q.cleaning_fee) + "</span></div>";
        h += '<div class="ks-quote-row ks-quote-total"><span>Guest pays</span><span>' + money(q.total) + "</span></div>";
        h += '<div class="ks-quote-row ks-muted"><span>Average a night</span><span>' + money(q.average_nightly) + "</span></div></div>";
        h += d.available ? '<p class="ks-small text-success mt-2 mb-0"><i class="bi bi-check-circle"></i> Those dates are free.</p>' : '<p class="ks-small text-danger mt-2 mb-0"><i class="bi bi-x-circle"></i> Not free on those dates.</p>';
        out.innerHTML = h;
      }).catch(() => { out.innerHTML = '<p class="text-danger mb-0">Couldn\'t load the quote.</p>'; });
    });
  }

  /* ---------- property profile: live WhatsApp preview ---------- */
  const prof = document.querySelector("[data-profile-form]");
  if (prof) {
    const bubble = document.querySelector("[data-wa-preview]"), title = document.querySelector("[data-wa-name]");
    const val = (n) => { const el = prof.querySelector("[name=" + n + "]"); return (el && el.value.trim()) || (el && el.placeholder) || ""; };
    const draw = () => {
      title.textContent = val("name");
      bubble.textContent =
        "✅ *Booking confirmed — KS-7QX2MD*\n\nApt 201 (Atlantic View)\nFri 12 Dec → Mon 15 Dec · 3 nights\n\n" +
        "Paid: " + money(4500) + " · Balance: " + money(9100) + "\n" +
        "Check-in from " + val("checkin_time") + ", check-out by " + val("checkout_time") + ".\n" +
        "📍 " + val("address") + "\nhttps://maps.google.com/?q=" + val("lat") + "," + val("lng");
    };
    prof.addEventListener("input", draw);
    draw();
  }

  /* ---------- charge to room (POS) ---------- */
  const pos = document.querySelector("[data-pos]");
  if (pos) {
    const ticket = [];  // {key, item, name, price, qty, stock, custom, category}
    const linesEl = pos.querySelector("[data-lines]"), totalEl = pos.querySelector("[data-total]");
    const submit = pos.querySelector("[data-submit]"), submitLabel = pos.querySelector("[data-submit-label]");
    const hidden = pos.querySelector("[name=ticket]"), bookingInput = pos.querySelector("[name=booking]");
    const bar = document.querySelector("[data-ticket-bar]");
    const roomLabel = pos.querySelector("[data-ticket-room]").textContent.trim();

    const draw = () => {
      let total = 0, count = 0;
      linesEl.innerHTML = ticket.length ? "" : '<li class="ks-receipt-empty">Tap items to add them.</li>';
      ticket.forEach((l, idx) => {
        total += l.price * l.qty; count += l.qty;
        const li = document.createElement("li");
        li.innerHTML = "<span>" + esc(l.name) + (l.qty > 1 ? ' <small class="ks-muted">@ ' + money(l.price) + "</small>" : "") + "</span>" +
          '<span class="ks-stepper"><button type="button" data-d="-1" aria-label="One fewer">−</button><output>' + l.qty + '</output><button type="button" data-d="1" aria-label="One more">+</button></span>' +
          '<span class="line-amt">' + money(l.price * l.qty) + "</span>";
        li.querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => change(idx, Number(b.dataset.d))));
        linesEl.appendChild(li);
      });
      pos.querySelectorAll(".ks-tile[data-item]").forEach((t) => {
        const l = ticket.find((x) => x.item === t.dataset.item);
        t.classList.toggle("picked", !!l);
        t.querySelector(".qty").textContent = l ? l.qty : "";
      });
      totalEl.textContent = money(total);
      hidden.value = JSON.stringify(ticket.map((l) => l.custom ? { custom: l.name, price: l.price, qty: l.qty, category: l.category } : { item: l.item, qty: l.qty }));
      const ready = count > 0 && bookingInput.value;
      submit.disabled = !ready;
      submitLabel.textContent = !bookingInput.value ? "Pick a room first" : count ? "Charge " + money(total) + " to " + roomLabel.split(" · ")[0] : "Charge to room";
      if (bar) {
        bar.hidden = count === 0;
        bar.querySelector("[data-bar-count]").textContent = count + (count === 1 ? " item" : " items");
        bar.querySelector("[data-bar-total]").textContent = money(total);
      }
    };
    const change = (idx, d) => {
      const l = ticket[idx];
      const next = l.qty + d;
      if (l.stock != null && next > l.stock) { flash("Only " + l.stock + " " + l.name + " in stock."); return; }
      if (next <= 0) ticket.splice(idx, 1); else l.qty = Math.min(next, 99);
      draw();
    };
    const flash = (msg) => {
      totalEl.closest(".ks-receipt").animate([{ transform: "translateX(-4px)" }, { transform: "translateX(4px)" }, { transform: "none" }], { duration: 220 });
      submitLabel.textContent = msg;
      setTimeout(draw, 1600);
    };

    pos.querySelectorAll(".ks-tile[data-item]").forEach((t) => t.addEventListener("click", () => {
      const idx = ticket.findIndex((x) => x.item === t.dataset.item);
      if (idx >= 0) { change(idx, 1); return; }
      ticket.push({ item: t.dataset.item, name: t.dataset.name, price: Number(t.dataset.price), qty: 1, stock: t.dataset.stock != null ? Number(t.dataset.stock) : null });
      draw();
    }));

    pos.querySelectorAll("[data-cat]").forEach((a) => {
      if (a.tagName !== "A") return;
      a.addEventListener("click", (e) => {
        e.preventDefault();
        pos.querySelectorAll("a[data-cat]").forEach((x) => x.classList.toggle("on", x === a));
        pos.querySelectorAll(".ks-tile").forEach((t) => t.classList.toggle("hide", a.dataset.cat !== "all" && t.dataset.cat !== a.dataset.cat));
      });
    });

    const cDesc = document.getElementById("c-desc"), cPrice = document.getElementById("c-price"), cCat = document.getElementById("c-cat");
    const addCustom = () => {
      const name = cDesc.value.trim(), price = Number(cPrice.value);
      if (!name || !(price >= 0) || cPrice.value === "") { (name ? cPrice : cDesc).focus(); return; }
      ticket.push({ custom: true, name: name, price: price, qty: 1, category: cCat.value, stock: null });
      cDesc.value = ""; cPrice.value = "";
      draw();
    };
    pos.querySelector("[data-add-custom]").addEventListener("click", addCustom);
    [cDesc, cPrice].forEach((i) => i.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }));
    pos.querySelectorAll(".ks-void-pop input").forEach((i) => i.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); if (i.value.trim()) document.getElementById(i.getAttribute("form")).requestSubmit(); }
    }));
    pos.addEventListener("submit", () => { submit.disabled = true; submitLabel.textContent = "Charging…"; });
    draw();
  }

  /* ---------- booking page: quick add to tab ---------- */
  const quick = document.querySelector("[data-quick-charge]");
  if (quick) {
    const sel = quick.querySelector("[name=item]");
    const toggle = () => {
      const custom = sel.value === "";
      quick.querySelectorAll("[data-custom]").forEach((el) => el.classList.toggle("d-none", !custom));
      quick.querySelector("[name=description]").required = custom;
      quick.querySelector("[name=unit_price]").required = custom;
    };
    sel.addEventListener("change", toggle);
    toggle();
  }

  /* ---------- confirm buttons ---------- */
  document.querySelectorAll("[data-confirm]").forEach((el) => el.addEventListener("click", (e) => { if (!confirm(el.dataset.confirm)) e.preventDefault(); }));
})();
