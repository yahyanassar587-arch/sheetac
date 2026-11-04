import csv
import base64
import hashlib
import hmac
import html
import io
import mimetypes
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from supabase import create_client


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
INSTAPAY_HANDLE = cfg("INSTAPAY_HANDLE", "yourname@instapay")
WALLET_NUMBER = cfg("WALLET_NUMBER", "01000000000")
WALLET_NAME = cfg("WALLET_NAME", "فودافون كاش / اتصالات كاش / أورنج كاش")
WHATSAPP_NUMBER = cfg("WHATSAPP_NUMBER", "201000000000")  # بصيغة دولية بدون +
ADMIN_PASSWORD = cfg("ADMIN_PASSWORD", "admin123")  # غيّرها!

# بيانات الاتصال بـ Supabase (ضيفها في Secrets)
SUPABASE_URL = cfg("SUPABASE_URL")
SUPABASE_KEY = cfg("SUPABASE_KEY")  # مفتاح service_role، ومينفعش يتحط في الكود أو GitHub

B_SHEETS, B_PROOFS, B_COVERS = "sheets", "proofs", "covers"
MAX_UPLOAD_MB = 50  # حد الرفع للملف الواحد في الخطة المجانية لـ Supabase
TZ = ZoneInfo("Africa/Cairo")

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

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("إعدادات قاعدة البيانات ناقصة: ضيف SUPABASE_URL و SUPABASE_KEY في Secrets.")
    st.stop()


# ----------------------------------------------------------------------------
# الاتصال بقاعدة البيانات والتخزين (Supabase)
# كل البيانات والملفات بتتحفظ هناك، فمفيش حاجة بتتمسح لما التطبيق ينام أو يتعمله ريستارت.
# ----------------------------------------------------------------------------
@st.cache_resource
def sb():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def tbl(name):
    return sb().table(name)


def bucket(name):
    return sb().storage.from_(name)


# ---- الشيتات ----
def list_sheets(active_only=True):
    qy = tbl("sheets").select("*, orders(count)")
    if active_only:
        qy = qy.eq("active", True)
    return qy.order("id", desc=True).execute().data or []


def get_sheet(sheet_id):
    rows = (tbl("sheets").select("*").eq("id", sheet_id).eq("active", True)
            .limit(1).execute().data)
    return rows[0] if rows else None


def sheet_orders_count(sheet):
    try:
        return int(sheet["orders"][0]["count"])
    except Exception:
        return 0


# ---- الطلبات ----
def get_order(token):
    rows = (tbl("orders").select("*, sheets(title, file, original_name)")
            .eq("token", token).limit(1).execute().data)
    if not rows:
        return None
    o = rows[0]
    o.update(o.pop("sheets", None) or {})
    return o


def list_customer_orders(customer_id):
    """كل طلبات العميل المتسجلة على حسابه."""
    rows = (tbl("orders").select("*, sheets(title, file, original_name)")
            .eq("customer_id", customer_id).order("id", desc=True).limit(100).execute().data or [])
    for o in rows:
        o.update(o.pop("sheets", None) or {})
    return rows


# ---- حسابات العملاء ----
def get_customer_by_phone(phone):
    rows = tbl("customers").select("*").eq("phone", phone).limit(1).execute().data
    return rows[0] if rows else None


def create_customer(name, phone, password):
    salt = secrets.token_hex(16)
    rows = tbl("customers").insert({
        "name": name, "phone": phone, "pw_hash": hash_pw(password, salt),
        "pw_salt": salt, "created_at": now(),
    }).execute().data
    return rows[0]


def set_password(customer_id, password):
    salt = secrets.token_hex(16)
    tbl("customers").update({
        "pw_hash": hash_pw(password, salt), "pw_salt": salt,
        "failed_logins": 0, "lock_until": 0,
    }).eq("id", customer_id).execute()


