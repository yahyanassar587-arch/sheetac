import html
import io
import os
import re
import secrets
import sqlite3
import uuid
import zipfile
from contextlib import closing
from datetime import datetime

import streamlit as st


# ----------------------------------------------------------------------------
# الإعدادات: من Secrets (Streamlit Cloud) أو متغيرات البيئة أو القيم الافتراضية
# ----------------------------------------------------------------------------
def cfg(key, default=""):
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


STORE_NAME = cfg("STORE_NAME", "متجر الشيتات")
INSTAPAY_HANDLE = cfg("INSTAPAY_HANDLE", "01285548849")
WALLET_NUMBER = cfg("WALLET_NUMBER", "01285548849")
WALLET_NAME = cfg("WALLET_NAME", "فودافون كاش / اتصالات كاش / أورنج كاش")
WHATSAPP_NUMBER = cfg("WHATSAPP_NUMBER", "201285548849")  # بصيغة دولية بدون +
ADMIN_PASSWORD = cfg("ADMIN_PASSWORD", "YaYa.2052006")  # غيّرها!

DATA_DIR = cfg("DATA_DIR", "data")
SHEETS_DIR = os.path.join(DATA_DIR, "sheets")
PROOFS_DIR = os.path.join(DATA_DIR, "proofs")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
DB_PATH = os.path.join(DATA_DIR, "store.db")
for _d in (SHEETS_DIR, PROOFS_DIR, COVERS_DIR):
    os.makedirs(_d, exist_ok=True)

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
SHEET_EXTS = ["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip", "rar", "png", "jpg", "jpeg"]
METHODS = {"instapay": "انستا باي (InstaPay)", "wallet": "محفظة إلكترونية"}
STATUS_LABELS = {"pending": "قيد المراجعة", "confirmed": "تم التأكيد", "rejected": "مرفوض"}
FILTERS = {"pending": "منتظرة", "confirmed": "مؤكدة", "rejected": "مرفوضة", "all": "الكل"}
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
PHONE_RE = re.compile(r"^01[0125][0-9]{8}$")

