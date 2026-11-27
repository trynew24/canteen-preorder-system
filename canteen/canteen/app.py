"""CPT Canteen Pre-Order & Queue Management System (Flask + SQLite).

Every price, total, stock level, slot count, wallet balance and status
transition is decided here on the server. The browser only sends *what*
the student wants (item ids + quantities, slot id, payment method).
"""
import hmac
import io
import os
import secrets
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEXT_STATUS = {"pending": "preparing", "preparing": "ready", "ready": "collected"}
HOME = {"student": "/student", "kitchen": "/kitchen", "admin": "/admin"}
LOW_STOCK_AT = 6
MAX_QTY_PER_ITEM = 10
MAX_TOPUP = 500


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE_DIR, "instance", "secret.key")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_secret_key(),
    DATABASE=os.environ.get("DATABASE", os.path.join(BASE_DIR, "canteen.db")),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    DEMO_MODE=os.environ.get("DEMO_MODE", "1") == "1",  # quick-login buttons + wallet top-up
)
app.teardown_appcontext(db.close_db)


@app.cli.command("init-db")
def init_db_command():
    """Create (or reset) canteen.db and load the sample data."""
    db.init_db()
    print("Initialised", app.config["DATABASE"])


# ---------------------------------------------------------------- helpers
class ApiError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify(error=e.message), e.code


def wants_json():
    return request.path.startswith("/api/")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def _load_user_and_check_csrf():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = db.get_db().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if g.user is None:
            session.clear()
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
        expected = session.get("csrf", "")
        if not sent or not expected or not hmac.compare_digest(sent, expected):
            if wants_json():
                return jsonify(error="Session expired. Reload the page."), 400
            abort(400, "Invalid or missing CSRF token. Go back and reload the page.")


