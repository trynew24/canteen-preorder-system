const $a = (id) => document.getElementById(id);
const on = (id, ev, fn) => { const el = $a(id); if (el) el.addEventListener(ev, fn); };

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
    const pct = Math.round((100 * s.booked_count) / s.max_orders);
    const statusText = !s.is_active ? "Paused" : s.is_expired ? "Closed" : `${s.spots_left} left`;
    return `<div class="load-row"><div class="row">
      <span><b>${esc(s.start_time)}–${esc(s.end_time)}</b> <small class="muted">${esc(s.slot_date)} · ${esc(statusText)}${s.picked_up_count ? ` · ${s.picked_up_count} picked up` : ""}</small></span>
      <span class="inline-ctrl">${s.booked_count}/<input type="number" min="1" max="200" value="${s.max_orders}" data-cap="${esc(s.id)}"
        style="width:64px;padding:2px 6px" aria-label="Max orders for ${esc(s.start_time)}">
        <button class="btn btn-quiet btn-sm" type="button" data-slot-toggle="${esc(s.id)}" data-active="${s.is_active ? 0 : 1}">${s.is_active ? "Pause" : "Activate"}</button>
        <button class="btn btn-danger btn-sm" type="button" data-del-slot="${esc(s.id)}" data-label="${esc(s.start_time)}–${esc(s.end_time)} (${esc(s.slot_date)})">Delete</button>
      </span></div>
      <div class="bar"><i class="${s.is_full ? "full" : pct >= 80 ? "warn" : ""}" style="width:${Math.min(pct, 100)}%"></i></div></div>`;
  }).join("") || '<p class="empty">No slots configured.</p>';
}

function renderUsers(users) {
  $a("users-table").innerHTML =
    "<thead><tr><th>ID</th><th>Name</th><th>Login</th><th>Role</th><th>Email</th><th>Orders</th><th>Wallet</th><th>Add money</th><th>Status</th><th>Action</th></tr></thead><tbody>" +
    users.map((u) => {
      const badge = u.is_blocked
        ? '<span class="badge blocked">Blocked</span>'
        : '<span class="badge ready">Active</span>';
      const walletCtrl = u.role === "student"
        ? `<div class="inline-ctrl"><input type="number" min="1" max="10000" placeholder="₹" data-wallet-amt="${esc(u.user_id)}" style="width:74px;padding:4px 6px" aria-label="Amount for ${esc(u.name)}"><button class="btn btn-primary btn-sm" type="button" data-add-wallet="${esc(u.user_id)}">Add</button></div>`
        : '<span class="muted">—</span>';
      const blockBtn = u.role === "admin"
        ? '<span class="muted">Protected</span>'
        : `<button class="btn ${u.is_blocked ? "btn-quiet" : "btn-danger"} btn-sm" type="button" data-block-user="${esc(u.user_id)}" data-blocked="${u.is_blocked ? 0 : 1}">${u.is_blocked ? "Unblock" : "Block"}</button>`;
      return `<tr>
        <td><code>${esc(u.user_id)}</code></td>
        <td>${esc(u.name)}</td>
        <td>${esc(u.login_id)}</td>
        <td>${esc(u.role)}</td>
        <td class="muted">${esc(u.campus_email || "—")}</td>
        <td>${u.order_count} (₹${u.total_spent})</td>
        <td><strong>₹${u.wallet_balance}</strong></td>
        <td>${walletCtrl}</td>
        <td>${badge}</td>
        <td>${blockBtn}</td>
      </tr>`;
    }).join("") + "</tbody>";
}