def attempt_login(phone, password):
    """بترجّع (العميل, None) لو نجح، أو (None, رسالة الخطأ). بتقفل الحساب مؤقتًا بعد محاولات غلط كتير."""
    bad = "رقم الموبايل أو كلمة السر غلط."
    c = get_customer_by_phone(phone)
    if not c:
        return None, bad
    remaining = int(c["lock_until"]) - int(time.time())
    if remaining > 0:
        return None, f"الحساب مقفول مؤقتًا بسبب محاولات غلط كتير. جرّب بعد {(remaining + 59) // 60} دقيقة."
    if verify_pw(password, c):
        if c["failed_logins"] or c["lock_until"]:
            tbl("customers").update({"failed_logins": 0, "lock_until": 0}).eq("id", c["id"]).execute()
        return c, None
    fails = int(c["failed_logins"]) + 1
    if fails >= MAX_FAILS:
        upd = {"failed_logins": 0, "lock_until": int(time.time()) + LOCK_SECONDS}
    else:
        upd = {"failed_logins": fails}
    tbl("customers").update(upd).eq("id", c["id"]).execute()
    return None, bad


def get_order_status(token):
    rows = tbl("orders").select("status").eq("token", token).limit(1).execute().data
    return rows[0]["status"] if rows else None


def list_orders(status):
    qy = tbl("orders").select("*, sheets(title)")
    if status != "all":
        qy = qy.eq("status", status)
    rows = qy.order("id", desc=True).limit(100).execute().data or []
    for o in rows:
        o["title"] = (o.pop("sheets", None) or {}).get("title", "—")
    return rows


def get_stats():
    d = sb().rpc("store_stats").execute().data
    if isinstance(d, list):
        d = d[0] if d else {}
    d = d or {}
    return int(d.get("pending", 0)), int(d.get("confirmed", 0)), int(d.get("revenue", 0))


# ---- الملفات ----
def save_bytes(bucket_name, data, ext):
    name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    ctype = mimetypes.guess_type(f"x.{ext}")[0] or "application/octet-stream"
    bucket(bucket_name).upload(name, data, {"content-type": ctype})
    return name


def remove_file(bucket_name, name):
    if name:
        try:
            bucket(bucket_name).remove([name])
        except Exception:
            pass


@st.cache_data(ttl=900, max_entries=100, show_spinner=False)
def fetch_proof(name):
    return bucket(B_PROOFS).download(name)


@st.cache_data(ttl=300, max_entries=3, show_spinner=False)
def fetch_sheet_file(name):
    return bucket(B_SHEETS).download(name)


def cover_url(name):
    return bucket(B_COVERS).get_public_url(name)


# ----------------------------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------------------------
def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


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


def too_big(data: bytes):
    return len(data) > MAX_UPLOAD_MB * 1024 * 1024


def clean_filename(name):
    return re.sub(r"[^\w.\- ]", "_", name) or "sheet"


MIN_PW_LEN = 6
MAX_FAILS = 5            # محاولات دخول غلط قبل قفل الحساب
LOCK_SECONDS = 15 * 60   # مدة القفل


def hash_pw(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000).hex()


def verify_pw(password, customer):
    return hmac.compare_digest(hash_pw(password, customer["pw_salt"]), customer["pw_hash"])


def norm_phone(s):
    return s.strip().replace(" ", "").translate(AR_DIGITS)


# ---- جلسة العميل (بتتخزن في ذاكرة الجلسة بس) ----
def current_customer():
    return st.session_state.get("customer")


def login_session(c):
    st.session_state["customer"] = {"id": c["id"], "name": c["name"], "phone": c["phone"]}


def logout_session():
    st.session_state.pop("customer", None)
    for k in [k for k in st.session_state if str(k).startswith("ready_")]:
        del st.session_state[k]


