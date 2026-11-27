/* Shared helpers: CSRF-aware fetch, escaping, toasts, polling. */
const CSRF = document.querySelector('meta[name="csrf-token"]').content;

async function api(path, body, method = "POST") {
  const opts = { headers: { "Accept": "application/json" }, credentials: "same-origin" };
  if (body !== undefined || method !== "GET") {
    if (body !== undefined || (method !== "POST" && method !== "GET")) {
      opts.method = method;
      opts.headers["X-CSRF-Token"] = CSRF;
      if (body !== undefined && body !== null) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
  }
  const res = await fetch(path, opts);
  if (res.status === 401) { location.href = "/login"; throw new Error("Signed out"); }
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(data.error || "Something went wrong (" + res.status + ").");
  return data;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rupees = (n) => "₹" + n;
const STATUS_LABEL = {
  pending: "Pending",
  preparing: "Preparing",
  ready: "Ready",
  picked_up: "Picked up",
  cancelled: "Cancelled",
};
const statusBadge = (s) => `<span class="badge ${esc(s)}">${esc(STATUS_LABEL[s] || s)}</span>`;
const stockBadge = (s, qty) =>
  s === "out_of_stock" ? '<span class="badge out">Sold out</span>'
  : s === "low_stock" ? `<span class="badge low">Only ${qty} left</span>`
  : `<span class="badge">${qty} in stock</span>`;

function toast(msg, isErr) {
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = msg;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), isErr ? 5000 : 3200);
}

(() => {
  const btn = document.getElementById("settings-btn");
  const modal = document.getElementById("settings-modal");
  const form = document.getElementById("password-form");
  if (!btn || !modal || !form) return;

  const close = () => modal.classList.add("hidden");
  btn.addEventListener("click", () => {
    form.reset();
    modal.classList.remove("hidden");
    document.getElementById("pw-current").focus();
  });
  modal.addEventListener("click", (e) => {
    if (e.target === modal || e.target.closest("[data-close-settings]")) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const d = await api("/api/account/password", {
        current_password: document.getElementById("pw-current").value,
        new_password: document.getElementById("pw-new").value,
        confirm_password: document.getElementById("pw-confirm").value,
      });
      form.reset();
      close();
      toast(d.message || "Password updated.");
    } catch (err) {
      toast(err.message, true);
    }
  });
})();