@app.after_request
def _no_cache_api(resp):
    if request.path.startswith("/api/") or request.path.startswith("/orders/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                if wants_json():
                    return jsonify(error="Please sign in."), 401
                return redirect(url_for("login"))
            if roles and g.user["role"] not in roles:
                if wants_json():
                    return jsonify(error="You do not have access to this action."), 403
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def stock_status(row):
    if not row["is_available"] or row["stock_qty"] <= 0:
        return "out_of_stock"
    return "low_stock" if row["stock_qty"] <= LOW_STOCK_AT else "available"


def menu_json(r):
    return {"item_id": r["item_id"], "dish_name": r["dish_name"], "category": r["category"],
            "price": r["price"], "prep_mins": r["prep_mins"], "stock_qty": r["stock_qty"],
            "is_available": bool(r["is_available"]), "veg": bool(r["veg"]),
            "description": r["description"], "stock_status": stock_status(r)}


def slot_json(r):
    left = r["max_capacity"] - r["booked_count"]
    return {"slot_id": r["slot_id"], "start_time": r["start_time"], "end_time": r["end_time"],
            "max_capacity": r["max_capacity"], "booked_count": r["booked_count"],
            "spots_left": max(left, 0), "is_full": left <= 0}


def fetch_orders(where="1=1", params=(), order="o.created_at DESC"):
    con = db.get_db()
    rows = con.execute(
        "SELECT o.*, s.start_time, s.end_time, u.name AS student_name, u.login_id "
        "FROM orders o JOIN time_slots s ON s.slot_id=o.slot_id JOIN users u ON u.user_id=o.user_id "
        "WHERE %s ORDER BY %s" % (where, order), params).fetchall()   # `where`/`order` are internal literals
    if not rows:
        return []
    ids = [r["order_id"] for r in rows]
    items = con.execute(
        "SELECT * FROM order_items WHERE order_id IN (%s) ORDER BY id" % ",".join("?" * len(ids)), ids).fetchall()
    by_order = {}
    for it in items:
        by_order.setdefault(it["order_id"], []).append(
            {"item_id": it["item_id"], "dish_name": it["dish_name"], "quantity": it["quantity"],
             "unit_price": it["unit_price"]})
    return [{"order_id": r["order_id"], "slot_id": r["slot_id"], "slot": r["start_time"] + "–" + r["end_time"],
             "start_time": r["start_time"], "student_name": r["student_name"], "login_id": r["login_id"],
             "total_amount": r["total_amount"], "payment_method": r["payment_method"], "status": r["status"],
             "qr_token": r["qr_token"], "created_at": r["created_at"], "collected_at": r["collected_at"],
             "items": by_order.get(r["order_id"], [])} for r in rows]


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send a JSON object.")
    return data


def to_int(value, label, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ApiError("%s must be a whole number." % label)
    if isinstance(value, bool) or n < lo or n > hi:
        raise ApiError("%s must be between %d and %d." % (label, lo, hi))
    return n


# ------------------------------------------------------------ auth + pages
@app.get("/")
def index():
    return redirect(HOME[g.user["role"]] if g.user else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if g.user:
            return redirect(HOME[g.user["role"]])
        return render_template("login.html", demo=app.config["DEMO_MODE"], active=None)
    login_id = (request.form.get("login_id") or "").strip()
    password = request.form.get("password") or ""
    row = db.get_db().execute("SELECT * FROM users WHERE login_id=?", (login_id,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        flash("Register number / username or password is incorrect.")
        return render_template("login.html", demo=app.config["DEMO_MODE"], active=None), 401
    session.clear()                      # prevents session fixation
    session["user_id"] = row["user_id"]
    csrf_token()
    return redirect(HOME[row["role"]])


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/student")
@login_required("student")
def student_page():
    return render_template("student.html", active="student", demo=app.config["DEMO_MODE"])


@app.get("/kitchen")
@login_required("kitchen", "admin")
def kitchen_page():
    return render_template("kitchen.html", active="kitchen")


@app.get("/admin")
@login_required("admin")
def admin_page():
    return render_template("admin.html", active="admin")


@app.errorhandler(403)
def _forbidden(_e):
    return render_template("error.html", code=403, active=None,
                           message="Your account cannot open this portal."), 403


# ------------------------------------------------------------ student API
@app.get("/api/me")
@login_required()
def api_me():
    u = g.user
    return jsonify(user_id=u["user_id"], name=u["name"], role=u["role"], wallet_balance=u["wallet_balance"])


@app.get("/api/menu")
@login_required()
def api_menu():
    con = db.get_db()
    q = (request.args.get("q") or "").strip().lower()
    veg = request.args.get("veg", "all")
    cat = request.args.get("category", "all")
    rows = con.execute("SELECT * FROM menu_items ORDER BY category, dish_name").fetchall()
    categories = sorted({r["category"] for r in rows})
    out = []
    for r in rows:
        if q and q not in (r["dish_name"] + " " + r["description"]).lower():
            continue
        if veg == "veg" and not r["veg"]:
            continue
        if veg == "nonveg" and r["veg"]:
            continue
        if cat != "all" and r["category"] != cat:
            continue
        out.append(menu_json(r))
    return jsonify(items=out, categories=categories)


@app.get("/api/slots")
@login_required()
def api_slots():
    rows = db.get_db().execute("SELECT * FROM time_slots ORDER BY start_time").fetchall()
    return jsonify(slots=[slot_json(r) for r in rows])


@app.post("/api/wallet/topup")
@login_required("student")
def api_topup():
    if not app.config["DEMO_MODE"]:
        raise ApiError("Wallet top-up is handled at the canteen counter.", 403)
    amount = to_int(json_body().get("amount"), "Amount", 10, MAX_TOPUP)
    con = db.get_db()
    con.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id=?", (amount, g.user["user_id"]))
    bal = con.execute("SELECT wallet_balance FROM users WHERE user_id=?", (g.user["user_id"],)).fetchone()[0]
    return jsonify(wallet_balance=bal)


@app.post("/api/orders")
@login_required("student")
def api_place_order():
    data = json_body()
    slot_id = data.get("slot_id")
    method = data.get("payment_method")
    cart = data.get("cart")
    if method not in ("UPI", "Wallet"):
        raise ApiError("Choose UPI Instant or Campus Wallet.")
    if not isinstance(slot_id, str) or not slot_id:
        raise ApiError("Select a 15-minute pickup slot.")
    if not isinstance(cart, dict):
        raise ApiError("Your cart is empty.")
    lines = {}
    for k, v in cart.items():
        item_id = to_int(k, "Item", 1, 10**6)
        qty = to_int(v, "Quantity", 0, MAX_QTY_PER_ITEM)
        if qty:
            lines[item_id] = qty
    if not lines:
        raise ApiError("Your cart is empty.")

    con = db.get_db()
    con.execute("BEGIN IMMEDIATE")        # take the write lock: check-and-update is atomic
    try:
        slot = con.execute("SELECT * FROM time_slots WHERE slot_id=?", (slot_id,)).fetchone()
        if slot is None:
            raise ApiError("That pickup slot does not exist.", 404)

        total, priced = 0, []
        for item_id in sorted(lines):
            qty = lines[item_id]
            m = con.execute("SELECT * FROM menu_items WHERE item_id=?", (item_id,)).fetchone()
            if m is None or not m["is_available"]:
                raise ApiError("%s is not available right now." % (m["dish_name"] if m else "An item"), 409)
            cur = con.execute("UPDATE menu_items SET stock_qty = stock_qty - ? "
                              "WHERE item_id=? AND is_available=1 AND stock_qty >= ?", (qty, item_id, qty))
            if cur.rowcount != 1:
                raise ApiError(("%s is sold out." % m["dish_name"]) if m["stock_qty"] <= 0
                               else "Only %d left of %s." % (m["stock_qty"], m["dish_name"]), 409)
            total += m["price"] * qty              # price always comes from the database
            priced.append((m, qty))

        cur = con.execute("UPDATE time_slots SET booked_count = booked_count + 1 "
                          "WHERE slot_id=? AND booked_count < max_capacity", (slot_id,))
        if cur.rowcount != 1:
            raise ApiError("That slot is full. Pick another pickup window.", 409)

        payment_ref = None
        if method == "Wallet":
            cur = con.execute("UPDATE users SET wallet_balance = wallet_balance - ? "
                              "WHERE user_id=? AND wallet_balance >= ?", (total, g.user["user_id"], total))
            if cur.rowcount != 1:
                raise ApiError("Wallet balance is too low for ₹%d. Top up or pay with UPI." % total, 402)
        else:
            payment_ref = "UPI" + secrets.token_hex(5).upper()   # simulated gateway reference

        n = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(order_id,5) AS INTEGER)),1000)+1 FROM orders").fetchone()[0]
        order_id = "ORD-%d" % n
        qr_token = "CPT-%d-%s" % (n, secrets.token_hex(4).upper())
        con.execute("INSERT INTO orders (order_id,user_id,slot_id,total_amount,payment_method,payment_ref,"
                    "status,qr_token,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (order_id, g.user["user_id"], slot_id, total, method, payment_ref, "pending", qr_token,
                     db.now_iso()))
        for m, qty in priced:
            con.execute("INSERT INTO order_items (order_id,item_id,dish_name,quantity,unit_price) VALUES (?,?,?,?,?)",
                        (order_id, m["item_id"], m["dish_name"], qty, m["price"]))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    bal = con.execute("SELECT wallet_balance FROM users WHERE user_id=?", (g.user["user_id"],)).fetchone()[0]
    order = fetch_orders("o.order_id=?", (order_id,))[0]
    return jsonify(order=order, wallet_balance=bal, payment_ref=payment_ref), 201


@app.get("/api/orders/mine")
@login_required("student")
def api_my_orders():
    return jsonify(orders=fetch_orders("o.user_id=?", (g.user["user_id"],)))


# ------------------------------------------------------------------- QR
def make_qr_svg(token):
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(token, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        # Fallback when `qrcode` is not installed: a clear placeholder that still shows the token
        # so staff can type it into the scanner box.
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 120" width="260" height="120">'
                '<rect width="260" height="120" fill="#fff" stroke="#0f5b4a" stroke-width="3"/>'
                '<text x="130" y="44" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#14201c">'
                'QR library not installed</text>'
                '<text x="130" y="76" text-anchor="middle" font-family="monospace" font-size="15" font-weight="700" '
                'fill="#0f5b4a">%s</text></svg>' % token)


def _order_for_qr(order_id):
    row = db.get_db().execute("SELECT order_id, user_id, qr_token FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None or (g.user["role"] == "student" and row["user_id"] != g.user["user_id"]):
        abort(404)
    return row


@app.get("/orders/<order_id>/qr.svg")
@login_required()
def order_qr_svg(order_id):
    return Response(make_qr_svg(_order_for_qr(order_id)["qr_token"]), mimetype="image/svg+xml")


@app.get("/orders/<order_id>/qr.png")
@login_required()
def order_qr_png(order_id):
    token = _order_for_qr(order_id)["qr_token"]
    try:
        import qrcode
        buf = io.BytesIO()
        qrcode.make(token, box_size=10, border=2).save(buf, format="PNG")
        return Response(buf.getvalue(), mimetype="image/png")
    except Exception:
        return redirect(url_for("order_qr_svg", order_id=order_id))   # PNG needs Pillow; SVG does not


# ---------------------------------------------------------- kitchen API
@app.get("/api/kitchen/board")
@login_required("kitchen", "admin")
def api_kitchen_board():
    active = fetch_orders("o.status IN ('pending','preparing')", order="s.start_time, o.created_at")
    slots = {}
    for o in active:
        s = slots.setdefault(o["slot_id"], {"slot_id": o["slot_id"], "slot": o["slot"], "orders": [],
                                            "batch": {}, "pending": 0, "preparing": 0})
        s["orders"].append(o)
        s[o["status"]] += 1
        for it in o["items"]:
            s["batch"][it["dish_name"]] = s["batch"].get(it["dish_name"], 0) + it["quantity"]
    groups = []
    for s in sorted(slots.values(), key=lambda x: x["slot"]):
        s["batch"] = sorted(({"dish_name": k, "quantity": v} for k, v in s["batch"].items()),
                            key=lambda b: -b["quantity"])
        groups.append(s)
    ready = fetch_orders("o.status='ready'", order="s.start_time, o.created_at")
    return jsonify(slots=groups, ready=ready)


def _advance(con, order_id, expected_from, to):
    stamp = db.now_iso() if to == "collected" else None
    cur = con.execute("UPDATE orders SET status=?, collected_at=COALESCE(?, collected_at) "
                      "WHERE order_id=? AND status=?", (to, stamp, order_id, expected_from))
    return cur.rowcount == 1


@app.post("/api/orders/<order_id>/status")
@login_required("kitchen", "admin")
def api_order_status(order_id):
    target = json_body().get("status")
    con = db.get_db()
    row = con.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        raise ApiError("Order not found.", 404)
    if NEXT_STATUS.get(row["status"]) != target:
        raise ApiError("%s is %s. It can only move to %s." % (
            order_id, row["status"], NEXT_STATUS.get(row["status"], "nothing further")), 409)
    if not _advance(con, order_id, row["status"], target):   # lost a race with another staff member
        raise ApiError("Someone else just updated this order. Refresh the board.", 409)
    return jsonify(order=fetch_orders("o.order_id=?", (order_id,))[0])


@app.post("/api/kitchen/slots/<slot_id>/advance")
@login_required("kitchen", "admin")
def api_batch_advance(slot_id):
    src = json_body().get("from_status")
    if src not in NEXT_STATUS:
        raise ApiError("from_status must be pending, preparing or ready.")
    to = NEXT_STATUS[src]
    stamp = db.now_iso() if to == "collected" else None
    cur = db.get_db().execute("UPDATE orders SET status=?, collected_at=COALESCE(?, collected_at) "
                              "WHERE slot_id=? AND status=?", (to, stamp, slot_id, src))
    return jsonify(updated=cur.rowcount, to=to)


# ------------------------------------------------------------ admin API
@app.get("/api/admin/summary")
@login_required("admin")
def api_admin_summary():
    con = db.get_db()
    k = con.execute("SELECT COUNT(*) n, COALESCE(SUM(total_amount),0) rev, "
                    "SUM(status='ready') ready, SUM(status='collected') done, "
                    "SUM(status IN ('pending','preparing')) cooking FROM orders").fetchone()
    total = k["n"]
    slots = con.execute("SELECT * FROM time_slots ORDER BY start_time").fetchall()
    menu = con.execute("SELECT * FROM menu_items ORDER BY category, dish_name").fetchall()
    return jsonify(
        kpis={"total_orders": total, "revenue": k["rev"], "ready": k["ready"] or 0,
              "collected": k["done"] or 0, "cooking": k["cooking"] or 0,
              "handover_pct": round(100 * (k["done"] or 0) / total) if total else 0},
        slots=[slot_json(s) for s in slots], menu=[menu_json(m) for m in menu],
        recent=fetch_orders()[:12])


@app.post("/api/admin/verify")
@login_required("admin")
def api_admin_verify():
    token = str(json_body().get("token") or "").strip()
    if not token:
        raise ApiError("Scan a QR pass or type an order ID first.")
    con = db.get_db()
    row = con.execute("SELECT order_id, status FROM orders WHERE qr_token=? OR order_id=? COLLATE NOCASE",
                      (token, token)).fetchone()
    if row is None:
        raise ApiError("No order matches that QR token or ID.", 404)
    if row["status"] == "collected":
        raise ApiError("%s was already collected. Duplicate scan blocked." % row["order_id"], 409)
    if row["status"] != "ready":
        raise ApiError("%s is still %s. The kitchen has not marked it ready." % (row["order_id"], row["status"]), 409)
    if not _advance(con, row["order_id"], "ready", "collected"):
        raise ApiError("Duplicate scan blocked.", 409)
    return jsonify(order=fetch_orders("o.order_id=?", (row["order_id"],))[0])


@app.post("/api/admin/menu/<int:item_id>")
@login_required("admin")
def api_admin_menu(item_id):
    data = json_body()
    con = db.get_db()
    if con.execute("SELECT 1 FROM menu_items WHERE item_id=?", (item_id,)).fetchone() is None:
        raise ApiError("Dish not found.", 404)
    if "stock_qty" in data:
        con.execute("UPDATE menu_items SET stock_qty=? WHERE item_id=?",
                    (to_int(data["stock_qty"], "Stock", 0, 500), item_id))
    if "is_available" in data:
        con.execute("UPDATE menu_items SET is_available=? WHERE item_id=?", (1 if data["is_available"] else 0, item_id))
    return jsonify(item=menu_json(con.execute("SELECT * FROM menu_items WHERE item_id=?", (item_id,)).fetchone()))


@app.post("/api/admin/slots/<slot_id>")
@login_required("admin")
def api_admin_slot(slot_id):
    cap = to_int(json_body().get("max_capacity"), "Capacity", 1, 60)
    con = db.get_db()
    cur = con.execute("UPDATE time_slots SET max_capacity=? WHERE slot_id=? AND booked_count <= ?", (cap, slot_id, cap))
    if cur.rowcount != 1:
        raise ApiError("Capacity cannot be lower than the orders already booked, or the slot does not exist.", 409)
    return jsonify(slot=slot_json(con.execute("SELECT * FROM time_slots WHERE slot_id=?", (slot_id,)).fetchone()))


# Create the database automatically on first run
with app.app_context():
    if not os.path.exists(app.config["DATABASE"]):
        db.init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
