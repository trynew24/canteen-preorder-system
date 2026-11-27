const NEXT = { pending: ["preparing", "Start cooking"], preparing: ["ready", "Mark ready"], ready: ["picked_up", "Mark picked up"] };
const $k = (id) => document.getElementById(id);

function orderCard(o) {
  const n = NEXT[o.status];
  return `<article class="order">
    <div class="order-head"><span class="order-id">${esc(o.order_id)}</span>${statusBadge(o.status)}</div>
    <div class="muted">${esc(o.student_name)} · ${esc(o.slot)}</div>
    <ul>${o.items.map((i) => `<li>${i.quantity} × ${esc(i.dish_name)}</li>`).join("")}</ul>
    ${n ? `<div class="order-actions"><button class="btn ${o.status === "ready" ? "btn-quiet" : "btn-primary"} btn-sm"
      data-order="${esc(o.order_id)}" data-to="${n[0]}">${n[1]}</button></div>` : ""}
  </article>`;
}

function slotCard(s) {
  const adv = [];
  if (s.pending) adv.push(`<button class="btn btn-warn btn-sm" data-slot="${esc(s.slot_id)}" data-from="pending">Start all pending (${s.pending})</button>`);
  if (s.preparing) adv.push(`<button class="btn btn-primary btn-sm" data-slot="${esc(s.slot_id)}" data-from="preparing">Mark all preparing ready (${s.preparing})</button>`);
  return `<section class="kds-slot">
    <div class="kds-slot-head"><h3>${esc(s.slot)}</h3><span class="muted">${s.orders.length} active · load ${s.booked_count}/${s.max_orders}${s.picked_up_count ? ` (${s.picked_up_count} picked up)` : ""}</span></div>
    <div class="batch"><b>Cook this batch</b>${s.batch.map((b) =>
      `<div class="batch-row"><span>${esc(b.dish_name)}</span><strong>× ${b.quantity}</strong></div>`).join("")}</div>
    <div class="order-actions">${adv.join("")}</div>
    ${s.orders.map(orderCard).join("")}
  </section>`;
}

async function refresh() {
  try {
    const d = await api("/api/kitchen/board");
    $k("kds-slots").innerHTML = d.slots.length ? d.slots.map(slotCard).join("")
      : '<p class="empty">No orders to cook. New pre-orders appear here within a few seconds.</p>';
    $k("kds-ready").innerHTML = d.ready.length ? d.ready.map(orderCard).join("")
      : '<p class="empty">Nothing waiting for pickup.</p>';
    $k("kds-updated").textContent = "Updated " + new Date().toLocaleTimeString();
  } catch (e) { $k("kds-updated").textContent = e.message; }
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  try {
    if (b.dataset.order) {
      await api(`/api/orders/${encodeURIComponent(b.dataset.order)}/status`, { status: b.dataset.to });
    } else if (b.dataset.slot) {
      const d = await api(`/api/kitchen/slots/${encodeURIComponent(b.dataset.slot)}/advance`, { from_status: b.dataset.from });
      toast(d.updated + " order" + (d.updated === 1 ? "" : "s") + " moved to " + d.to + ".");
    } else return;
  } catch (err) { toast(err.message, true); }
  refresh();
});

refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 4000);
