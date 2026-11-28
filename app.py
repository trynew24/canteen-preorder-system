"""CPT Canteen Pre-Order & Queue Management System (Flask + SQLite).

Every price, total, stock level, slot count, wallet balance and status
transition is decided here on the server. The browser only sends *what*
the student wants (item ids + quantities, slot id, payment method).
"""
import hmac
import io
import os
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEXT_STATUS = {"pending": "preparing", "preparing": "ready", "ready": "picked_up"}
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
    SEND_FILE_MAX_AGE_DEFAULT=0,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    DEMO_MODE=False,
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
        if g.user is None or g.user["is_blocked"]:
            session.clear()
            g.user = None
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


def get_settings(con):
    row = con.execute("SELECT * FROM canteen_settings WHERE id=1").fetchone()
    if row is None:
        con.execute(
            "INSERT INTO canteen_settings (id, afternoon_start, afternoon_end, slot_minutes, default_max_orders, enforce_cutoff)"
            " VALUES (1, '12:00', '14:30', 15, 15, 1)"
        )
        row = con.execute("SELECT * FROM canteen_settings WHERE id=1").fetchone()
    return row


def format_time_12h(hhmm):
    return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


def schedule_json(settings):
    return {
        "afternoon_start": settings["afternoon_start"],
        "afternoon_end": settings["afternoon_end"],
        "start_label": format_time_12h(settings["afternoon_start"]),
        "end_label": format_time_12h(settings["afternoon_end"]),
        "slot_minutes": settings["slot_minutes"],
        "default_max_orders": settings["default_max_orders"],
        "enforce_cutoff": bool(settings["enforce_cutoff"]),
    }


def _valid_hhmm(val):
    if not isinstance(val, str) or not re.match(r"^\d{2}:\d{2}$", val):
        return False
    try:
        datetime.strptime(val, "%H:%M")
        return True
    except ValueError:
        return False


