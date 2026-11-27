const $a = (id) => document.getElementById(id);

function renderKpis(k) {
  $a("kpis").innerHTML = [
    [k.total_orders, "Total orders"],
    ["₹" + k.revenue, "Cashless revenue"],
    [k.ready, "Ready for pickup"],
    [k.handover_pct + "%", `Handed over (${k.collected} of ${k.total_orders}). Target: under 10 s per scan`],
  ].map(([v, l]) => `<div class="kpi"><strong>${esc(v)}</strong><span>${esc(l)}</span></div>`).join("");
}

function renderSlots(slots) {
  $a("slot-load").innerHTML = slots.map((s) => {
    const pct = Math.round((100 * s.booked_count) / s.max_capacity);
    return `<div class="load-row"><div class="row"><span>${esc(s.start_time)}–${esc(s.end_time)}</span>
      <span>${s.booked_count}/<input type="number" min="1" max="60" value="${s.max_capacity}" data-cap="${esc(s.slot_id)}"
        style="width:64px;padding:2px 6px" aria-label="Capacity for ${esc(s.start_time)}"></span></div>
      <div class="bar"><i class="${s.is_full ? "full" : pct >= 80 ? "warn" : ""}" style="width:${pct}%"></i></div></div>`;
  }).join("");
}

function renderMenu(menu) {
  $a("menu-table").innerHTML = "<thead><tr><th>Dish</th><th>Price</th><th>Status</th><th>Stock</th><th>Serving</th></tr></thead><tbody>" +
    menu.map((m) => `<tr><td>${esc(m.dish_name)}</td><td>₹${m.price}</td><td>${stockBadge(m.stock_status, m.stock_qty)}</td>
      <td><input type="number" min="0" max="500" value="${m.stock_qty}" data-stock="${m.item_id}" aria-label="Stock for ${esc(m.dish_name)}"></td>
      <td><button class="btn btn-quiet btn-sm" data-toggle="${m.item_id}" data-on="${m.is_available ? 0 : 1}">${m.is_available ? "Pause" : "Resume"}</button></td></tr>`).join("") + "</tbody>";
}

function renderRecent(rows) {
  $a("recent-table").innerHTML = "<thead><tr><th>Order</th><th>Student</th><th>Slot</th><th>Total</th><th>Paid by</th><th>Status</th></tr></thead><tbody>" +
    rows.map((o) => `<tr><td><b>${esc(o.order_id)}</b></td><td>${esc(o.student_name)}</td><td>${esc(o.slot)}</td>
      <td>₹${o.total_amount}</td><td>${esc(o.payment_method)}</td><td>${statusBadge(o.status)}</td></tr>`).join("") + "</tbody>";
}

async function refresh() {
  try {
    const d = await api("/api/admin/summary");
    renderKpis(d.kpis);
    renderRecent(d.recent);
    const editing = document.activeElement && document.activeElement.matches("input[data-stock], input[data-cap]");
    if (!editing) { renderSlots(d.slots); renderMenu(d.menu); }   // don't wipe a field someone is typing in
  } catch (e) { toast(e.message, true); }
}

$a("verify-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const box = $a("verify-result"), input = $a("verify-token");
  try {
    const d = await api("/api/admin/verify", { token: input.value });
    box.className = "verify-result ok";
    box.textContent = `${d.order.order_id} handed over to ${d.order.student_name}: ` +
      d.order.items.map((i) => i.quantity + " × " + i.dish_name).join(", ") + ".";
    input.value = "";
  } catch (err) { box.className = "verify-result bad"; box.textContent = err.message; }
  input.focus();
  refresh();
});

document.addEventListener("change", async (e) => {
  const t = e.target;
  try {
    if (t.dataset.stock) await api("/api/admin/menu/" + t.dataset.stock, { stock_qty: t.value });
    else if (t.dataset.cap) await api("/api/admin/slots/" + encodeURIComponent(t.dataset.cap), { max_capacity: t.value });
    else return;
    toast("Saved.");
  } catch (err) { toast(err.message, true); }
  t.blur(); refresh();
});

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-toggle]");
  if (!b) return;
  try { await api("/api/admin/menu/" + b.dataset.toggle, { is_available: b.dataset.on === "1" }); }
  catch (err) { toast(err.message, true); }
  refresh();
});

refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 5000);
