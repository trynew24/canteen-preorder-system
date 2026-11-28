const $h = (id) => document.getElementById(id);
let ORDERS = [];

function renderHistory() {
  const q = ($h("h-q").value || "").trim().toLowerCase();
  const status = $h("h-status").value;

  const filtered = ORDERS.filter((o) => {
    if (status !== "all" && o.status !== status) return false;
    if (q) {
      const hay = (o.order_id + " " + o.items.map((i) => i.dish_name).join(" ")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const nonCancelled = ORDERS.filter((o) => o.status !== "cancelled");
  const totalSpent = nonCancelled.reduce((s, o) => s + o.total_amount, 0);
  $h("hist-summary").textContent = `${ORDERS.length} order${ORDERS.length === 1 ? "" : "s"} · ${rupees(totalSpent)} spent`;

  $h("hist-list").innerHTML = filtered.length
    ? filtered.map((o) => `
      <article class="order">
        <div class="order-head"><span class="order-id">${esc(o.order_id)}</span>${statusBadge(o.status)}</div>
        <div class="muted">${esc((o.created_at || o.slot_date || "").slice(0, 10))} · Pickup ${esc(o.slot)} · ${esc(o.payment_method)} · <strong>${rupees(o.total_amount)}</strong></div>
        <ul>${o.items.map((i) => `<li>${i.quantity} × ${esc(i.dish_name)} (${rupees(i.unit_price * i.quantity)})</li>`).join("")}</ul>
        ${o.collected_at ? `<div class="muted">Picked up: ${esc(o.collected_at.replace("T", " "))}</div>` : ""}
        <div class="order-actions">
          ${o.status === "picked_up" || o.status === "cancelled" ? "" : `<button class="btn btn-primary btn-sm" data-qr="${esc(o.order_id)}">Show QR pass</button>`}
        </div>
      </article>`).join("")
    : '<p class="empty">No matching orders found.</p>';
}

function openQr(orderId) {
  const o = ORDERS.find((x) => x.order_id === orderId);
  if (!o) return;
  $h("qr-title").textContent = "Pickup pass · " + o.order_id;
  $h("qr-body").innerHTML = `<img src="/orders/${encodeURIComponent(o.order_id)}/qr.svg" alt="QR code for ${esc(o.order_id)}">
    <div class="token">${esc(o.qr_token)}</div>
    <div>${statusBadge(o.status)} <span class="muted">Slot ${esc(o.slot)} (${esc(o.slot_date)})</span></div>
    <p class="muted">${o.status === "ready" ? "Your food is ready. Show this code at the counter." : "Show this code at the counter once the order is ready."}</p>`;
  $h("qr-modal").classList.remove("hidden");
}

async function loadHistory() {
  try {
    const d = await api("/api/orders/mine");
    ORDERS = d.orders;
    renderHistory();
  } catch (err) { toast(err.message, true); }
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("button, .modal-backdrop");
  if (!t) return;
  if (t.dataset.qr) openQr(t.dataset.qr);
  else if (t.hasAttribute("data-close") || (t.classList.contains("modal-backdrop") && e.target === t)) {
    $h("qr-modal").classList.add("hidden");
  }
});

$h("h-q").addEventListener("input", renderHistory);
$h("h-status").addEventListener("input", renderHistory);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $h("qr-modal").classList.add("hidden"); });

loadHistory();
