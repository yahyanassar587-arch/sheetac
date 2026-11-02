import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Sheetac - متجر الشيتات", page_icon="📄", layout="centered")

DB_PATH = "store.db"
FILES_DIR = "sheets_files"
os.makedirs(FILES_DIR, exist_ok=True)


def secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


ADMIN_EMAIL = secret("ADMIN_EMAIL", "").strip().lower()
PAY_NUMBER = secret("PAY_NUMBER", "01XXXXXXXXX")  # رقم فودافون كاش / انستا باي
PAY_METHOD = secret("PAY_METHOD", "فودافون كاش")


# ---------- قاعدة البيانات ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                file_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                sheet_id INTEGER NOT NULL,
                payment_ref TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            """
        )


# ---------- المستخدمين ----------
import os
import requests
from flask import Flask, redirect, url_for, session, request, render_template_string, abort
from authlib.integrations.flask_client import OAuth

# ===== الإعدادات (حطها كمتغيرات بيئة) =====
# ALLOWED_EMAIL         : yahyanassar587@gmail.com
# GOOGLE_CLIENT_ID      : من Google Cloud Console
# GOOGLE_CLIENT_SECRET  : من Google Cloud Console
# SECRET_KEY            : أي نص عشوائي طويل
ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "your.email@gmail.com").lower()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "غيّر-المفتاح-ده")

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile https://www.googleapis.com/auth/spreadsheets"},
)

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

PAGE = """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>إضافة شيتات</title>
<style>
  body{font-family:Tahoma,Arial,sans-serif;background:#f4f6f8;margin:0;padding:24px}
  .box{max-width:560px;margin:auto;background:#fff;padding:24px;border-radius:12px;box-shadow:0 2px 10px #0001}
  h1{font-size:22px;margin-top:0}
  h2{font-size:17px;margin-top:28px}
  input,button{width:100%;padding:10px;margin:6px 0;font-size:15px;box-sizing:border-box}
  button{background:#1a73e8;color:#fff;border:0;border-radius:8px;cursor:pointer}
  .msg{padding:10px;border-radius:8px;margin:12px 0;background:#e6f4ea;color:#137333}
  .err{background:#fce8e6;color:#c5221f}
  .top{display:flex;justify-content:space-between;font-size:14px;color:#555}
</style>
</head>
<body><div class="box">
  <div class="top"><span>{{ email }}</span><a href="{{ url_for('logout') }}">خروج</a></div>
  <h1>إضافة شيتات</h1>
  {% if msg %}<div class="msg">{{ msg|safe }}</div>{% endif %}
  {% if error %}<div class="msg err">{{ error }}</div>{% endif %}

  <h2>1) إنشاء ملف Spreadsheet جديد</h2>
  <form method="post" action="{{ url_for('create_spreadsheet') }}">
    <input name="title" placeholder="اسم الملف" required>
    <button>إنشاء</button>
  </form>

  <h2>2) إضافة شيت (تبويب) لملف موجود</h2>
  <form method="post" action="{{ url_for('add_sheet') }}">
    <input name="spreadsheet_id" placeholder="Spreadsheet ID (من رابط الملف)" required>
    <input name="sheet_title" placeholder="اسم الشيت الجديد" required>
    <button>إضافة الشيت</button>
  </form>
</div></body></html>
"""


def current_email():
    return (session.get("user") or {}).get("email", "").lower()


def require_owner():
    """يسمح فقط للجيميل المحدد."""
    if not session.get("user"):
        return redirect(url_for("login"))
    if current_email() != ALLOWED_EMAIL:
        session.clear()
        abort(403)
    return None


def auth_headers():
    return {"Authorization": f"Bearer {session['token']['access_token']}"}


@app.route("/")
def index():
    guard = require_owner()
    if guard:
        return guard
    return render_template_string(
        PAGE, email=current_email(),
        msg=request.args.get("msg"), error=request.args.get("error"),
    )


@app.route("/login")
def login():
    return oauth.google.authorize_redirect(url_for("callback", _external=True))


@app.route("/callback")
def callback():
    token = oauth.google.authorize_access_token()
    info = token.get("userinfo") or {}
    email = info.get("email", "").lower()
    if email != ALLOWED_EMAIL or not info.get("email_verified", False):
        session.clear()
        abort(403)
    session["user"] = {"email": email}
    session["token"] = {"access_token": token["access_token"]}
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/create", methods=["POST"])
def create_spreadsheet():
    guard = require_owner()
    if guard:
        return guard
    title = request.form["title"].strip()
    r = requests.post(SHEETS_API, headers=auth_headers(),
                      json={"properties": {"title": title}})
    if r.ok:
        d = r.json()
        link = f'تم إنشاء الملف: <a href="{d["spreadsheetUrl"]}" target="_blank">{title}</a>'
        return redirect(url_for("index", msg=link))
    return redirect(url_for("index", error=f"فشل الإنشاء: {r.text[:200]}"))


@app.route("/add", methods=["POST"])
def add_sheet():
    guard = require_owner()
    if guard:
        return guard
    sid = request.form["spreadsheet_id"].strip()
    title = request.form["sheet_title"].strip()
    body = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
    r = requests.post(f"{SHEETS_API}/{sid}:batchUpdate", headers=auth_headers(), json=body)
    if r.ok:
        return redirect(url_for("index", msg=f"تمت إضافة الشيت: {title}"))
    return redirect(url_for("index", error=f"فشلت الإضافة: {r.text[:200]}"))


@app.errorhandler(403)
def forbidden(_):
    return "غير مسموح. الصفحة دي خاصة بصاحبها فقط.", 403


if __name__ == "__main__":
    app.run(debug=True, port=5000)
def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def register(name, email, password):
    email = email.strip().lower()
    if not name.strip():
        return "اكتب اسمك"
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return "الإيميل غير صحيح"
    if len(password) < 8:
        return "كلمة السر لازم تكون 8 حروف على الأقل"
    salt = secrets.token_hex(16)
    is_admin = 1 if ADMIN_EMAIL and email == ADMIN_EMAIL else 0
    try:
        with db() as c:
            c.execute(
                "INSERT INTO users (name, email, salt, pw_hash, is_admin) VALUES (?,?,?,?,?)",
                (name.strip(), email, salt, hash_pw(password, salt), is_admin),
            )
    except sqlite3.IntegrityError:
        return "الإيميل ده مسجل قبل كده"
    return None


def login(email, password):
    email = email.strip().lower()
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if row and hmac.compare_digest(row["pw_hash"], hash_pw(password, row["salt"])):
        return dict(row)
    return None


def current_user():
    return st.session_state.get("user")


# ---------- الصفحات ----------
def auth_page():
    st.title("📄 Sheetac")
    st.caption("سجّل حساب أو ادخل عشان تشتري الشيتات")
    tab_login, tab_signup = st.tabs(["تسجيل الدخول", "إنشاء حساب"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("الإيميل")
            password = st.text_input("كلمة السر", type="password")
            if st.form_submit_button("دخول"):
                user = login(email, password)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("الإيميل أو كلمة السر غلط")

    with tab_signup:
        with st.form("signup"):
            name = st.text_input("الاسم")
            email = st.text_input("الإيميل", key="su_email")
            password = st.text_input("كلمة السر (8 حروف على الأقل)", type="password", key="su_pw")
            if st.form_submit_button("إنشاء حساب"):
                err = register(name, email, password)
                if err:
                    st.error(err)
                else:
                    st.success("تم إنشاء الحساب، سجّل دخول من التبويب التاني")


def store_page(user):
    st.header("🛒 المتجر")
    with db() as c:
        sheets = c.execute("SELECT * FROM sheets ORDER BY id DESC").fetchall()
        orders = c.execute("SELECT * FROM orders WHERE user_id=?", (user["id"],)).fetchall()
    status_by_sheet = {o["sheet_id"]: o["status"] for o in orders}

    if not sheets:
        st.info("مفيش شيتات متاحة دلوقتي")
        return

    for s in sheets:
        with st.container(border=True):
            st.subheader(s["title"])
            if s["description"]:
                st.write(s["description"])
            st.write(f"**السعر:** {s['price']:g} جنيه")
            status = status_by_sheet.get(s["id"])
            if status == "approved":
                st.success("اشتريته ✅ — تقدر تحمّله من «شيتاتي»")
            elif status == "pending":
                st.warning("طلبك قيد المراجعة ⏳")
            else:
                with st.expander("اشتري الشيت ده"):
                    st.write(
                        f"1. حوّل **{s['price']:g} جنيه** على {PAY_METHOD}: `{PAY_NUMBER}`\n"
                        "2. اكتب رقم العملية أو رقم الموبايل اللي حوّلت منه\n"
                        "3. هنراجع الدفع ونفعّل الشيت لحسابك"
                    )
                    ref = st.text_input("رقم العملية / رقم المحوّل منه", key=f"ref_{s['id']}")
                    if st.button("تأكيد الطلب", key=f"buy_{s['id']}"):
                        if len(ref.strip()) < 4:
                            st.error("اكتب رقم العملية")
                        else:
                            with db() as c:
                                c.execute(
                                    "INSERT INTO orders (user_id, sheet_id, payment_ref, created_at) VALUES (?,?,?,?)",
                                    (user["id"], s["id"], ref.strip(), datetime.now().isoformat(timespec="seconds")),
                                )
                            st.rerun()


def my_sheets_page(user):
    st.header("📚 شيتاتي")
    with db() as c:
        rows = c.execute(
            """SELECT o.id AS order_id, o.status, s.title, s.file_name
               FROM orders o JOIN sheets s ON s.id = o.sheet_id
               WHERE o.user_id=? ORDER BY o.id DESC""",
            (user["id"],),
        ).fetchall()
    if not rows:
        st.info("لسه مشتريتش حاجة")
        return
    for r in rows:
        with st.container(border=True):
            st.subheader(r["title"])
            if r["status"] == "approved":
                path = os.path.join(FILES_DIR, r["file_name"])
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        st.download_button("⬇️ تحميل", f.read(), file_name=r["file_name"], key=f"dl_{r['order_id']}")
                else:
                    st.error("الملف مش موجود، كلم الدعم")
            elif r["status"] == "pending":
                st.warning("قيد المراجعة ⏳")
            else:
                st.error("الطلب اترفض ❌")


def admin_page():
    st.header("⚙️ لوحة الأدمن")
    tab_orders, tab_add = st.tabs(["الطلبات", "إضافة شيت"])

    with tab_orders:
        with db() as c:
            rows = c.execute(
                """SELECT o.id, o.payment_ref, o.status, o.created_at,
                          u.name, u.email, s.title, s.price
                   FROM orders o
                   JOIN users u ON u.id = o.user_id
                   JOIN sheets s ON s.id = o.sheet_id
                   ORDER BY o.status = 'pending' DESC, o.id DESC"""
            ).fetchall()
        if not rows:
            st.info("مفيش طلبات")
        for r in rows:
            with st.container(border=True):
                st.write(f"**{r['title']}** — {r['price']:g} جنيه")
                st.write(f"{r['name']} ({r['email']})")
                st.write(f"رقم العملية: `{r['payment_ref']}` | {r['created_at']} | الحالة: **{r['status']}**")
                if r["status"] == "pending":
                    a, b = st.columns(2)
                    if a.button("✅ قبول", key=f"ok_{r['id']}"):
                        with db() as c:
                            c.execute("UPDATE orders SET status='approved' WHERE id=?", (r["id"],))
                        st.rerun()
                    if b.button("❌ رفض", key=f"no_{r['id']}"):
                        with db() as c:
                            c.execute("UPDATE orders SET status='rejected' WHERE id=?", (r["id"],))
                        st.rerun()

    with tab_add:
        with st.form("add_sheet", clear_on_submit=True):
            title = st.text_input("اسم الشيت")
            desc = st.text_area("الوصف")
            price = st.number_input("السعر (جنيه)", min_value=0.0, step=5.0)
            file = st.file_uploader("ملف الشيت (PDF مثلاً)")
            if st.form_submit_button("إضافة"):
                if not title.strip() or file is None:
                    st.error("اكتب الاسم وارفع الملف")
                else:
                    safe = re.sub(r"[^\w.\-]", "_", file.name)
                    safe = f"{secrets.token_hex(4)}_{safe}"
                    with open(os.path.join(FILES_DIR, safe), "wb") as f:
                        f.write(file.getbuffer())
                    with db() as c:
                        c.execute(
                            "INSERT INTO sheets (title, description, price, file_name) VALUES (?,?,?,?)",
                            (title.strip(), desc.strip(), price, safe),
                        )
                    st.success("تمت الإضافة")


# ---------- التشغيل ----------
init_db()
user = current_user()

if not user:
    auth_page()
else:
    st.sidebar.write(f"أهلاً، **{user['name']}**")
    pages = ["المتجر", "الشيتات"]
    if user["is_admin"]:
        pages.append("الأدمن")
    choice = st.sidebar.radio("القائمة", pages)
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.clear()
        st.rerun()

    if choice == "المتجر":
        store_page(user)
    elif choice == "شيتاتي":
        my_sheets_page(user)
    else:
        admin_page()
