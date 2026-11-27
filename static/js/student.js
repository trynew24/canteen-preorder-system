const S = { items: {}, cart: {}, slotId: null, wallet: null, orders: [], filterTimer: null };
const $ = (id) => document.getElementById(id);

function qs() {
  const p = new URLSearchParams({ q: $("f-q").value, veg: $("f-veg").value, category: $("f-cat").value });
  return p.toString();
}

async function loadMenu(first) {
  const d = await api("/api/menu?" + qs());
  d.items.forEach((i) => (S.items[i.item_id] = i));
  if (first || $("f-cat").options.length - 1 !== d.categories.length) {
    const cur = $("f-cat").value;
    $("f-cat").innerHTML = '<option value="all">All categories</option>' +
      d.categories.map((c) => `<option>${esc(c)}</option>`).join("");
    $("f-cat").value = d.categories.includes(cur) ? cur : "all";
  }
  $("menu-count").textContent = d.items.length + " dishes";
  $("menu-grid").innerHTML = d.items.length ? d.items.map(dishCard).join("")
    : '<p class="empty">No dishes match. Clear the search or filters.</p>';
  clampCart();
  renderCart();
}

function dishCard(i) {
  const out = i.stock_status === "out_of_stock";
  const q = S.cart[i.item_id] || 0;
  return `<article class="dish ${out ? "out" : ""}">
    <div class="dish-top"><span class="vd ${i.veg ? "" : "nv"}" title="${i.veg ? "Veg" : "Non-veg"}"></span>
      <h4>${esc(i.dish_name)}</h4><span class="price">${rupees(i.price)}</span></div>
    <p>${esc(i.description)}</p>
    <div class="dish-meta">${stockBadge(i.stock_status, i.stock_qty)}<span>${i.prep_mins} min prep</span><span>${esc(i.category)}</span></div>
    <div class="stepper">
      <button data-dec="${i.item_id}" ${q ? "" : "disabled"} aria-label="Remove one ${esc(i.dish_name)}">−</button>
      <span>${q}</span>
      <button data-inc="${i.item_id}" ${out || q >= Math.min(i.stock_qty, 10) ? "disabled" : ""} aria-label="Add one ${esc(i.dish_name)}">+</button>
    </div></article>`;
}

function clampCart() {
  for (const id of Object.keys(S.cart)) {
    const it = S.items[id];
    if (!it || it.stock_status === "out_of_stock") delete S.cart[id];
    else S.cart[id] = Math.min(S.cart[id], it.stock_qty, 10);
    if (S.cart[id] <= 0) delete S.cart[id];
  }
}

function cartTotal() {
  return Object.entries(S.cart).reduce((t, [id, q]) => t + S.items[id].price * q, 0);  // display only; server recomputes
}

function renderCart() {
  const ids = Object.keys(S.cart);
  $("cart-lines").innerHTML = ids.length ? ids.map((id) =>
    `<div class="row"><span>${S.cart[id]} × ${esc(S.items[id].dish_name)}</span><span>${rupees(S.items[id].price * S.cart[id])}</span></div>`).join("")
    : '<span class="muted">Add dishes from the menu.</span>';
  $("cart-total").textContent = rupees(cartTotal());
  $("pay-btn").disabled = !(ids.length && S.slotId);
}

function rerenderCards() {
  $("menu-grid").querySelectorAll("[data-inc]").forEach((b) => {
    const id = b.dataset.inc, it = S.items[id], q = S.cart[id] || 0;
    b.disabled = it.stock_status === "out_of_stock" || q >= Math.min(it.stock_qty, 10);
    b.previousElementSibling.textContent = q;
    b.previousElementSibling.previousElementSibling.disabled = !q;
  });
}

async function loadSlots() {
  const d = await api("/api/slots");
  const sel = d.slots.find((s) => String(s.id) === String(S.slotId));
  if (sel && !sel.is_bookable) S.slotId = null;

  const bookableCount = d.slots.filter((s) => s.is_bookable).length;
  const noSlotsMsg = $("no-slots-msg");
  const payBtn = $("pay-btn");

  if (!d.slots.length || bookableCount === 0) {
    noSlotsMsg.classList.remove("hidden");
    noSlotsMsg.textContent = `No active afternoon pickup slots remain for today (${d.schedule.start_label} – ${d.schedule.end_label}).`;
    S.slotId = null;
  } else {
    noSlotsMsg.classList.add("hidden");
  }

  $("slot-grid").innerHTML = d.slots.map((s) => {
    const pct = Math.round((100 * s.booked_count) / s.max_orders);
    const label = s.is_expired ? "Closed" : s.is_full ? "Full" : `${s.spots_left} spots left`;
    const badgeCls = s.is_full ? "full" : pct >= 80 ? "warn" : "";
    return `<button type="button" class="slot ${String(s.id) === String(S.slotId) ? "sel" : ""}" data-slot="${esc(s.id)}" ${s.is_bookable ? "" : "disabled"}>
      <b>${esc(s.start_time)}–${esc(s.end_time)}</b>
      <small>${s.is_full ? '<span class="badge out">Full</span>' : esc(label)}</small>
      <div class="bar"><i class="${badgeCls}" style="width:${Math.min(pct, 100)}%"></i></div></button>`;
  }).join("");
  renderCart();
  if (bookableCount === 0) payBtn.disabled = true;
}

