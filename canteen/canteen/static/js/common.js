/* Shared helpers: CSRF-aware fetch, escaping, toasts, polling. */
const CSRF = document.querySelector('meta[name="csrf-token"]').content;

async function api(path, body) {
  const opts = { headers: { "Accept": "application/json" }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.headers["X-CSRF-Token"] = CSRF;
    opts.body = JSON.stringify(body);
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
const STATUS_LABEL = { pending: "Pending", preparing: "Preparing", ready: "Ready", collected: "Collected" };
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