def _valid_date(val):
    if not isinstance(val, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
        return False
    try:
        datetime.strptime(val, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def slot_within_afternoon(start_time, end_time, settings):
    return (
        _valid_hhmm(start_time)
        and _valid_hhmm(end_time)
        and start_time < end_time
        and start_time >= settings["afternoon_start"]
        and end_time <= settings["afternoon_end"]
    )


def slot_is_expired(r, _settings=None):
    today = db.today_iso()
    if r["slot_date"] < today:
        return True
    if r["slot_date"] == today:
        now_hhmm = datetime.now().strftime("%H:%M")
        return now_hhmm >= r["end_time"]
    return False


def close_expired_slots(con):
    today = db.today_iso()
    now_hhmm = datetime.now().strftime("%H:%M")
    con.execute(
        "UPDATE time_slots SET is_active=0 WHERE is_active=1 AND (slot_date < ? OR (slot_date=? AND end_time <= ?))",
        (today, today, now_hhmm),
    )


def ensure_today_slots(con):
    close_expired_slots(con)
    today = db.today_iso()
    has_today = con.execute("SELECT 1 FROM time_slots WHERE slot_date=? LIMIT 1", (today,)).fetchone()
    if has_today is None:
        settings = get_settings(con)
        now_hhmm = datetime.now().strftime("%H:%M")
        pairs = db.generate_afternoon_slots(
            settings["afternoon_start"], settings["afternoon_end"], settings["slot_minutes"]
        )
        con.executemany(
            "INSERT OR IGNORE INTO time_slots (slot_date, start_time, end_time, max_orders, is_active)"
            " VALUES (?,?,?,?,?)",
            [(today, s, e, settings["default_max_orders"], 0 if e <= now_hhmm else 1) for s, e in pairs],
        )


def fetch_slots_with_counts(con, where="1=1", params=()):
    return con.execute(
        "SELECT s.*, "
        "COUNT(CASE WHEN o.status != 'cancelled' THEN 1 END) AS booked_count, "
        "COUNT(CASE WHEN o.status = 'picked_up' THEN 1 END) AS picked_up_count "
        "FROM time_slots s LEFT JOIN orders o ON o.time_slot_id = s.id "
        "WHERE %s GROUP BY s.id ORDER BY s.slot_date, s.start_time" % where,
        params,
    ).fetchall()


def slot_json(r, settings=None):
    booked = r["booked_count"] if "booked_count" in r.keys() else 0
    picked_up = r["picked_up_count"] if "picked_up_count" in r.keys() else 0
    left = r["max_orders"] - booked
    expired = slot_is_expired(r, settings) if settings is not None else False
    active = bool(r["is_active"])
    within = slot_within_afternoon(r["start_time"], r["end_time"], settings) if settings is not None else True
    return {
        "id": r["id"],
        "slot_id": r["id"],
        "slot_date": r["slot_date"],
        "start_time": r["start_time"],
        "end_time": r["end_time"],
        "max_orders": r["max_orders"],
        "is_active": active,
        "booked_count": booked,
        "picked_up_count": picked_up,
        "spots_left": max(left, 0),
        "is_full": left <= 0,
        "is_expired": expired,
        "is_bookable": active and within and not expired and left > 0,
    }


def fetch_orders(where="1=1", params=(), order="o.created_at DESC"):
    con = db.get_db()
    rows = con.execute(
        "SELECT o.*, s.slot_date, s.start_time, s.end_time, u.name AS student_name, u.login_id "
        "FROM orders o JOIN time_slots s ON s.id=o.time_slot_id JOIN users u ON u.user_id=o.user_id "
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
    return [{"order_id": r["order_id"], "time_slot_id": r["time_slot_id"], "slot_id": r["time_slot_id"],
             "slot_date": r["slot_date"], "slot": r["start_time"] + "–" + r["end_time"],
             "start_time": r["start_time"], "end_time": r["end_time"],
             "student_name": r["student_name"], "login_id": r["login_id"],
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
    sched = schedule_json(get_settings(db.get_db()))
    if request.method == "GET":
        if g.user:
            return redirect(HOME[g.user["role"]])
        return render_template("login.html", active=None, schedule=sched)
    login_id = (request.form.get("login_id") or "").strip()
    password = request.form.get("password") or ""
    remember = request.form.get("remember") == "1"
    row = db.get_db().execute("SELECT * FROM users WHERE login_id=?", (login_id,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        flash("Register number / username or password is incorrect.", "err")
        return render_template("login.html", active=None, schedule=sched), 401
    if row["is_blocked"]:
        flash("Your account has been blocked by the administrator.", "err")
        return render_template("login.html", active=None, schedule=sched), 403
    session.clear()                      # prevents session fixation
    session.permanent = remember
    session["user_id"] = row["user_id"]
    csrf_token()
    return redirect(HOME[row["role"]])


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if g.user:
            return redirect(HOME[g.user["role"]])
        return render_template("register.html", active=None)
    name = (request.form.get("name") or "").strip()
    login_id = (request.form.get("login_id") or "").strip()
    campus_email = (request.form.get("campus_email") or "").strip() or None
    password = request.form.get("password") or ""
    if not name or not login_id or len(password) < 4:
        flash("Enter your full name, register number, and a password (at least 4 characters).", "err")
        return render_template("register.html", active=None), 400
    con = db.get_db()
    if con.execute("SELECT 1 FROM users WHERE login_id=?", (login_id,)).fetchone() is not None:
        flash("That register number / username is already registered.", "err")
        return render_template("register.html", active=None), 409
    n = con.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(user_id,5) AS INTEGER)),1000)+1 FROM users "
        "WHERE user_id LIKE 'USR-%' AND CAST(SUBSTR(user_id,5) AS INTEGER) >= 1000"
    ).fetchone()[0]
    user_id = "USR-%d" % n
    con.execute(
        "INSERT INTO users (user_id,name,role,login_id,password_hash,campus_email,wallet_balance,is_blocked,created_at)"
        " VALUES (?,?,?,?,?,?,0,0,?)",
        (user_id, name, "student", login_id, generate_password_hash(password), campus_email, db.now_iso()),
    )
    flash("ACCOUNT CREATED SUCCESSFULLY. TRY SIGNING IN WITH THE NEW ACCOUNT.", "ok")
    return redirect(url_for("login"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/student")
@login_required("student")
def student_page():
    sched = schedule_json(get_settings(db.get_db()))
    return render_template("student.html", active="student", schedule=sched)


@app.get("/history")
@login_required("student")
def history_page():
    return render_template("history.html", active="history")


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


@app.post("/api/account/password")
@login_required()
def api_change_password():
    data = json_body()
    current = data.get("current_password") or ""
    new_pw = data.get("new_password") or ""
    confirm = data.get("confirm_password") or ""
    if not current or not check_password_hash(g.user["password_hash"], current):
        raise ApiError("Current password is incorrect.", 403)
    if len(new_pw) < 4:
        raise ApiError("New password must be at least 4 characters.")
    if new_pw != confirm:
        raise ApiError("New passwords do not match.")
    if new_pw == current:
        raise ApiError("New password must be different from your current password.")
    db.get_db().execute(
        "UPDATE users SET password_hash=? WHERE user_id=?",
        (generate_password_hash(new_pw), g.user["user_id"]),
    )
    return jsonify(ok=True, message="Password updated.")


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
    con = db.get_db()
    ensure_today_slots(con)
    settings = get_settings(con)
    today = db.today_iso()
    rows = fetch_slots_with_counts(con, "s.slot_date = ?", (today,))
    out = []
    for r in rows:
        if g.user["role"] == "student":
            if not r["is_active"] or not slot_within_afternoon(r["start_time"], r["end_time"], settings):
                continue
        out.append(slot_json(r, settings))
    has_active_today = any(s["is_bookable"] for s in out)
    return jsonify(slots=out, schedule=schedule_json(settings), has_active_today=has_active_today, today=today)


@app.post("/api/wallet/topup")
@login_required("student")
def api_topup():
    raise ApiError("Only admin can add money to your campus wallet.", 403)


@app.post("/api/orders")
@login_required("student")
def api_place_order():
    data = json_body()
    raw_slot_id = data.get("time_slot_id") if data.get("time_slot_id") is not None else data.get("slot_id")
    time_slot_id = to_int(raw_slot_id, "Pickup slot", 1, 10**9)
    method = data.get("payment_method")
    cart = data.get("cart")
    if method not in ("UPI", "Wallet"):
        raise ApiError("Choose UPI Instant or Campus Wallet.")
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
        settings = get_settings(con)
        slot = con.execute("SELECT * FROM time_slots WHERE id=?", (time_slot_id,)).fetchone()
        if slot is None:
            raise ApiError("That pickup slot does not exist.", 404)
        if not slot["is_active"]:
            raise ApiError("That pickup slot is currently inactive.", 409)
        if not slot_within_afternoon(slot["start_time"], slot["end_time"], settings):
            raise ApiError(
                "Pre-orders are available only for afternoon pickup slots (%s – %s)."
                % (format_time_12h(settings["afternoon_start"]), format_time_12h(settings["afternoon_end"])),
                409,
            )
        if slot_is_expired(slot, settings):
            raise ApiError("Afternoon cutoff has passed for that pickup slot.", 409)

        # Count all non-cancelled orders (pending, preparing, ready, picked_up) toward slot capacity
        booked = con.execute(
            "SELECT COUNT(*) FROM orders WHERE time_slot_id=? AND status != 'cancelled'", (time_slot_id,)
        ).fetchone()[0]
        if booked >= slot["max_orders"]:
            raise ApiError("That slot is full. Pick another afternoon pickup window.", 409)

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

        payment_ref = None
        if method == "Wallet":
            cur = con.execute("UPDATE users SET wallet_balance = wallet_balance - ? "
                              "WHERE user_id=? AND wallet_balance >= ?", (total, g.user["user_id"], total))
            if cur.rowcount != 1:
                raise ApiError("Wallet balance is too low for ₹%d. Ask admin to add balance or pay with UPI." % total, 402)
        else:
            payment_ref = "UPI" + secrets.token_hex(5).upper()   # simulated gateway reference

        n = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(order_id,5) AS INTEGER)),1000)+1 FROM orders").fetchone()[0]
        order_id = "ORD-%d" % n
        qr_token = "CPT-%d-%s" % (n, secrets.token_hex(4).upper())
        con.execute("INSERT INTO orders (order_id,user_id,time_slot_id,total_amount,payment_method,payment_ref,"
                    "status,qr_token,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (order_id, g.user["user_id"], time_slot_id, total, method, payment_ref, "pending", qr_token,
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


@app.post("/api/orders/<order_id>/cancel")
@login_required("student")
def api_cancel_order(order_id):
    con = db.get_db()
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT * FROM orders WHERE order_id=? AND user_id=?",
                          (order_id, g.user["user_id"])).fetchone()
        if row is None:
            raise ApiError("Order not found.", 404)
        if row["status"] != "pending":
            raise ApiError("Only pending orders can be cancelled.", 409)
        con.execute("UPDATE orders SET status='cancelled' WHERE order_id=?", (order_id,))
        items = con.execute("SELECT item_id, quantity FROM order_items WHERE order_id=?", (order_id,)).fetchall()
        for it in items:
            con.execute("UPDATE menu_items SET stock_qty = stock_qty + ? WHERE item_id=?",
                        (it["quantity"], it["item_id"]))
        if row["payment_method"] == "Wallet":
            con.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id=?",
                        (row["total_amount"], g.user["user_id"]))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    bal = con.execute("SELECT wallet_balance FROM users WHERE user_id=?", (g.user["user_id"],)).fetchone()[0]
    return jsonify(order=fetch_orders("o.order_id=?", (order_id,))[0], wallet_balance=bal)


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
    con = db.get_db()
    ensure_today_slots(con)
    active = fetch_orders("o.status IN ('pending','preparing')", order="s.slot_date, s.start_time, o.created_at")
    slot_rows = {
        r["id"]: slot_json(r)
        for r in fetch_slots_with_counts(con, "s.slot_date >= ?", (db.today_iso(),))
    }
    slots = {}
    for o in active:
        sid = o["time_slot_id"]
        meta = slot_rows.get(sid, {})
        s = slots.setdefault(sid, {
            "slot_id": sid, "slot_date": o["slot_date"], "slot": o["slot"],
            "start_time": o["start_time"], "orders": [], "batch": {},
            "pending": 0, "preparing": 0,
            "booked_count": meta.get("booked_count", 0),
            "picked_up_count": meta.get("picked_up_count", 0),
            "max_orders": meta.get("max_orders", 0),
        })
        s["orders"].append(o)
        s[o["status"]] += 1
        for it in o["items"]:
            s["batch"][it["dish_name"]] = s["batch"].get(it["dish_name"], 0) + it["quantity"]
    groups = []
    for s in sorted(slots.values(), key=lambda x: (x["slot_date"], x["start_time"])):
        s["batch"] = sorted(({"dish_name": k, "quantity": v} for k, v in s["batch"].items()),
                            key=lambda b: -b["quantity"])
        groups.append(s)
    ready = fetch_orders("o.status='ready'", order="s.slot_date, s.start_time, o.created_at")
    return jsonify(slots=groups, ready=ready)


def _advance(con, order_id, expected_from, to):
    stamp = db.now_iso() if to == "picked_up" else None
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


@app.post("/api/kitchen/slots/<int:slot_id>/advance")
@login_required("kitchen", "admin")
def api_batch_advance(slot_id):
    src = json_body().get("from_status")
    if src not in NEXT_STATUS:
        raise ApiError("from_status must be pending, preparing or ready.")
    to = NEXT_STATUS[src]
    stamp = db.now_iso() if to == "picked_up" else None
    cur = db.get_db().execute("UPDATE orders SET status=?, collected_at=COALESCE(?, collected_at) "
                              "WHERE time_slot_id=? AND status=?", (to, stamp, slot_id, src))
    return jsonify(updated=cur.rowcount, to=to)


def user_json(r):
    return {"user_id": r["user_id"], "name": r["name"], "role": r["role"],
            "login_id": r["login_id"], "campus_email": r["campus_email"],
            "wallet_balance": r["wallet_balance"], "is_blocked": bool(r["is_blocked"]),
            "created_at": r["created_at"],
            "order_count": r["order_count"] if "order_count" in r.keys() else 0,
            "total_spent": r["total_spent"] if "total_spent" in r.keys() else 0}


# ------------------------------------------------------------ admin API
@app.get("/api/admin/summary")
@login_required("admin")
def api_admin_summary():
    con = db.get_db()
    ensure_today_slots(con)
    settings = get_settings(con)
    k = con.execute("SELECT SUM(status != 'cancelled') n, "
                    "COALESCE(SUM(CASE WHEN status != 'cancelled' THEN total_amount ELSE 0 END),0) rev, "
                    "SUM(status='ready') ready, SUM(status='picked_up') done, "
                    "SUM(status IN ('pending','preparing')) cooking FROM orders").fetchone()
    total = k["n"] or 0
    slots = fetch_slots_with_counts(con, "s.slot_date >= ?", (db.today_iso(),))
    menu = con.execute("SELECT * FROM menu_items ORDER BY category, dish_name").fetchall()
    users = con.execute(
        "SELECT u.*, COUNT(CASE WHEN o.status != 'cancelled' THEN 1 END) AS order_count, "
        "COALESCE(SUM(CASE WHEN o.status != 'cancelled' THEN o.total_amount ELSE 0 END),0) AS total_spent "
        "FROM users u LEFT JOIN orders o ON o.user_id=u.user_id "
        "GROUP BY u.user_id ORDER BY CASE u.role WHEN 'admin' THEN 0 WHEN 'kitchen' THEN 1 ELSE 2 END, u.user_id"
    ).fetchall()
    return jsonify(
        kpis={"total_orders": total, "revenue": k["rev"], "ready": k["ready"] or 0,
              "picked_up": k["done"] or 0, "cooking": k["cooking"] or 0,
              "handover_pct": round(100 * (k["done"] or 0) / total) if total else 0},
        settings=schedule_json(settings),
        slots=[slot_json(s, settings) for s in slots], menu=[menu_json(m) for m in menu],
        users=[user_json(u) for u in users],
        recent=fetch_orders()[:12])


@app.post("/api/admin/orders/clear")
@login_required("admin")
def api_admin_clear_orders():
    con = db.get_db()
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute("DELETE FROM orders WHERE status IN ('picked_up', 'cancelled')")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return jsonify(deleted=cur.rowcount)


@app.post("/api/admin/users/<user_id>/wallet")
@login_required("admin")
def api_admin_user_wallet(user_id):
    amount = to_int(json_body().get("amount"), "Amount", 1, 10000)
    con = db.get_db()
    cur = con.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id=?", (amount, user_id))
    if cur.rowcount != 1:
        raise ApiError("User not found.", 404)
    row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return jsonify(user=user_json(row))


@app.post("/api/admin/users/kitchen")
@login_required("admin")
def api_admin_create_kitchen():
    data = json_body()
    name = str(data.get("name") or "").strip()
    login_id = str(data.get("login_id") or "").strip()
    password = data.get("password") or ""
    if not name or not login_id or len(password) < 4:
        raise ApiError("Enter staff name, username, and a password (at least 4 characters).")
    con = db.get_db()
    if con.execute("SELECT 1 FROM users WHERE login_id=?", (login_id,)).fetchone() is not None:
        raise ApiError("That username is already taken.", 409)
    n = con.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(user_id,5) AS INTEGER)),1000)+1 FROM users "
        "WHERE user_id LIKE 'USR-%' AND CAST(SUBSTR(user_id,5) AS INTEGER) >= 1000"
    ).fetchone()[0]
    user_id = "USR-%d" % n
    con.execute(
        "INSERT INTO users (user_id,name,role,login_id,password_hash,campus_email,wallet_balance,is_blocked,created_at)"
        " VALUES (?,?,?,?,?,NULL,0,0,?)",
        (user_id, name, "kitchen", login_id, generate_password_hash(password), db.now_iso()),
    )
    row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return jsonify(user=user_json(row)), 201


