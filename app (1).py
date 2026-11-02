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
ADMIN_CODE = str(secret("ADMIN_CODE", ""))  # كود سري تدخله قبل لوحة الأدمن


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
    is_admin = 0  # الأدمن بيتحدد من الـ Secrets بس، مش من التسجيل
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


def is_admin(user):
    return bool(ADMIN_EMAIL) and bool(user) and user["email"] == ADMIN_EMAIL


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

    # حماية مزدوجة: لازم الإيميل يطابق + كود سري
    if not is_admin(current_user()) or not ADMIN_CODE:
        st.error("غير مسموح")
        return
    if not st.session_state.get("admin_ok"):
        with st.form("admin_gate"):
            code = st.text_input("الكود السري", type="password")
            if st.form_submit_button("دخول"):
                if hmac.compare_digest(code, ADMIN_CODE):
                    st.session_state["admin_ok"] = True
                    st.rerun()
                else:
                    st.error("الكود غلط")
        return

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
    pages = ["المتجر", "شيتاتي"]
    if is_admin(user):
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
