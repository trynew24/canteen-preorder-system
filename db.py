"""SQLite helpers: connection handling, schema creation, seed data."""
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import current_app, g
from werkzeug.security import generate_password_hash

DEMO_PASSWORDS = {"kitchen": "kitchen123", "admin": "admin123"}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def today_iso():
    return date.today().isoformat()


def get_db():
    if "db" not in g:
        # isolation_level=None -> autocommit; write routes open BEGIN IMMEDIATE themselves
        con = sqlite3.connect(current_app.config["DATABASE"], isolation_level=None, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        g.db = con
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db(seed=True):
    con = get_db()
    schema = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema, encoding="utf-8") as fh:
        con.executescript(fh.read())
    if seed:
        seed_db(con)


def generate_afternoon_slots(start_hhmm="12:00", end_hhmm="14:30", step_mins=15):
    """Return list of (start_time, end_time) tuples in HH:MM within afternoon hours."""
    cur = datetime.strptime(start_hhmm, "%H:%M")
    end = datetime.strptime(end_hhmm, "%H:%M")
    slots = []
    while cur + timedelta(minutes=step_mins) <= end:
        nxt = cur + timedelta(minutes=step_mins)
        slots.append((cur.strftime("%H:%M"), nxt.strftime("%H:%M")))
        cur = nxt
    return slots


def seed_db(con):
    now = now_iso()
    today = today_iso()

    con.execute(
        "INSERT INTO canteen_settings (id, afternoon_start, afternoon_end, slot_minutes, default_max_orders, enforce_cutoff)"
        " VALUES (1, '12:00', '14:30', 15, 15, 1)"
    )

    users = [
        # user_id, name, role, login_id, password, email, wallet
        ("USR-201", "Kitchen Staff 1", "kitchen", "kitchen1", DEMO_PASSWORDS["kitchen"], None, 0),
        ("USR-202", "Kitchen Staff 2", "kitchen", "kitchen2", DEMO_PASSWORDS["kitchen"], None, 0),
        ("USR-203", "Kitchen Staff 3", "kitchen", "kitchen3", DEMO_PASSWORDS["kitchen"], None, 0),
        ("USR-301", "Canteen Admin", "admin", "admin", DEMO_PASSWORDS["admin"], None, 0),
    ]
    con.executemany(
        "INSERT INTO users (user_id,name,role,login_id,password_hash,campus_email,wallet_balance,is_blocked,created_at)"
        " VALUES (?,?,?,?,?,?,?,0,?)",
        [(a, b, c, d, generate_password_hash(e), f, g_, now) for a, b, c, d, e, f, g_ in users],
    )

    menu = [
        # name, category, price, prep, stock, available, veg, description
        ("Mini Meals Combo", "Meals", 85, 6, 28, 1, 1, "Sambar rice, curd rice, poriyal, papad & sweet"),
        ("Ghee Masala Dosa", "Tiffin", 60, 5, 24, 1, 1, "Crispy roast dosa with potato masala & 2 chutneys"),
        ("Chicken Biryani Bowl", "Meals", 120, 4, 6, 1, 0, "Seeraga samba biryani with onion raita & salna"),
        ("Paneer Frankie Roll", "Snacks", 75, 5, 18, 1, 1, "Spiced paneer tikka wrapped in toasted chapati"),
        ("Veg Puff & Samosa Duo", "Snacks", 40, 2, 35, 1, 1, "Warm bakery puff + crispy samosa with mint dip"),
        ("Chole Bhature Plate", "Tiffin", 80, 7, 16, 1, 1, "2 fluffy bhaturas with chickpea curry & pickle"),
        ("Filter Coffee", "Beverages", 25, 2, 50, 1, 1, "Traditional South Indian filter coffee"),
        ("Cold Milo Shake", "Beverages", 45, 3, 0, 1, 1, "Chilled chocolate malt shake (300 ml)"),
        ("Egg Fried Rice", "Meals", 90, 6, 20, 1, 0, "Wok-tossed rice with egg, spring onion & pepper"),
    ]
    con.executemany(
        "INSERT INTO menu_items (dish_name,category,price,prep_mins,stock_qty,is_available,veg,description)"
        " VALUES (?,?,?,?,?,?,?,?)", menu)

    slot_pairs = generate_afternoon_slots("12:00", "14:30", 15)
    con.executemany(
        "INSERT INTO time_slots (slot_date, start_time, end_time, max_orders, is_active) VALUES (?,?,?,?,1)",
        [(today, s, e, 15) for s, e in slot_pairs],
    )