@app.post("/api/admin/users/<user_id>/block")
@login_required("admin")
def api_admin_user_block(user_id):
    if user_id == g.user["user_id"]:
        raise ApiError("You cannot block your own admin account.", 400)
    blocked = 1 if json_body().get("is_blocked") else 0
    con = db.get_db()
    cur = con.execute("UPDATE users SET is_blocked=? WHERE user_id=?", (blocked, user_id))
    if cur.rowcount != 1:
        raise ApiError("User not found.", 404)
    row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return jsonify(user=user_json(row))


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
    if row["status"] == "picked_up":
        raise ApiError("%s was already picked up. Duplicate scan blocked." % row["order_id"], 409)
    if row["status"] == "cancelled":
        raise ApiError("%s was cancelled." % row["order_id"], 409)
    if row["status"] != "ready":
        raise ApiError("%s is still %s. The kitchen has not marked it ready." % (row["order_id"], row["status"]), 409)
    if not _advance(con, row["order_id"], "ready", "picked_up"):
        raise ApiError("Duplicate scan blocked.", 409)
    return jsonify(order=fetch_orders("o.order_id=?", (row["order_id"],))[0])


@app.post("/api/admin/menu")
@login_required("admin")
def api_admin_menu_create():
    data = json_body()
    dish_name = str(data.get("dish_name") or "").strip()
    category = str(data.get("category") or "").strip()
    description = str(data.get("description") or "").strip()
    if not dish_name:
        raise ApiError("Dish name is required.")
    if not category:
        raise ApiError("Category is required.")
    price = to_int(data.get("price"), "Price", 1, 10000)
    prep_mins = to_int(data.get("prep_mins", 5), "Prep time", 1, 120)
    stock_qty = to_int(data.get("stock_qty", 0), "Stock", 0, 500)
    veg = 1 if data.get("veg", True) else 0
    is_available = 1 if data.get("is_available", True) else 0
    con = db.get_db()
    cur = con.execute(
        "INSERT INTO menu_items (dish_name,category,price,prep_mins,stock_qty,is_available,veg,description)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (dish_name, category, price, prep_mins, stock_qty, is_available, veg, description),
    )
    row = con.execute("SELECT * FROM menu_items WHERE item_id=?", (cur.lastrowid,)).fetchone()
    return jsonify(item=menu_json(row)), 201


