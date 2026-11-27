# CPT Canteen Pre-Order & Queue Management (Flask + SQLite)

## Layout
```
canteen/
├── app.py            routes, auth, validation, order/status logic
├── db.py             SQLite connection, schema loader, seed data
├── schema.sql        users, menu_items, time_slots, orders, order_items
├── requirements.txt
├── templates/        base, login, student, kitchen, admin, error
└── static/{css,js}/  styles.css, common.js, student.js, kitchen.js, admin.js
```

## Run
```bash
cd canteen
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app init-db            # creates/resets canteen.db with sample data
flask --app app run                # http://127.0.0.1:5000
```
`python app.py` also works, and creates `canteen.db` automatically if it is missing.

## Demo accounts (shown as quick-login buttons while DEMO_MODE=1)
| Role | Login | Password |
|---|---|---|
| Student: Amarnath R | 501125002 | student123 |
| Student: Gopi Krishna | 501125018 | student123 |
| Student: Thiripura Sundari | 501126511 | student123 |
| Student: Arun Karthick | 501125000 (placeholder, edit in `db.py`) | student123 |
| Kitchen | kitchen | kitchen123 |
| Admin | admin | admin123 |

For anything beyond a demo: `DEMO_MODE=0`, set `SECRET_KEY`, change the seed passwords.