function renderMenu(menu) {
  $a("menu-table").innerHTML =
    "<thead><tr><th>Dish</th><th>Category</th><th>Veg</th><th>Price (₹)</th><th>Prep</th><th>Status</th><th>Stock</th><th>Actions</th></tr></thead><tbody>" +
    menu.map((m) => `<tr>
      <td><input value="${esc(m.dish_name)}" data-menu-id="${m.item_id}" data-menu-field="dish_name" style="min-width:140px;padding:4px 6px" aria-label="Name for ${esc(m.dish_name)}"></td>
      <td><input value="${esc(m.category)}" data-menu-id="${m.item_id}" data-menu-field="category" style="width:95px;padding:4px 6px" aria-label="Category for ${esc(m.dish_name)}"></td>
      <td><select data-menu-id="${m.item_id}" data-menu-field="veg" style="padding:4px 6px" aria-label="Veg for ${esc(m.dish_name)}">
        <option value="1" ${m.veg ? "selected" : ""}>Veg</option>
        <option value="0" ${!m.veg ? "selected" : ""}>Non-veg</option>
      </select></td>
      <td><input type="number" min="1" max="10000" value="${m.price}" data-menu-id="${m.item_id}" data-menu-field="price" style="width:72px;padding:4px 6px" aria-label="Price for ${esc(m.dish_name)}"></td>
      <td><input type="number" min="1" max="120" value="${m.prep_mins}" data-menu-id="${m.item_id}" data-menu-field="prep_mins" style="width:62px;padding:4px 6px" aria-label="Prep mins for ${esc(m.dish_name)}"></td>
      <td>${stockBadge(m.stock_status, m.stock_qty)}</td>
      <td><input type="number" min="0" max="500" value="${m.stock_qty}" data-stock="${m.item_id}" aria-label="Stock for ${esc(m.dish_name)}"></td>
      <td><div class="inline-ctrl">
        <button class="btn btn-quiet btn-sm" type="button" data-toggle="${m.item_id}" data-on="${m.is_available ? 0 : 1}">${m.is_available ? "Pause" : "Resume"}</button>
        <button class="btn btn-danger btn-sm" type="button" data-del-menu="${m.item_id}" data-name="${esc(m.dish_name)}">Delete</button>
      </div></td>
    </tr>`).join("") + "</tbody>";
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
    if (!$a("new-slot-date").value) {
      $a("new-slot-date").value = new Date().toISOString().slice(0, 10);
    }
    const editingSettings = document.activeElement && document.activeElement.matches("#set-start, #set-end, #set-cutoff");
    if (!editingSettings && d.settings) {
      $a("set-start").value = d.settings.afternoon_start;
      $a("set-end").value = d.settings.afternoon_end;
      $a("set-cutoff").checked = !!d.settings.enforce_cutoff;
    }
    const editing = document.activeElement && document.activeElement.matches(
      "input[data-stock], input[data-cap], input[data-wallet-amt], input[data-menu-field], select[data-menu-field]"
    );
    if (!editing) {
      renderSlots(d.slots);
      renderUsers(d.users);
      renderMenu(d.menu);
    }
  } catch (e) { toast(e.message, true); }
}

on("verify-form", "submit", async (e) => {
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

on("settings-form", "submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/admin/settings", {
      afternoon_start: $a("set-start").value,
      afternoon_end: $a("set-end").value,
      enforce_cutoff: $a("set-cutoff").checked,
    });
    toast("Hours saved and 15-min slots generated.");
    refresh();
  } catch (err) { toast(err.message, true); }
});

on("gen-slots-btn", "click", async () => {
  try {
    const d = await api("/api/admin/slots/generate", {});
    toast(d.created ? `Added ${d.created} new 0/15 slot(s).` : "All 15-min slots already exist.");
    refresh();
  } catch (err) { toast(err.message, true); }
});

on("add-slot-form", "submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/admin/slots", {
      slot_date: $a("new-slot-date").value,
      start_time: $a("new-slot-start").value,
      end_time: $a("new-slot-end").value,
      max_orders: $a("new-slot-max").value,
    });
    toast("Afternoon slot added.");
    refresh();
  } catch (err) { toast(err.message, true); }
});

on("add-kitchen-form", "submit", async (e) => {
  e.preventDefault();
  try {
    const d = await api("/api/admin/users/kitchen", {
      name: $a("new-kitchen-name").value,
      login_id: $a("new-kitchen-login").value,
      password: $a("new-kitchen-pw").value,
    });
    e.target.reset();
    toast(`Kitchen staff "${d.user.name}" added.`);
    refresh();
  } catch (err) { toast(err.message, true); }
});