@app.post("/api/admin/menu/<int:item_id>")
@login_required("admin")
def api_admin_menu(item_id):
    data = json_body()
    con = db.get_db()
    if con.execute("SELECT 1 FROM menu_items WHERE item_id=?", (item_id,)).fetchone() is None:
        raise ApiError("Dish not found.", 404)
    if "dish_name" in data:
        name = str(data["dish_name"] or "").strip()
        if not name:
            raise ApiError("Dish name cannot be empty.")
        con.execute("UPDATE menu_items SET dish_name=? WHERE item_id=?", (name, item_id))
    if "category" in data:
        cat = str(data["category"] or "").strip()
        if not cat:
            raise ApiError("Category cannot be empty.")
        con.execute("UPDATE menu_items SET category=? WHERE item_id=?", (cat, item_id))
    if "price" in data:
        con.execute("UPDATE menu_items SET price=? WHERE item_id=?",
                    (to_int(data["price"], "Price", 1, 10000), item_id))
    if "prep_mins" in data:
        con.execute("UPDATE menu_items SET prep_mins=? WHERE item_id=?",
                    (to_int(data["prep_mins"], "Prep time", 1, 120), item_id))
    if "stock_qty" in data:
        con.execute("UPDATE menu_items SET stock_qty=? WHERE item_id=?",
                    (to_int(data["stock_qty"], "Stock", 0, 500), item_id))
    if "is_available" in data:
        con.execute("UPDATE menu_items SET is_available=? WHERE item_id=?", (1 if data["is_available"] else 0, item_id))
    if "veg" in data:
        con.execute("UPDATE menu_items SET veg=? WHERE item_id=?", (1 if data["veg"] else 0, item_id))
    if "description" in data:
        con.execute("UPDATE menu_items SET description=? WHERE item_id=?",
                    (str(data["description"] or "").strip(), item_id))
    return jsonify(item=menu_json(con.execute("SELECT * FROM menu_items WHERE item_id=?", (item_id,)).fetchone()))