function setWallet(n) {
  S.wallet = n;
  $("wallet-chip").textContent = rupees(n);
  $("wallet-line").textContent = "(" + rupees(n) + ")";
  const zeroMsg = $("wallet-zero-msg");
  if (zeroMsg) zeroMsg.classList.toggle("hidden", n > 0);
}

async function loadOrders() {
  const d = await api("/api/orders/mine");
  S.orders = d.orders;
  $("my-orders").innerHTML = d.orders.length ? d.orders.map((o) => `
    <article class="order">
      <div class="order-head"><span class="order-id">${esc(o.order_id)}</span>${statusBadge(o.status)}</div>
      <div class="muted">Pickup ${esc(o.slot)} (${esc(o.slot_date)}) · ${esc(o.payment_method)} · ${rupees(o.total_amount)}</div>
      <ul>${o.items.map((i) => `<li>${i.quantity} × ${esc(i.dish_name)}</li>`).join("")}</ul>
      <div class="order-actions">
        ${o.status === "picked_up" || o.status === "cancelled" ? "" : `<button class="btn btn-primary btn-sm" data-qr="${esc(o.order_id)}">Show QR pass</button>`}
        ${o.status === "pending" ? `<button class="btn btn-danger btn-sm" data-cancel="${esc(o.order_id)}">Cancel</button>` : ""}
      </div>
    </article>`).join("") : '<p class="empty">No orders yet. Pick dishes and a slot to book your first pickup.</p>';
}

function openQr(orderId) {
  const o = S.orders.find((x) => x.order_id === orderId);
  if (!o) return;
  $("qr-title").textContent = "Pickup pass · " + o.order_id;
  $("qr-body").innerHTML = `<img src="/orders/${encodeURIComponent(o.order_id)}/qr.svg" alt="QR code for ${esc(o.order_id)}">
    <div class="token">${esc(o.qr_token)}</div>
    <div>${statusBadge(o.status)} <span class="muted">Slot ${esc(o.slot)}</span></div>
    <p class="muted">${o.status === "ready" ? "Your food is ready. Show this code at the counter." : "Show this code at the counter once the order is ready."}</p>`;
  $("qr-modal").classList.remove("hidden");
}

document.addEventListener("click", async (e) => {
  const t = e.target.closest("button, .modal-backdrop");
  if (!t) return;
  if (t.dataset.inc) { const id = t.dataset.inc; S.cart[id] = (S.cart[id] || 0) + 1; clampCart(); renderCart(); rerenderCards(); }
  else if (t.dataset.dec) { const id = t.dataset.dec; S.cart[id] = (S.cart[id] || 1) - 1; if (!S.cart[id]) delete S.cart[id]; renderCart(); rerenderCards(); }
  else if (t.dataset.slot) { S.slotId = Number(t.dataset.slot); await loadSlots(); }
  else if (t.dataset.qr) openQr(t.dataset.qr);
  else if (t.dataset.cancel) {
    const oid = t.dataset.cancel;
    if (!window.confirm(`Cancel order ${oid}?`)) return;
    try {
      const d = await api(`/api/orders/${encodeURIComponent(oid)}/cancel`, {});
      setWallet(d.wallet_balance);
      toast(`Order ${oid} cancelled.`);
      await Promise.all([loadMenu(), loadSlots(), loadOrders()]);
    } catch (err) { toast(err.message, true); }
  }
  else if (t.hasAttribute("data-close") || (t.classList.contains("modal-backdrop") && e.target === t)) $("qr-modal").classList.add("hidden");
});

$("pay-btn").addEventListener("click", async () => {
  const method = document.querySelector('input[name="pay"]:checked').value;
  const slotLabel = document.querySelector(`.slot[data-slot="${CSS.escape(S.slotId)}"] b`)?.textContent || S.slotId;
  const summary = Object.entries(S.cart)
    .map(([id, q]) => `${q} × ${S.items[id].dish_name} (₹${S.items[id].price * q})`)
    .join("\n");
  if (!window.confirm(`Confirm your order?\n\n${summary}\n\nPickup slot: ${slotLabel}\nPayment: ${method}\nTotal: ${rupees(cartTotal())}`)) {
    return;
  }
  $("pay-btn").disabled = true;
  try {
    const d = await api("/api/orders", { slot_id: S.slotId, payment_method: method, cart: S.cart });
    setWallet(d.wallet_balance);
    toast("Order " + d.order.order_id + " booked for " + d.order.slot + ".");
    S.cart = {};
    await Promise.all([loadMenu(), loadSlots(), loadOrders()]);
    openQr(d.order.order_id);
  } catch (err) {
    toast(err.message, true);
    await Promise.all([loadMenu(), loadSlots()]).catch(() => {});
  } finally { renderCart(); }
});

["f-q", "f-veg", "f-cat"].forEach((id) => $(id).addEventListener("input", () => {
  clearTimeout(S.filterTimer); S.filterTimer = setTimeout(() => loadMenu().catch((e) => toast(e.message, true)), 200);
}));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("qr-modal").classList.add("hidden"); });

(async () => {
  try {
    const me = await api("/api/me"); setWallet(me.wallet_balance);
    await Promise.all([loadMenu(true), loadSlots(), loadOrders()]);
  } catch (e) { toast(e.message, true); }
  setInterval(() => { if (!document.hidden) Promise.all([loadMenu(), loadSlots(), loadOrders()]).catch(() => {}); }, 6000);
})();
