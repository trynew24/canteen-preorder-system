# CPT Canteen Pre-Order & Queue Management (Flask + SQLite)

## Layout
```
canteen/
├── app.py            routes, auth, validation, order/status logic, CLI commands
├── db.py             SQLite connection, schema loader, seed data
├── schema.sql        users, menu_items, time_slots, orders, order_items, wallet_ledger
├── requirements.txt
├── templates/        base, login, register, student, kitchen, admin, error
└── static/{css,js}/
```

## Run
```bash
cd canteen
python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db            # WARNING: creates or RESETS canteen.db
flask --app app run                # http://127.0.0.1:5000
```

## Accounts
Only these exist after `init-db`. Students create their own on the **Create an account** page.

| Login | Role | Starter password |
|---|---|---|
| `kitchen1`, `kitchen2`, `kitchen3` | kitchen | `kitchen123` |
| `admin` | admin (only one allowed) | `admin123` |

The database allows exactly 1 admin and at most 3 kitchen accounts. Change the starter passwords:
```bash
flask --app app set-password admin
flask --app app set-password kitchen1
```

## Rules
- Every account (including new students) is a row in `canteen.db`, starting with ₹0.
- Only the admin can add wallet money (Admin page, Users, View, Add to wallet). Each credit and wallet payment is logged in `wallet_ledger`.
- The admin can view every account's details, orders and wallet history, and block or unblock any non-admin account. Blocked users are signed out and cannot sign in.
- The admin adds, edits, pauses and deletes dishes on the Admin page. Deleted dishes are hidden but old orders keep their record.
- All time slots start with 0 bookings and fill as orders are placed.
- Set `SECRET_KEY` in the environment for any real deployment. Set `REGISTRATION_OPEN=0` to turn off the sign-up page.