@app.delete("/api/admin/menu/<int:item_id>")
@login_required("admin")
def api_admin_menu_delete(item_id):
    con = db.get_db()
    if con.execute("SELECT 1 FROM menu_items WHERE item_id=?", (item_id,)).fetchone() is None:
        raise ApiError("Dish not found.", 404)
    if con.execute("SELECT 1 FROM order_items WHERE item_id=? LIMIT 1", (item_id,)).fetchone() is not None:
        raise ApiError("Cannot delete a dish that has existing orders. Pause it instead.", 409)
    con.execute("DELETE FROM menu_items WHERE item_id=?", (item_id,))
    return jsonify(deleted=item_id)


@app.post("/api/admin/slots")
@login_required("admin")
def api_admin_slot_create():
    data = json_body()
    con = db.get_db()
    settings = get_settings(con)
    slot_date = str(data.get("slot_date") or db.today_iso()).strip()
    start_time = str(data.get("start_time") or "").strip()
    end_time = str(data.get("end_time") or "").strip()
    if not _valid_date(slot_date):
        raise ApiError("Slot date must be YYYY-MM-DD.")
    if not slot_within_afternoon(start_time, end_time, settings):
        raise ApiError(
            "Afternoon slots must be within %s – %s (start < end)."
            % (settings["afternoon_start"], settings["afternoon_end"])
        )
    max_orders = to_int(data.get("max_orders", settings["default_max_orders"]), "Max orders", 1, 200)
    now_hhmm = datetime.now().strftime("%H:%M")
    is_active = 0 if (slot_date < db.today_iso() or (slot_date == db.today_iso() and end_time <= now_hhmm)) else (1 if data.get("is_active", True) else 0)
    if con.execute(
        "SELECT 1 FROM time_slots WHERE slot_date=? AND start_time=? AND end_time=?",
        (slot_date, start_time, end_time),
    ).fetchone():
        raise ApiError("A slot for that date and time already exists.", 409)
    cur = con.execute(
        "INSERT INTO time_slots (slot_date, start_time, end_time, max_orders, is_active) VALUES (?,?,?,?,?)",
        (slot_date, start_time, end_time, max_orders, is_active),
    )
    row = fetch_slots_with_counts(con, "s.id = ?", (cur.lastrowid,))[0]
    return jsonify(slot=slot_json(row, settings)), 201