on("add-dish-form", "submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/admin/menu", {
      dish_name: $a("new-dish-name").value,
      category: $a("new-dish-cat").value,
      price: $a("new-dish-price").value,
      prep_mins: $a("new-dish-prep").value,
      stock_qty: $a("new-dish-stock").value,
      veg: $a("new-dish-veg").value === "1",
      description: $a("new-dish-desc").value,
    });
    e.target.reset();
    $a("new-dish-prep").value = "5";
    $a("new-dish-stock").value = "20";
    toast("Dish added.");
    refresh();
  } catch (err) { toast(err.message, true); }
});

document.addEventListener("change", async (e) => {
  const t = e.target;
  try {
    if (t.dataset.stock) {
      await api("/api/admin/menu/" + t.dataset.stock, { stock_qty: t.value });
    } else if (t.dataset.cap) {
      await api("/api/admin/slots/" + encodeURIComponent(t.dataset.cap), { max_orders: t.value });
    } else if (t.dataset.menuField) {
      const val = t.dataset.menuField === "veg" ? t.value === "1" : t.value;
      await api("/api/admin/menu/" + t.dataset.menuId, { [t.dataset.menuField]: val });
    } else return;
    toast("Saved.");
  } catch (err) { toast(err.message, true); }
  t.blur();
  refresh();
});

document.addEventListener("click", async (e) => {
  const slotToggleBtn = e.target.closest("[data-slot-toggle]");
  if (slotToggleBtn) {
    try {
      await api("/api/admin/slots/" + encodeURIComponent(slotToggleBtn.dataset.slotToggle), {
        is_active: slotToggleBtn.dataset.active === "1",
      });
      toast("Slot updated.");
    } catch (err) { toast(err.message, true); }
    refresh();
    return;
  }
  const delSlotBtn = e.target.closest("[data-del-slot]");
  if (delSlotBtn) {
    if (!window.confirm(`Delete time slot ${delSlotBtn.dataset.label}?`)) return;
    try {
      await api("/api/admin/slots/" + encodeURIComponent(delSlotBtn.dataset.delSlot), null, "DELETE");
      toast("Time slot deleted.");
    } catch (err) { toast(err.message, true); }
    refresh();
    return;
  }
  const toggleBtn = e.target.closest("[data-toggle]");
  if (toggleBtn) {
    try { await api("/api/admin/menu/" + toggleBtn.dataset.toggle, { is_available: toggleBtn.dataset.on === "1" }); }
    catch (err) { toast(err.message, true); }
    refresh();
    return;
  }
  const delBtn = e.target.closest("[data-del-menu]");
  if (delBtn) {
    if (!window.confirm(`Delete "${delBtn.dataset.name}" from the menu?`)) return;
    try {
      await api("/api/admin/menu/" + delBtn.dataset.delMenu, null, "DELETE");
      toast("Dish deleted.");
    } catch (err) { toast(err.message, true); }
    refresh();
    return;
  }
  const walletBtn = e.target.closest("[data-add-wallet]");
  if (walletBtn) {
    const uid = walletBtn.dataset.addWallet;
    const inp = document.querySelector(`input[data-wallet-amt="${CSS.escape(uid)}"]`);
    const amt = inp ? inp.value : "";
    try {
      const d = await api(`/api/admin/users/${encodeURIComponent(uid)}/wallet`, { amount: amt });
      toast(`Added ₹${amt} to ${d.user.name}'s wallet (balance ₹${d.user.wallet_balance}).`);
      if (inp) inp.value = "";
    } catch (err) { toast(err.message, true); }
    refresh();
    return;
  }
  const blockBtn = e.target.closest("[data-block-user]");
  if (blockBtn) {
    const uid = blockBtn.dataset.blockUser;
    const block = blockBtn.dataset.blocked === "1";
    try {
      const d = await api(`/api/admin/users/${encodeURIComponent(uid)}/block`, { is_blocked: block });
      toast(`${d.user.name} ${d.user.is_blocked ? "blocked" : "unblocked"}.`);
    } catch (err) { toast(err.message, true); }
    refresh();
  }
});

refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 5000);