st.set_page_config(page_title=STORE_NAME, page_icon="📚", layout="centered")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
html, body, .stApp, .stMarkdown, p, h1, h2, h3, h4, label, button, input, textarea {
  font-family: 'Cairo', sans-serif;
}
.stApp { direction: rtl; background: #f6f4ff; }
.stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label, .stApp li { text-align: right; }
code, pre { direction: ltr; text-align: left; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 1.5rem; max-width: 760px; }

.topbar {
  background: #fff; border-radius: 18px; padding: 10px 18px; margin-bottom: 10px;
  font-weight: 800; font-size: 1.3rem; color: #1f1b3a; box-shadow: 0 6px 20px rgba(108,76,255,.10);
}
.hero {
  background: linear-gradient(135deg, #6c4cff 0%, #a24cff 55%, #ff5fa2 100%);
  color: #fff; border-radius: 24px; padding: 34px 26px; margin: 8px 0 18px;
  box-shadow: 0 14px 34px rgba(108,76,255,.28);
}
.hero h1 { color: #fff; font-size: 1.9rem; font-weight: 800; margin: 0 0 8px; }
.hero p { margin: 0; opacity: .95; font-size: 1.05rem; }
.pill { display: inline-block; background: rgba(255,255,255,.22); padding: 2px 14px;
  border-radius: 99px; font-weight: 700; margin-bottom: 10px; font-size: .9rem; }
.price { font-size: 1.6rem; font-weight: 800; color: #6c4cff; }
.price small { font-size: .9rem; font-weight: 600; color: #6e6a8c; }
.ph { height: 150px; border-radius: 14px; display: grid; place-items: center; font-size: 3.5rem; margin-bottom: 8px; }
.c0 { background: linear-gradient(135deg, #c9b8ff, #8fd3ff); }
.c1 { background: linear-gradient(135deg, #ffc2dc, #ffd9a8); }
.c2 { background: linear-gradient(135deg, #a8f0e0, #b8c8ff); }
.c3 { background: linear-gradient(135deg, #ffe29a, #ffb3c1); }
.status { text-align: center; background: #fff; border-radius: 22px; padding: 28px 18px;
  box-shadow: 0 10px 30px rgba(108,76,255,.12); margin-bottom: 14px; }
.status .ic { font-size: 3.2rem; }
.status h2 { margin: 4px 0; font-weight: 800; }
.badge { display: inline-block; padding: 2px 12px; border-radius: 99px; font-size: .85rem; font-weight: 700; }
.b-pending { background: #fff4e0; color: #b54708; }
.b-confirmed { background: #e7f8ef; color: #067647; }
.b-rejected { background: #fdecea; color: #b42318; }

.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stLinkButton > a {
  border-radius: 14px; font-weight: 700; border: 1.5px solid #e8e4fa;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
  background: linear-gradient(135deg, #6c4cff, #a24cff); color: #fff; border: 0;
  box-shadow: 0 8px 20px rgba(108,76,255,.3);
}
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 20px; background: #fff; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# قاعدة البيانات
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL,
    cover TEXT,
    file TEXT NOT NULL,
    original_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    sheet_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    method TEXT NOT NULL,
    proof TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    downloads INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
"""


def _con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def q(sql, args=(), one=False):
    with closing(_con()) as con:
        rows = con.execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    with closing(_con()) as con:
        cur = con.execute(sql, args)
        con.commit()
        return cur.lastrowid


with closing(_con()) as _c:
    _c.executescript(SCHEMA)


# ----------------------------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------------------------
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def esc(s):
    return html.escape(str(s))


def md(s):
    """يهرّب رموز الماركداون عشان نص العميل ما يتحولش لروابط أو تنسيق."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$])", r"\\\1", str(s))


def ext_of(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_image(data: bytes):
    return (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG")
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def save_bytes(folder, data, ext):
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(folder, name), "wb") as f:
        f.write(data)
    return name


def remove_file(folder, name):
    if name:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def clean_filename(name):
    return re.sub(r"[^\w.\- ]", "_", name) or "sheet"


def go(**params):
    st.query_params.clear()
    for k, v in params.items():
        st.query_params[k] = str(v)
    st.rerun()


def header():
    st.markdown(f"<div class='topbar'>📚 {esc(STORE_NAME)}</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("🏠 الرئيسية", key="nav_home", width="stretch"):
        go()
    c2.link_button("💬 واتساب", f"https://wa.me/{WHATSAPP_NUMBER}", width="stretch")


def img_html(path, max_h=220, fit="cover"):
    """صورة بـ HTML (base64) عشان نتحكم في العرض من غير ما نعتمد على بارامترات st.image."""
    import base64
    mime = {"png": "image/png", "webp": "image/webp"}.get(ext_of(path), "image/jpeg")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return (f"<img src='data:{mime};base64,{b64}' "
            f"style='width:100%;max-height:{max_h}px;object-fit:{fit};border-radius:14px;"
            f"margin-bottom:8px;display:block'>")


def show_cover(sheet, key_n=0):
    path = os.path.join(COVERS_DIR, sheet["cover"]) if sheet["cover"] else None
    if path and os.path.exists(path):
        st.markdown(img_html(path, 220, "cover"), unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='ph c{sheet['id'] % 4}'>📘</div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# صفحات العملاء
# ----------------------------------------------------------------------------
def page_home():
    header()
    st.markdown(
        "<div class='hero'><span class='pill'>✨ شيتات جاهزة للمذاكرة</span>"
        "<h1>ذاكر بذكاء.. بشيتات متظبطة ومرتبة</h1>"
        "<p>اختار الشيت، حوّل بانستا باي أو محفظة، ابعت سكرين التحويل، ونزّل الشيت أول ما نأكد الدفع.</p></div>",
        unsafe_allow_html=True)
    with st.expander("إزاي أشتري؟"):
        st.markdown("1. اختار الشيت\n2. حوّل الفلوس (انستا باي أو محفظة)\n"
                    "3. ارفع سكرين التحويل واكتب بياناتك\n4. أول ما نأكد الطلب يظهر لك زرار التحميل")

    sheets = q("SELECT * FROM sheets WHERE active=1 ORDER BY id DESC")
    st.subheader("الشيتات المتاحة")
    if not sheets:
        st.info("لسه مفيش شيتات متاحة، ارجع قريب 🌟")
    cols = st.columns(2)
    for i, s in enumerate(sheets):
        with cols[i % 2]:
            with st.container(border=True):
                show_cover(s)
                st.markdown(f"**{md(s['title'])}**")
                desc = s["description"] or ""
                st.caption(desc[:90] + ("…" if len(desc) > 90 else ""))
                st.markdown(f"<div class='price'>{int(s['price'])} <small>جنيه</small></div>", unsafe_allow_html=True)
                if st.button("عرض واشتري", key=f"open_{s['id']}", type="primary", width="stretch"):
                    go(page="sheet", id=s["id"])

    st.divider()
    if st.button("دخول الأدمن", key="to_admin"):
        go(admin=1)


def page_sheet(sheet_id):
    header()
    sheet = q("SELECT * FROM sheets WHERE id=? AND active=1", (sheet_id,), one=True)
    if not sheet:
        st.error("الشيت ده مش موجود.")
        return
    if st.button("← رجوع للشيتات", key="back"):
        go()

    show_cover(sheet)
    st.markdown(f"## {md(sheet['title'])}")
    st.markdown(f"<div class='price'>{int(sheet['price'])} <small>جنيه</small></div>", unsafe_allow_html=True)
    st.write(sheet["description"] or "شيت جاهز للتحميل بعد تأكيد الدفع.")
    st.markdown("✅ تحميل مباشر بعد تأكيد الدفع  \n✅ دعم على واتساب لو حصلت أي مشكلة")
    st.divider()

    st.subheader("إتمام الشراء")
    method = st.radio("طريقة الدفع", list(METHODS), format_func=METHODS.get, horizontal=True, key="method")
    if method == "instapay":
        st.write(f"حوّل **{int(sheet['price'])} جنيه** على عنوان انستا باي:")
        st.code(INSTAPAY_HANDLE, language=None)
    else:
        st.write(f"حوّل **{int(sheet['price'])} جنيه** على رقم المحفظة ({WALLET_NAME}):")
        st.code(WALLET_NUMBER, language=None)

    with st.form("checkout"):
        name = st.text_input("الاسم بالكامل", max_chars=80)
        phone = st.text_input("رقم الموبايل (واتساب)", max_chars=15, placeholder="01012345678")
        proof = st.file_uploader("سكرين التحويل", type=sorted(IMAGE_EXTS))
        submit = st.form_submit_button("أكّد وابعت الطلب", type="primary", width="stretch")

    if submit:
        name = name.strip()
        phone = phone.strip().replace(" ", "").translate(AR_DIGITS)
        data = proof.getvalue() if proof else b""
        errors = []
        if len(name) < 3:
            errors.append("اكتب اسمك بالكامل.")
        if not PHONE_RE.match(phone):
            errors.append("رقم الموبايل غير صحيح (مثال: 01012345678).")
        if not proof:
            errors.append("لازم ترفع سكرين التحويل.")
        elif not is_image(data):
            errors.append("سكرين التحويل لازم يكون صورة حقيقية (PNG أو JPG أو WEBP).")
        if errors:
            for e in errors:
                st.error(e)
        else:
            saved = save_bytes(PROOFS_DIR, data, ext_of(proof.name) if ext_of(proof.name) in IMAGE_EXTS else "png")
            token = secrets.token_urlsafe(24)
            x("INSERT INTO orders (token, sheet_id, name, phone, method, proof, status, created_at) "
              "VALUES (?,?,?,?,?,?, 'pending', ?)",
              (token, sheet["id"], name, phone, method, saved, now()))
            go(order=token)


@st.fragment(run_every=15)
def watch_status(token, status):
    row = q("SELECT status FROM orders WHERE token=?", (token,), one=True)
    st.caption("🔄 بنتابع حالة طلبك تلقائيًا، مش لازم تعمل ريفريش.")
    if row and row["status"] != status:
        st.rerun()


def bump_downloads(order_id):
    x("UPDATE orders SET downloads = downloads + 1 WHERE id=?", (order_id,))


def page_order(token):
    header()
    o = q("SELECT o.*, s.title, s.price, s.file, s.original_name FROM orders o "
          "JOIN sheets s ON s.id=o.sheet_id WHERE o.token=?", (token,), one=True)
    if not o:
        st.error("الطلب ده مش موجود. اتأكد من الرابط.")
        return

    if o["status"] == "pending":
        st.markdown("<div class='status'><div class='ic'>⏳</div><h2>طلبك قيد المراجعة</h2>"
                    "<p>بنراجع سكرين التحويل، ولما نأكد هيظهر لك زرار التحميل هنا.</p></div>",
                    unsafe_allow_html=True)
        watch_status(token, o["status"])
    elif o["status"] == "confirmed":
        st.markdown("<div class='status'><div class='ic'>🎉</div><h2>تم تأكيد الدفع!</h2>"
                    "<p>الشيت جاهز للتحميل دلوقتي.</p></div>", unsafe_allow_html=True)
        path = os.path.join(SHEETS_DIR, o["file"])
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            st.download_button("⬇️ تحميل الشيت", data, file_name=o["original_name"],
                               on_click=bump_downloads, args=(o["id"],),
                               type="primary", width="stretch")
        else:
            st.error("ملف الشيت مش متاح حاليًا، كلمنا على واتساب وهنحلها فورًا.")
    else:
        st.markdown("<div class='status'><div class='ic'>❌</div><h2>الطلب اترفض</h2>"
                    "<p>ممكن يكون التحويل مش واصل أو المبلغ مختلف. كلمنا على واتساب ونحلها فورًا.</p></div>",
                    unsafe_allow_html=True)
        st.link_button("💬 كلمنا على واتساب", f"https://wa.me/{WHATSAPP_NUMBER}", width="stretch")

    with st.container(border=True):
        st.markdown(f"**الشيت:** {md(o['title'])}")
        st.markdown(f"**المبلغ:** {int(o['price'])} جنيه")
        st.markdown(f"**طريقة الدفع:** {METHODS.get(o['method'], '')}")
        st.markdown(f"**الحالة:** <span class='badge b-{o['status']}'>{STATUS_LABELS[o['status']]}</span>",
                    unsafe_allow_html=True)
        st.markdown(f"**وقت الطلب:** {o['created_at']}")
    st.info("📌 احفظ رابط الصفحة دي (من شريط العنوان) عشان ترجع لها وتنزّل الشيت في أي وقت.")


# ----------------------------------------------------------------------------
# لوحة التحكم
# ----------------------------------------------------------------------------
def decide(order_id, status):
    x("UPDATE orders SET status=?, decided_at=? WHERE id=?", (status, now(), order_id))


def admin_orders_tab():
    pending = q("SELECT COUNT(*) c FROM orders WHERE status='pending'", one=True)["c"]
    confirmed = q("SELECT COUNT(*) c FROM orders WHERE status='confirmed'", one=True)["c"]
    revenue = q("SELECT COALESCE(SUM(s.price),0) t FROM orders o JOIN sheets s ON s.id=o.sheet_id "
                "WHERE o.status='confirmed'", one=True)["t"]
    c1, c2, c3 = st.columns(3)
    c1.metric("منتظرة", pending)
    c2.metric("مؤكدة", confirmed)
    c3.metric("المبيعات (جنيه)", revenue)

    flt = st.radio("الحالة", list(FILTERS), format_func=FILTERS.get, horizontal=True, key="flt")
    sql = ("SELECT o.*, s.title, s.price FROM orders o JOIN sheets s ON s.id=o.sheet_id")
    args = ()
    if flt != "all":
        sql += " WHERE o.status=?"
        args = (flt,)
    orders = q(sql + " ORDER BY o.id DESC", args)
    if not orders:
        st.info("مفيش طلبات هنا.")
    for o in orders:
        with st.container(border=True):
            left, right = st.columns([1, 2])
            proof_path = os.path.join(PROOFS_DIR, o["proof"])
            if os.path.exists(proof_path):
                left.markdown(img_html(proof_path, 260, "contain"), unsafe_allow_html=True)
            else:
                left.warning("السكرين مش موجود")
            right.markdown(f"**{md(o['title'])}** · #{o['id']} "
                           f"<span class='badge b-{o['status']}'>{STATUS_LABELS[o['status']]}</span>",
                           unsafe_allow_html=True)
            right.markdown(f"{md(o['name'])} · [{o['phone']}](https://wa.me/2{o['phone']})")
            right.caption(f"{METHODS.get(o['method'], '')} · المطلوب {int(o['price'])} جنيه · {o['created_at']}"
                          + (f" · تحميلات: {o['downloads']}" if o["status"] == "confirmed" else ""))
            b1, b2, b3 = right.columns(3)
            if o["status"] != "confirmed":
                b1.button("✅ تأكيد", key=f"ok_{o['id']}", on_click=decide, args=(o["id"], "confirmed"),
                          type="primary", width="stretch")
            if o["status"] != "rejected":
                b2.button("❌ رفض", key=f"no_{o['id']}", on_click=decide, args=(o["id"], "rejected"),
                          width="stretch")
            if o["status"] != "pending":
                b3.button("↩️ مراجعة", key=f"rs_{o['id']}", on_click=decide, args=(o["id"], "pending"),
                          width="stretch")


def parse_price(v):
    return int(v) if v and int(v) > 0 else None


def admin_sheets_tab():
    st.subheader("إضافة شيت جديد")
    with st.form("add_sheet", clear_on_submit=True):
        title = st.text_input("عنوان الشيت", max_chars=120)
        desc = st.text_area("الوصف", max_chars=2000)
        price = st.number_input("السعر (جنيه)", min_value=1, value=50, step=5)
        cover = st.file_uploader("صورة الغلاف (اختياري)", type=sorted(IMAGE_EXTS), key="new_cover")
        sfile = st.file_uploader("ملف الشيت", type=SHEET_EXTS, key="new_file")
        active = st.checkbox("ظاهر في المتجر", value=True)
        add = st.form_submit_button("إضافة", type="primary", width="stretch")
    if add:
        if not title.strip():
            st.error("اكتب عنوان الشيت.")
        elif not sfile:
            st.error("ارفع ملف الشيت.")
        else:
            cover_name = None
            if cover and is_image(cover.getvalue()):
                cover_name = save_bytes(COVERS_DIR, cover.getvalue(), ext_of(cover.name))
            fname = save_bytes(SHEETS_DIR, sfile.getvalue(), ext_of(sfile.name))
            x("INSERT INTO sheets (title, description, price, cover, file, original_name, active, created_at) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (title.strip(), desc.strip(), int(price), cover_name, fname,
               clean_filename(sfile.name), 1 if active else 0, now()))
            st.success("تم إضافة الشيت ✅")

    st.subheader("الشيتات الحالية")
    sheets = q("SELECT s.*, (SELECT COUNT(*) FROM orders o WHERE o.sheet_id=s.id) AS n "
               "FROM sheets s ORDER BY s.id DESC")
    if not sheets:
        st.info("لسه مفيش شيتات.")
    for s in sheets:
        label = f"{s['title']} — {s['price']} جنيه — {s['n']} طلب" + ("" if s["active"] else " (مخفي)")
        with st.expander(label):
            with st.form(f"edit_{s['id']}"):
                t = st.text_input("العنوان", value=s["title"], max_chars=120)
                d = st.text_area("الوصف", value=s["description"], max_chars=2000)
                p = st.number_input("السعر", min_value=1, value=int(s["price"]), step=5)
                nc = st.file_uploader("غلاف جديد (اختياري)", type=sorted(IMAGE_EXTS), key=f"nc_{s['id']}")
                nf = st.file_uploader(f"ملف جديد (الحالي: {s['original_name']})", type=SHEET_EXTS, key=f"nf_{s['id']}")
                a = st.checkbox("ظاهر في المتجر", value=bool(s["active"]))
                save = st.form_submit_button("حفظ التعديلات", type="primary", width="stretch")
            if save:
                cover_name, fname, orig = s["cover"], s["file"], s["original_name"]
                if nc and is_image(nc.getvalue()):
                    remove_file(COVERS_DIR, cover_name)
                    cover_name = save_bytes(COVERS_DIR, nc.getvalue(), ext_of(nc.name))
                if nf:
                    remove_file(SHEETS_DIR, fname)
                    fname = save_bytes(SHEETS_DIR, nf.getvalue(), ext_of(nf.name))
                    orig = clean_filename(nf.name)
                x("UPDATE sheets SET title=?, description=?, price=?, cover=?, file=?, original_name=?, active=? "
                  "WHERE id=?", (t.strip() or s["title"], d.strip(), int(p), cover_name, fname, orig,
                                 1 if a else 0, s["id"]))
                st.success("تم الحفظ. حدّث الصفحة لو مش شايف التغيير.")
            if s["n"] == 0:
                if st.button("🗑️ مسح الشيت", key=f"del_{s['id']}"):
                    remove_file(SHEETS_DIR, s["file"])
                    remove_file(COVERS_DIR, s["cover"])
                    x("DELETE FROM sheets WHERE id=?", (s["id"],))
                    st.rerun()
            else:
                st.caption("الشيت عليه طلبات فمينفعش يتمسح — اقدر تخفيه بس.")


def build_backup():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(DATA_DIR):
            for fn in files:
                full = os.path.join(root, fn)
                zf.write(full, os.path.relpath(full, DATA_DIR))
    return buf.getvalue()


def restore_backup(data):
    allowed = ("store.db", "sheets/", "proofs/", "covers/")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            n = info.filename.replace("\\", "/")
            if info.is_dir():
                continue
            if n.startswith("/") or ".." in n.split("/") or not n.startswith(allowed):
                continue
            dest = os.path.join(DATA_DIR, n)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())


def admin_backup_tab():
    st.warning("⚠️ على Streamlit Cloud الملفات بتتمسح لما التطبيق يتعمله ريستارت أو إعادة نشر. "
               "نزّل نسخة احتياطية بشكل منتظم، وارجعها من هنا لو حصل ريستارت.")
    if st.button("تجهيز نسخة احتياطية", key="mk_backup"):
        st.session_state["backup"] = build_backup()
    if st.session_state.get("backup"):
        st.download_button("⬇️ تحميل النسخة الاحتياطية (zip)", st.session_state["backup"],
                           file_name="sheet_store_backup.zip", mime="application/zip",
                           type="primary", width="stretch")
    st.divider()
    up = st.file_uploader("استرجاع نسخة احتياطية", type=["zip"], key="restore_file")
    if up and st.button("استرجاع البيانات", key="do_restore"):
        try:
            restore_backup(up.getvalue())
            st.success("تم الاسترجاع ✅")
        except zipfile.BadZipFile:
            st.error("الملف مش zip سليم.")


def page_admin():
    header()
    if not st.session_state.get("is_admin"):
        st.subheader("دخول لوحة التحكم")
        with st.form("login"):
            pw = st.text_input("كلمة السر", type="password")
            ok = st.form_submit_button("دخول", type="primary", width="stretch")
        if ok:
            if secrets.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("كلمة السر غلط.")
        return

    top1, top2 = st.columns([3, 1])
    top1.subheader("لوحة التحكم")
    if top2.button("خروج", key="logout", width="stretch"):
        st.session_state["is_admin"] = False
        go()
    if ADMIN_PASSWORD == "admin123":
        st.warning("⚠️ لسه كلمة السر الافتراضية — غيّرها من Secrets (ADMIN_PASSWORD).")

    t1, t2, t3 = st.tabs(["الطلبات", "الشيتات", "نسخة احتياطية"])
    with t1:
        admin_orders_tab()
    with t2:
        admin_sheets_tab()
    with t3:
        admin_backup_tab()


# ----------------------------------------------------------------------------
# التوجيه
# ----------------------------------------------------------------------------
params = st.query_params
if "order" in params:
    page_order(params["order"])
elif "admin" in params:
    page_admin()
elif params.get("page") == "sheet" and str(params.get("id", "")).isdigit():
    page_sheet(int(params["id"]))
else:
    page_home()