@app.post("/api/admin/slots/<int:slot_id>")
@login_required("admin")
def api_admin_slot(slot_id):
    data = json_body()
    con = db.get_db()
    settings = get_settings(con)
    existing = fetch_slots_with_counts(con, "s.id = ?", (slot_id,))
    if not existing:
        raise ApiError("Slot not found.", 404)
    cur_slot = existing[0]
    if "max_orders" in data:
        cap = to_int(data["max_orders"], "Max orders", 1, 200)
        if cap < cur_slot["booked_count"]:
            raise ApiError("Max orders cannot be lower than the %d orders already booked." % cur_slot["booked_count"], 409)
        con.execute("UPDATE time_slots SET max_orders=? WHERE id=?", (cap, slot_id))
    if "is_active" in data:
        con.execute("UPDATE time_slots SET is_active=? WHERE id=?", (1 if data["is_active"] else 0, slot_id))
    row = fetch_slots_with_counts(con, "s.id = ?", (slot_id,))[0]
    return jsonify(slot=slot_json(row, settings))


@app.delete("/api/admin/slots/<int:slot_id>")
@login_required("admin")
def api_admin_slot_delete(slot_id):
    con = db.get_db()
    if con.execute("SELECT 1 FROM time_slots WHERE id=?", (slot_id,)).fetchone() is None:
        raise ApiError("Slot not found.", 404)
    if con.execute("SELECT 1 FROM orders WHERE time_slot_id=? LIMIT 1", (slot_id,)).fetchone() is not None:
        raise ApiError("Cannot delete a slot that has existing orders. Pause it instead.", 409)
    con.execute("DELETE FROM time_slots WHERE id=?", (slot_id,))
    return jsonify(deleted=slot_id)


