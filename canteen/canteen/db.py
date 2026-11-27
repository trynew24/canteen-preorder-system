"""SQLite helpers: connection handling, schema creation, seed data."""
import os
import secrets
import sqlite3
from datetime import datetime

from flask import current_app, g
from werkzeug.security import generate_password_hash

DEMO_PASSWORDS = {"student": "student123", "kitchen": "kitchen123", "admin": "admin123"}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


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


def _qr_token(order_id):
    return "CPT-%s-%s" % (order_id.split("-")[1], secrets.token_hex(4).upper())


def seed_db(con):
    users = [
        # user_id, name, role, login_id, password, email, wallet
        ("USR-101", "Amarnath R", "student", "501125002", DEMO_PASSWORDS["student"], "amarnath.501125002@cpt.edu", 480),
        ("USR-102", "Gopi Krishna", "student", "501125018", DEMO_PASSWORDS["student"], "gopi.501125018@cpt.edu", 250),
        ("USR-103", "Thiripura Sundari", "student", "501126511", DEMO_PASSWORDS["student"], "thiripura.501126511@cpt.edu", 320),
        # Arun Karthick's register number was not provided: replace this placeholder.
        ("USR-104", "Arun Karthick", "student", "501125000", DEMO_PASSWORDS["student"], "arun.karthick@cpt.edu", 150),
        ("USR-201", "Canteen Kitchen", "kitchen", "kitchen", DEMO_PASSWORDS["kitchen"], None, 0),
        ("USR-301", "Canteen Admin", "admin", "admin", DEMO_PASSWORDS["admin"], None, 0),
    ]
    con.executemany(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        [(a, b, c, d, generate_password_hash(e), f, g_) for a, b, c, d, e, f, g_ in users],
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

    # booked_count is pre-seeded to simulate bookings already made by other students
    slots = [
        ("SLT-1200", "12:00", "12:15", 15, 8), ("SLT-1215", "12:15", "12:30", 15, 12),
        ("SLT-1230", "12:30", "12:45", 18, 15), ("SLT-1245", "12:45", "13:00", 18, 18),
        ("SLT-1300", "13:00", "13:15", 15, 5), ("SLT-1315", "13:15", "13:30", 15, 3),
    ]
    con.executemany("INSERT INTO time_slots VALUES (?,?,?,?,?)", slots)

    sample = [
        # order_id, user, slot, status, payment, [(item_id, qty)]
        ("ORD-1001", "USR-103", "SLT-1230", "pending", "UPI", [(3, 1), (7, 1)]),
        ("ORD-1002", "USR-102", "SLT-1230", "preparing", "Wallet", [(1, 1), (7, 1)]),
        ("ORD-1003", "USR-104", "SLT-1215", "ready", "UPI", [(2, 2)]),
    ]
    prices = {r[0]: (r[1], r[2]) for r in con.execute("SELECT item_id, dish_name, price FROM menu_items")}
    for oid, uid, sid, status, pay, lines in sample:
        total = sum(prices[i][1] * q for i, q in lines)
        con.execute(
            "INSERT INTO orders (order_id,user_id,slot_id,total_amount,payment_method,payment_ref,status,qr_token,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (oid, uid, sid, total, pay, "UPI" + secrets.token_hex(5).upper() if pay == "UPI" else None,
             status, _qr_token(oid), now_iso()))
        for i, q in lines:
            con.execute("INSERT INTO order_items (order_id,item_id,dish_name,quantity,unit_price) VALUES (?,?,?,?,?)",
                        (oid, i, prices[i][0], q, prices[i][1]))
