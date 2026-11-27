-- CPT Canteen Pre-Order & Queue Management: SQLite schema.
-- Running this file resets the database. All money is stored as whole rupees.
PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS time_slots;
DROP TABLE IF EXISTS canteen_settings;
DROP TABLE IF EXISTS menu_items;
DROP TABLE IF EXISTS users;
PRAGMA foreign_keys = ON;

CREATE TABLE canteen_settings (
  id                 INTEGER PRIMARY KEY CHECK (id = 1),
  afternoon_start    TEXT NOT NULL DEFAULT '12:00',
  afternoon_end      TEXT NOT NULL DEFAULT '14:30',
  slot_minutes       INTEGER NOT NULL DEFAULT 15 CHECK (slot_minutes > 0),
  default_max_orders INTEGER NOT NULL DEFAULT 15 CHECK (default_max_orders > 0),
  enforce_cutoff     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE users (
  user_id        TEXT PRIMARY KEY,                       -- e.g. USR-1001
  name           TEXT NOT NULL,
  role           TEXT NOT NULL CHECK (role IN ('student','kitchen','admin')),
  login_id       TEXT NOT NULL UNIQUE COLLATE NOCASE,    -- register no. (students) or username
  password_hash  TEXT NOT NULL,
  campus_email   TEXT,
  wallet_balance INTEGER NOT NULL DEFAULT 0 CHECK (wallet_balance >= 0),
  is_blocked     INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE menu_items (
  item_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  dish_name    TEXT NOT NULL,
  category     TEXT NOT NULL,
  price        INTEGER NOT NULL CHECK (price > 0),
  prep_mins    INTEGER NOT NULL DEFAULT 5,
  stock_qty    INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
  is_available INTEGER NOT NULL DEFAULT 1,               -- admin on/off switch
  veg          INTEGER NOT NULL DEFAULT 1,
  description  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE time_slots (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_date  TEXT NOT NULL,                              -- YYYY-MM-DD
  start_time TEXT NOT NULL,                              -- HH:MM (24h), e.g. 12:00
  end_time   TEXT NOT NULL,                              -- HH:MM (24h), e.g. 12:15
  max_orders INTEGER NOT NULL CHECK (max_orders > 0),
  is_active  INTEGER NOT NULL DEFAULT 1,
  UNIQUE(slot_date, start_time, end_time)
);

CREATE TABLE orders (
  order_id       TEXT PRIMARY KEY,                       -- e.g. ORD-1001
  user_id        TEXT NOT NULL REFERENCES users(user_id),
  time_slot_id   INTEGER NOT NULL REFERENCES time_slots(id),
  total_amount   INTEGER NOT NULL,
  payment_method TEXT NOT NULL CHECK (payment_method IN ('UPI','Wallet')),
  payment_ref    TEXT,
  status         TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','preparing','ready','picked_up','cancelled')),
  qr_token       TEXT NOT NULL UNIQUE,
  created_at     TEXT NOT NULL,
  collected_at   TEXT
);

CREATE TABLE order_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id   TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  item_id    INTEGER NOT NULL REFERENCES menu_items(item_id),
  dish_name  TEXT NOT NULL,                              -- snapshot at purchase time
  quantity   INTEGER NOT NULL CHECK (quantity > 0),
  unit_price INTEGER NOT NULL
);

CREATE INDEX idx_orders_user   ON orders(user_id, created_at);
CREATE INDEX idx_orders_slot   ON orders(time_slot_id, status);
CREATE INDEX idx_items_order   ON order_items(order_id);
CREATE INDEX idx_slots_date    ON time_slots(slot_date, start_time);