@app.post("/api/admin/slots/generate")
@login_required("admin")
def api_admin_slots_generate():
    con = db.get_db()
    settings = get_settings(con)
    today = db.today_iso()
    pairs = db.generate_afternoon_slots(
        settings["afternoon_start"], settings["afternoon_end"], settings["slot_minutes"]
    )
    created = 0
    for s, e in pairs:
        cur = con.execute(
            "INSERT OR IGNORE INTO time_slots (slot_date, start_time, end_time, max_orders, is_active)"
            " VALUES (?,?,?,?,1)",
            (today, s, e, settings["default_max_orders"]),
        )
        created += cur.rowcount
    rows = fetch_slots_with_counts(con, "s.slot_date >= ?", (today,))
    return jsonify(created=created, slots=[slot_json(r, settings) for r in rows])


@app.post("/api/admin/settings")
@login_required("admin")
def api_admin_settings():
    data = json_body()
    con = db.get_db()
    settings = get_settings(con)
    start = str(data.get("afternoon_start", settings["afternoon_start"])).strip()
    end = str(data.get("afternoon_end", settings["afternoon_end"])).strip()
    if not _valid_hhmm(start) or not _valid_hhmm(end) or start >= end:
        raise ApiError("Afternoon start and end times must be valid HH:MM with start < end.")
    enforce = 1 if data.get("enforce_cutoff", settings["enforce_cutoff"]) else 0
    con.execute(
        "UPDATE canteen_settings SET afternoon_start=?, afternoon_end=?, enforce_cutoff=? WHERE id=1",
        (start, end, enforce),
    )
    updated = get_settings(con)
    today = db.today_iso()
    now_hhmm = datetime.now().strftime("%H:%M")
    for s, e in db.generate_afternoon_slots(updated["afternoon_start"], updated["afternoon_end"], updated["slot_minutes"]):
        con.execute(
            "INSERT OR IGNORE INTO time_slots (slot_date, start_time, end_time, max_orders, is_active)"
            " VALUES (?,?,?,?,?)",
            (today, s, e, updated["default_max_orders"], 0 if e <= now_hhmm else 1),
        )
    return jsonify(settings=schedule_json(updated))


# Create the database automatically on first run
with app.app_context():
    if not os.path.exists(app.config["DATABASE"]):
        db.init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