def auth_forms(prefix):
    """نماذج الدخول وإنشاء حساب جديد (بتتعرض لأي حد مش مسجّل دخول)."""
    tab_in, tab_up = st.tabs(["دخول", "حساب جديد"])
    with tab_in:
        with st.form(f"{prefix}_login"):
            phone = st.text_input("رقم الموبايل", max_chars=15, placeholder="01012345678")
            pw = st.text_input("كلمة السر", type="password", max_chars=60)
            ok = st.form_submit_button("دخول", type="primary", width="stretch")
        if ok:
            phone = norm_phone(phone)
            if not PHONE_RE.match(phone):
                st.error("رقم الموبايل غير صحيح (مثال: 01012345678).")
            else:
                c, err = attempt_login(phone, pw)
                if err:
                    st.error(err)
                else:
                    login_session(c)
                    st.rerun()
    with tab_up:
        with st.form(f"{prefix}_signup"):
            name = st.text_input("الاسم بالكامل", max_chars=80)
            phone = st.text_input("رقم الموبايل (واتساب)", max_chars=15, placeholder="01012345678")
            pw = st.text_input(f"كلمة السر ({MIN_PW_LEN} حروف أو أرقام على الأقل)", type="password", max_chars=60)
            pw2 = st.text_input("أكّد كلمة السر", type="password", max_chars=60)
            ok = st.form_submit_button("إنشاء الحساب", type="primary", width="stretch")
        if ok:
            name, phone = name.strip(), norm_phone(phone)
            errors = []
            if len(name) < 3:
                errors.append("اكتب اسمك بالكامل.")
            if not PHONE_RE.match(phone):
                errors.append("رقم الموبايل غير صحيح (مثال: 01012345678).")
            if len(pw) < MIN_PW_LEN:
                errors.append(f"كلمة السر لازم تكون {MIN_PW_LEN} حروف أو أرقام على الأقل.")
            elif pw != pw2:
                errors.append("كلمتين السر مش متطابقين.")
            if not errors and get_customer_by_phone(phone):
                errors.append("الرقم ده عنده حساب بالفعل، سجّل دخول بدل ما تعمل حساب جديد.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    login_session(create_customer(name, phone, pw))
                except Exception:
                    st.error("مقدرناش ننشئ الحساب، جرّب تاني بعد شوية.")
                else:
                    st.rerun()


def go(**params):
    st.query_params.clear()
    for k, v in params.items():
        st.query_params[k] = str(v)
    st.rerun()


def header():
    st.markdown(f"<div class='topbar'>📚 {esc(STORE_NAME)}</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("🏠 الرئيسية", key="nav_home", width="stretch"):
        go()
    if c2.button("📥 شيتاتي", key="nav_mysheets", width="stretch"):
        go(mysheets=1)
    c3.link_button("💬 واتساب", f"https://wa.me/{WHATSAPP_NUMBER}", width="stretch")


def img_html(data, ext, max_h=220, fit="cover"):
    """صورة بـ HTML (base64) عشان نتحكم في العرض من غير ما نعتمد على بارامترات st.image."""
    mime = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    b64 = base64.b64encode(data).decode()
    return (f"<img src='data:{mime};base64,{b64}' "
            f"style='width:100%;max-height:{max_h}px;object-fit:{fit};border-radius:14px;"
            f"margin-bottom:8px;display:block'>")


def show_cover(sheet):
    if sheet.get("cover"):
        st.markdown(f"<img src='{esc(cover_url(sheet['cover']))}' "
                    "style='width:100%;max-height:220px;object-fit:cover;border-radius:14px;"
                    "margin-bottom:8px;display:block'>", unsafe_allow_html=True)
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

    sheets = list_sheets(active_only=True)
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
    sheet = get_sheet(sheet_id)
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
    cust = current_customer()
    if not cust:
        st.info("سجّل دخولك أو اعمل حساب الأول، عشان الشيتات اللي تشتريها تتحفظ في حسابك وتنزّلها في أي وقت.")
        auth_forms("buy")
        return
    st.caption(f"بتشتري بحساب: {md(cust['name'])} · {cust['phone']}")
    method = st.radio("طريقة الدفع", list(METHODS), format_func=METHODS.get, horizontal=True, key="method")
    if method == "instapay":
        st.write(f"حوّل **{int(sheet['price'])} جنيه** على عنوان انستا باي:")
        st.code(INSTAPAY_HANDLE, language=None)
    else:
        st.write(f"حوّل **{int(sheet['price'])} جنيه** على رقم المحفظة ({WALLET_NAME}):")
        st.code(WALLET_NUMBER, language=None)

    with st.form("checkout"):
        proof = st.file_uploader("سكرين التحويل", type=sorted(IMAGE_EXTS))
        submit = st.form_submit_button("أكّد وابعت الطلب", type="primary", width="stretch")

    if submit:
        data = proof.getvalue() if proof else b""
        errors = []
        if not proof:
            errors.append("لازم ترفع سكرين التحويل.")
        elif not is_image(data):
            errors.append("سكرين التحويل لازم يكون صورة حقيقية (PNG أو JPG أو WEBP).")
        elif too_big(data):
            errors.append(f"حجم الصورة كبير، الحد الأقصى {MAX_UPLOAD_MB} ميجا.")
        if errors:
            for e in errors:
                st.error(e)
        else:
            ext = ext_of(proof.name)
            saved = save_bytes(B_PROOFS, data, ext if ext in IMAGE_EXTS else "png")
            token = secrets.token_urlsafe(24)
            try:
                tbl("orders").insert({
                    "token": token, "sheet_id": sheet["id"], "customer_id": cust["id"],
                    "name": cust["name"], "phone": cust["phone"],
                    "method": method, "price": int(sheet["price"]), "proof": saved,
                    "status": "pending", "created_at": now(),
                }).execute()
            except Exception:
                remove_file(B_PROOFS, saved)
                raise
            go(order=token)


@st.fragment(run_every=15)
def watch_status(token, status):
    current = get_order_status(token)
    st.caption("🔄 بنتابع حالة طلبك تلقائيًا، مش لازم تعمل ريفريش.")
    if current and current != status:
        st.rerun()


def bump_downloads(order_id, current):
    tbl("orders").update({"downloads": int(current) + 1}).eq("id", order_id).execute()


def page_order(token):
    header()
    o = get_order(token)
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
        try:
            data = fetch_sheet_file(o["file"])
        except Exception:
            data = None
        if data:
            st.download_button("⬇️ تحميل الشيت", data, file_name=o["original_name"],
                               on_click=bump_downloads, args=(o["id"], o["downloads"]),
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
    cust = current_customer()
    if cust and not o.get("customer_id"):
        st.info("الطلب ده مش متسجل على أي حساب. ضيفه لحسابك عشان تلاقيه دايمًا في «شيتاتي».")
        if st.button("➕ أضف الطلب ده لحسابي", key="claim_order", type="primary", width="stretch"):
            (tbl("orders").update({"customer_id": cust["id"]}).eq("id", o["id"])
             .is_("customer_id", "null").execute())
            st.rerun()
    elif cust and o.get("customer_id") == cust["id"]:
        st.caption("✅ الطلب ده متسجل على حسابك، هتلاقيه في «📥 شيتاتي».")
    elif not cust:
        st.info("📌 احفظ رابط الصفحة دي، أو سجّل دخولك من «📥 شيتاتي» وهتلاقي كل طلباتك محفوظة في حسابك. "
                "ولو الطلب ده قديم، سجّل دخول وافتح الرابط ده تاني وضيفه لحسابك.")


def page_my_sheets():
    """صفحة العميل: كل الشيتات اللي اشتراها، وتنزيل الشيتات المؤكدة."""
    header()
    st.subheader("📥 شيتاتي")

    cust = current_customer()
    if not cust:
        st.write("سجّل دخولك أو اعمل حساب جديد، وهتلاقي كل شيتاتك وطلباتك محفوظة في حسابك.")
        auth_forms("my")
        st.caption("نسيت كلمة السر؟ كلمنا على واتساب ونغيّرها لك.")
        return

    top1, top2 = st.columns([3, 1])
    top1.markdown(f"أهلًا **{md(cust['name'])}** 👋  \n{cust['phone']}")
    if top2.button("خروج", key="my_logout", width="stretch"):
        logout_session()
        st.rerun()

    orders = list_customer_orders(cust["id"])
    if not orders:
        st.info("لسه مفيش طلبات على حسابك. اختار شيت من الرئيسية واشتريه 📚")
    for o in orders:
        with st.container(border=True):
            st.markdown(f"**{md(o['title'])}** "
                        f"<span class='badge b-{o['status']}'>{STATUS_LABELS[o['status']]}</span>",
                        unsafe_allow_html=True)
            st.caption(f"{int(o['price'])} جنيه · {o['created_at']}")
            if o["status"] == "confirmed":
                key = f"ready_{o['id']}"
                if not st.session_state.get(key):
                    if st.button("⬇️ جهّز التحميل", key=f"prep_{o['id']}", type="primary", width="stretch"):
                        st.session_state[key] = True
                        st.rerun()
                else:
                    try:
                        data = fetch_sheet_file(o["file"])
                    except Exception:
                        data = None
                    if data:
                        st.download_button("⬇️ تحميل الشيت", data, file_name=o["original_name"],
                                           key=f"dl_{o['id']}", on_click=bump_downloads,
                                           args=(o["id"], o["downloads"]), type="primary", width="stretch")
                    else:
                        st.error("ملف الشيت مش متاح حاليًا، كلمنا على واتساب وهنحلها فورًا.")
            elif o["status"] == "pending":
                st.info("⏳ لسه بنراجع التحويل. أول ما نأكد الطلب هيظهر هنا زرار التحميل.")
            else:
                st.link_button("💬 الطلب اترفض، كلمنا على واتساب", f"https://wa.me/{WHATSAPP_NUMBER}",
                               width="stretch")

    pending_ids = [o["id"] for o in orders if o["status"] == "pending"]
    if pending_ids:
        watch_my_orders(pending_ids)

    with st.expander("⚙️ إعدادات الحساب"):
        with st.form("chg_pw"):
            old = st.text_input("كلمة السر الحالية", type="password", max_chars=60)
            new = st.text_input(f"كلمة السر الجديدة ({MIN_PW_LEN} على الأقل)", type="password", max_chars=60)
            new2 = st.text_input("أكّد كلمة السر الجديدة", type="password", max_chars=60)
            ok = st.form_submit_button("تغيير كلمة السر", type="primary", width="stretch")
        if ok:
            row = get_customer_by_phone(cust["phone"])
            if not row or not verify_pw(old, row):
                st.error("كلمة السر الحالية غلط.")
            elif len(new) < MIN_PW_LEN:
                st.error(f"كلمة السر الجديدة لازم تكون {MIN_PW_LEN} حروف أو أرقام على الأقل.")
            elif new != new2:
                st.error("كلمتين السر الجديدتين مش متطابقين.")
            else:
                set_password(cust["id"], new)
                st.success("تم تغيير كلمة السر ✅")


@st.fragment(run_every=20)
def watch_my_orders(pending_ids):
    """بيتابع الطلبات المنتظرة، وأول ما واحد يتأكد أو يترفض الصفحة بتتحدّث لوحدها."""
    rows = tbl("orders").select("id, status").in_("id", list(pending_ids)).execute().data or []
    st.caption("🔄 بنتابع طلباتك تلقائيًا، مش لازم تعمل ريفريش.")
    if any(r["status"] != "pending" for r in rows):
        st.rerun()


# ----------------------------------------------------------------------------
# لوحة التحكم
# ----------------------------------------------------------------------------
def decide(order_id, status):
    tbl("orders").update({"status": status, "decided_at": now()}).eq("id", order_id).execute()


def admin_orders_tab():
    pending, confirmed, revenue = get_stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("منتظرة", pending)
    c2.metric("مؤكدة", confirmed)
    c3.metric("المبيعات (جنيه)", revenue)

    flt = st.radio("الحالة", list(FILTERS), format_func=FILTERS.get, horizontal=True, key="flt")
    orders = list_orders(flt)
    if not orders:
        st.info("مفيش طلبات هنا.")
    elif len(orders) == 100:
        st.caption("بيتعرض آخر 100 طلب بس.")
    for o in orders:
        with st.container(border=True):
            left, right = st.columns([1, 2])
            try:
                left.markdown(img_html(fetch_proof(o["proof"]), ext_of(o["proof"]), 260, "contain"),
                              unsafe_allow_html=True)
            except Exception:
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
        elif too_big(sfile.getvalue()):
            st.error(f"الملف كبير، الحد الأقصى {MAX_UPLOAD_MB} ميجا.")
        else:
            cover_name = fname = None
            try:
                if cover and is_image(cover.getvalue()) and not too_big(cover.getvalue()):
                    cover_name = save_bytes(B_COVERS, cover.getvalue(), ext_of(cover.name))
                fname = save_bytes(B_SHEETS, sfile.getvalue(), ext_of(sfile.name))
                tbl("sheets").insert({
                    "title": title.strip(), "description": desc.strip(), "price": int(price),
                    "cover": cover_name, "file": fname, "original_name": clean_filename(sfile.name),
                    "active": bool(active), "created_at": now(),
                }).execute()
                st.success("تم إضافة الشيت ✅ (متخزن بشكل دائم)")
            except Exception as e:
                remove_file(B_COVERS, cover_name)
                remove_file(B_SHEETS, fname)
                st.error(f"حصلت مشكلة وإحنا بنحفظ الشيت: {e}")

    st.subheader("الشيتات الحالية")
    sheets = list_sheets(active_only=False)
    if not sheets:
        st.info("لسه مفيش شيتات.")
    for s in sheets:
        n = sheet_orders_count(s)
        label = f"{s['title']} — {s['price']} جنيه — {n} طلب" + ("" if s["active"] else " (مخفي)")
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
                if nf and too_big(nf.getvalue()):
                    st.error(f"الملف كبير، الحد الأقصى {MAX_UPLOAD_MB} ميجا.")
                else:
                    cover_name, fname, orig = s["cover"], s["file"], s["original_name"]
                    old_cover, old_file = None, None
                    try:
                        if nc and is_image(nc.getvalue()) and not too_big(nc.getvalue()):
                            old_cover = cover_name
                            cover_name = save_bytes(B_COVERS, nc.getvalue(), ext_of(nc.name))
                        if nf:
                            old_file = fname
                            fname = save_bytes(B_SHEETS, nf.getvalue(), ext_of(nf.name))
                            orig = clean_filename(nf.name)
                        tbl("sheets").update({
                            "title": t.strip() or s["title"], "description": d.strip(), "price": int(p),
                            "cover": cover_name, "file": fname, "original_name": orig, "active": bool(a),
                        }).eq("id", s["id"]).execute()
                        # بنمسح الملفات القديمة بعد ما الحفظ ينجح بس
                        remove_file(B_COVERS, old_cover)
                        remove_file(B_SHEETS, old_file)
                        st.success("تم الحفظ. حدّث الصفحة لو مش شايف التغيير.")
                    except Exception as e:
                        if old_cover:
                            remove_file(B_COVERS, cover_name)
                        if old_file:
                            remove_file(B_SHEETS, fname)
                        st.error(f"حصلت مشكلة وإحنا بنحفظ التعديلات: {e}")
            if n == 0:
                if st.button("🗑️ مسح الشيت", key=f"del_{s['id']}"):
                    try:
                        tbl("sheets").delete().eq("id", s["id"]).execute()
                        remove_file(B_SHEETS, s["file"])
                        remove_file(B_COVERS, s["cover"])
                        st.rerun()
                    except Exception as e:
                        st.error(f"مقدرناش نمسح الشيت: {e}")
            else:
                st.caption("الشيت عليه طلبات فمينفعش يتمسح — اقدر تخفيه بس.")


def admin_export_tab():
    st.info("✅ كل الشيتات والطلبات والصور متخزنة على Supabase، فمش بتتمسح لما الموقع ينام أو يتعمله ريستارت.")
    st.caption("ممكن تنزّل ملف بالطلبات تحتفظ بيه عندك (بيفتح في إكسل).")
    if st.button("تجهيز ملف الطلبات", key="mk_csv"):
        rows = (tbl("orders").select("*, sheets(title)").order("id", desc=True)
                .limit(1000).execute().data or [])
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["رقم الطلب", "الشيت", "الاسم", "الموبايل", "طريقة الدفع", "السعر",
                    "الحالة", "التحميلات", "وقت الطلب"])
        for o in rows:
            w.writerow([o["id"], (o.get("sheets") or {}).get("title", ""), o["name"], o["phone"],
                        METHODS.get(o["method"], o["method"]), o["price"],
                        STATUS_LABELS.get(o["status"], o["status"]), o["downloads"], o["created_at"]])
        st.session_state["orders_csv"] = buf.getvalue().encode("utf-8-sig")
    if st.session_state.get("orders_csv"):
        st.download_button("⬇️ تحميل الطلبات (CSV)", st.session_state["orders_csv"],
                           file_name="orders.csv", mime="text/csv", type="primary", width="stretch")


def admin_customers_tab():
    st.caption("حسابات العملاء. لو عميل نسي كلمة السر، حدّد له كلمة سر جديدة هنا وابعتها له على واتساب (وبتفك القفل لو الحساب مقفول).")
    digits = re.sub(r"\D", "", st.text_input("بحث برقم الموبايل", key="adm_cust_q", max_chars=15))
    qy = tbl("customers").select("id, name, phone, created_at, lock_until")
    if digits:
        qy = qy.ilike("phone", f"%{digits}%")
    rows = qy.order("id", desc=True).limit(50).execute().data or []
    if not rows:
        st.info("مفيش عملاء.")
    for c in rows:
        locked = int(c["lock_until"]) > int(time.time())
        with st.expander(f"{c['name']} — {c['phone']}" + (" 🔒" if locked else "")):
            st.caption(f"اتسجّل: {c['created_at']}" + (" · الحساب مقفول مؤقتًا" if locked else ""))
            with st.form(f"rp_{c['id']}"):
                npw = st.text_input("كلمة سر جديدة للعميل", max_chars=60)
                go_btn = st.form_submit_button("تغيير كلمة السر", type="primary", width="stretch")
            if go_btn:
                if len(npw) < MIN_PW_LEN:
                    st.error(f"كلمة السر لازم تكون {MIN_PW_LEN} حروف أو أرقام على الأقل.")
                else:
                    set_password(c["id"], npw)
                    st.success("تم تغيير كلمة السر ✅")


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

    t1, t2, t3, t4 = st.tabs(["الطلبات", "الشيتات", "العملاء", "تصدير"])
    with t1:
        admin_orders_tab()
    with t2:
        admin_sheets_tab()
    with t3:
        admin_customers_tab()
    with t4:
        admin_export_tab()


# ----------------------------------------------------------------------------
# التوجيه
# ----------------------------------------------------------------------------
params = st.query_params
try:
    if "order" in params:
        page_order(params["order"])
    elif "mysheets" in params:
        page_my_sheets()
    elif "admin" in params:
        page_admin()
    elif params.get("page") == "sheet" and str(params.get("id", "")).isdigit():
        page_sheet(int(params["id"]))
    else:
        page_home()
except Exception as e:  # st.rerun بيتعامل معاه ستريمليت بشكل منفصل ومش بيتمسك هنا
    st.error("حصلت مشكلة في الاتصال بقاعدة البيانات. جرّب تعمل ريفريش بعد شوية.")
    with st.expander("تفاصيل المشكلة (للأدمن)"):
        st.code(f"{type(e).__name__}: {e}", language=None)
