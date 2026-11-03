import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from werkzeug.utils import secure_filename

# ----------------------------------------------------------------------------
# الإعدادات (غيّرها من متغيرات البيئة أو عدّل القيم الافتراضية هنا)
# ----------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)

STORE_NAME = os.environ.get("STORE_NAME", "متجر الشيتات")
INSTAPAY_HANDLE = os.environ.get("INSTAPAY_HANDLE", "yourname@instapay")
WALLET_NUMBER = os.environ.get("WALLET_NUMBER", "01000000000")
WALLET_NAME = os.environ.get("WALLET_NAME", "فودافون كاش / اتصالات كاش / أورنج كاش")
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "201000000000")  # بصيغة دولية بدون +
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")  # غيّرها!

DB_PATH = os.path.join(DATA_DIR, "store.db")
COVERS_DIR = os.path.join(BASE_DIR, "static", "covers")
SHEETS_DIR = os.path.join(DATA_DIR, "private", "sheets")   # ملفات الشيتات (مش متاحة للعامة)
PROOFS_DIR = os.path.join(DATA_DIR, "private", "proofs")   # سكرينات التحويل (للأدمن بس)
for d in (COVERS_DIR, SHEETS_DIR, PROOFS_DIR):
    os.makedirs(d, exist_ok=True)

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
SHEET_EXTS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip", "rar", "png", "jpg", "jpeg"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB


def _load_secret_key():
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(DATA_DIR, ".secret_key")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(key)
    return key


app.secret_key = _load_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


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
    decided_at TEXT,
    FOREIGN KEY (sheet_id) REFERENCES sheets(id)
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


with sqlite3.connect(DB_PATH) as _con:
    _con.executescript(SCHEMA)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------------------------
def ext_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def looks_like_image(file_storage):
    head = file_storage.stream.read(12)
    file_storage.stream.seek(0)
    return (head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG")
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"))


def save_upload(file_storage, folder, allowed_exts, image_only=False):
    """يحفظ الملف باسم عشوائي ويرجّع (الاسم الجديد، الاسم الأصلي) أو None لو مش مسموح."""
    if not file_storage or not file_storage.filename:
        return None
    ext = ext_of(file_storage.filename)
    if ext not in allowed_exts:
        return None
    if image_only and not looks_like_image(file_storage):
        return None
    new_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(folder, new_name))
    original = secure_filename(file_storage.filename) or f"sheet.{ext}"
    return new_name, original


def remove_file(folder, name):
    if name:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
PHONE_RE = re.compile(r"^01[0125][0-9]{8}$")

METHODS = {
    "instapay": "انستا باي (InstaPay)",
    "wallet": "محفظة إلكترونية (فودافون كاش وغيرها)",
}
STATUS_LABELS = {"pending": "قيد المراجعة", "confirmed": "تم التأكيد", "rejected": "مرفوض"}


# ----------------------------------------------------------------------------
# CSRF + قوالب
# ----------------------------------------------------------------------------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def protect_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400)


@app.context_processor
def inject_globals():
    return dict(
        csrf_token=csrf_token,
        store_name=STORE_NAME,
        instapay_handle=INSTAPAY_HANDLE,
        wallet_number=WALLET_NUMBER,
        wallet_name=WALLET_NAME,
        whatsapp_number=WHATSAPP_NUMBER,
        methods=METHODS,
        status_labels=STATUS_LABELS,
        is_admin=bool(session.get("admin")),
    )


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


# ----------------------------------------------------------------------------
# صفحات العملاء
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    sheets = query("SELECT * FROM sheets WHERE active=1 ORDER BY id DESC")
    return render_template("index.html", sheets=sheets)


@app.route("/sheet/<int:sheet_id>", methods=["GET", "POST"])
def sheet_detail(sheet_id):
    sheet = query("SELECT * FROM sheets WHERE id=? AND active=1", (sheet_id,), one=True)
    if not sheet:
        abort(404)

    form = {"name": "", "phone": "", "method": "instapay"}
    if request.method == "POST":
        form["name"] = request.form.get("name", "").strip()[:80]
        form["phone"] = request.form.get("phone", "").strip().translate(AR_DIGITS)
        form["method"] = request.form.get("method", "")
        proof = request.files.get("proof")

        errors = []
        if len(form["name"]) < 3:
            errors.append("اكتب اسمك بالكامل.")
        if not PHONE_RE.match(form["phone"]):
            errors.append("رقم الموبايل غير صحيح (مثال: 01012345678).")
        if form["method"] not in METHODS:
            errors.append("اختار طريقة الدفع.")
        if not proof or not proof.filename:
            errors.append("لازم ترفع سكرين التحويل.")

        saved = None
        if not errors:
            saved = save_upload(proof, PROOFS_DIR, IMAGE_EXTS, image_only=True)
            if not saved:
                errors.append("سكرين التحويل لازم يكون صورة (PNG أو JPG أو WEBP).")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("sheet.html", sheet=sheet, form=form), 400

        token = secrets.token_urlsafe(24)
        execute(
            "INSERT INTO orders (token, sheet_id, name, phone, method, proof, status, created_at) "
            "VALUES (?,?,?,?,?,?, 'pending', ?)",
            (token, sheet_id, form["name"], form["phone"], form["method"], saved[0], now()),
        )
        mine = session.get("my_orders", [])
        mine.append(token)
        session["my_orders"] = mine[-20:]
        flash("وصلنا طلبك! هنراجع التحويل ونأكد في أقرب وقت.", "success")
        return redirect(url_for("order_status", token=token))

    return render_template("sheet.html", sheet=sheet, form=form)


@app.route("/order/<token>")
def order_status(token):
    order = query(
        "SELECT o.*, s.title, s.price FROM orders o JOIN sheets s ON s.id=o.sheet_id WHERE o.token=?",
        (token,), one=True)
    if not order:
        abort(404)
    return render_template("order.html", order=order)


@app.route("/my-orders")
def my_orders():
    tokens = session.get("my_orders", [])
    orders = []
    if tokens:
        marks = ",".join("?" * len(tokens))
        orders = query(
            f"SELECT o.*, s.title, s.price FROM orders o JOIN sheets s ON s.id=o.sheet_id "
            f"WHERE o.token IN ({marks}) ORDER BY o.id DESC", tokens)
    return render_template("my_orders.html", orders=orders)


@app.route("/download/<token>")
def download(token):
    order = query(
        "SELECT o.*, s.file, s.original_name FROM orders o JOIN sheets s ON s.id=o.sheet_id WHERE o.token=?",
        (token,), one=True)
    if not order or order["status"] != "confirmed":
        abort(403)
    path = os.path.join(SHEETS_DIR, order["file"])
    if not os.path.exists(path):
        abort(404)
    execute("UPDATE orders SET downloads = downloads + 1 WHERE id=?", (order["id"],))
    return send_file(path, as_attachment=True, download_name=order["original_name"])


# ----------------------------------------------------------------------------
# لوحة التحكم
# ----------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return wrapper


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if secrets.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
            session["admin"] = True
            return redirect(url_for("admin_orders"))
        flash("كلمة السر غلط.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@app.route("/admin/orders")
@admin_required
def admin_orders():
    status = request.args.get("status", "pending")
    sql = ("SELECT o.*, s.title, s.price FROM orders o JOIN sheets s ON s.id=o.sheet_id")
    args = ()
    if status in STATUS_LABELS:
        sql += " WHERE o.status=?"
        args = (status,)
    else:
        status = "all"
    sql += " ORDER BY o.id DESC"
    orders = query(sql, args)
    stats = {
        "pending": query("SELECT COUNT(*) c FROM orders WHERE status='pending'", one=True)["c"],
        "confirmed": query("SELECT COUNT(*) c FROM orders WHERE status='confirmed'", one=True)["c"],
        "revenue": query(
            "SELECT COALESCE(SUM(s.price),0) t FROM orders o JOIN sheets s ON s.id=o.sheet_id "
            "WHERE o.status='confirmed'", one=True)["t"],
    }
    return render_template("admin_orders.html", orders=orders, status=status, stats=stats)


@app.route("/admin/proof/<int:order_id>")
@admin_required
def admin_proof(order_id):
    order = query("SELECT proof FROM orders WHERE id=?", (order_id,), one=True)
    if not order:
        abort(404)
    return send_from_directory(PROOFS_DIR, order["proof"])


@app.route("/admin/orders/<int:order_id>/<action>", methods=["POST"])
@admin_required
def admin_decide(order_id, action):
    if action not in ("confirm", "reject", "reset"):
        abort(404)
    order = query("SELECT id FROM orders WHERE id=?", (order_id,), one=True)
    if not order:
        abort(404)
    new_status = {"confirm": "confirmed", "reject": "rejected", "reset": "pending"}[action]
    execute("UPDATE orders SET status=?, decided_at=? WHERE id=?", (new_status, now(), order_id))
    flash({"confirm": "تم تأكيد الطلب ✅ والعميل يقدر ينزّل الشيت دلوقتي.",
           "reject": "تم رفض الطلب.",
           "reset": "الطلب رجع قيد المراجعة."}[action], "success")
    return redirect(request.referrer or url_for("admin_orders"))


@app.route("/admin/sheets")
@admin_required
def admin_sheets():
    sheets = query(
        "SELECT s.*, (SELECT COUNT(*) FROM orders o WHERE o.sheet_id=s.id) AS orders_count "
        "FROM sheets s ORDER BY s.id DESC")
    return render_template("admin_sheets.html", sheets=sheets)


def _sheet_form_values():
    title = request.form.get("title", "").strip()[:120]
    description = request.form.get("description", "").strip()[:2000]
    price_raw = request.form.get("price", "").strip().translate(AR_DIGITS)
    active = 1 if request.form.get("active") else 0
    return title, description, price_raw, active


@app.route("/admin/sheets/new", methods=["GET", "POST"])
@admin_required
def admin_sheet_new():
    if request.method == "POST":
        title, description, price_raw, active = _sheet_form_values()
        errors = []
        if not title:
            errors.append("اكتب عنوان الشيت.")
        if not price_raw.isdigit() or int(price_raw) <= 0:
            errors.append("السعر لازم يكون رقم أكبر من صفر.")
        sheet_file = request.files.get("file")
        saved_file = None
        if not errors:
            saved_file = save_upload(sheet_file, SHEETS_DIR, SHEET_EXTS)
            if not saved_file:
                errors.append("ارفع ملف الشيت (PDF أو Word أو غيره).")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("admin_sheet_form.html", sheet=None, form=request.form), 400
        cover = save_upload(request.files.get("cover"), COVERS_DIR, IMAGE_EXTS, image_only=True)
        execute(
            "INSERT INTO sheets (title, description, price, cover, file, original_name, active, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (title, description, int(price_raw), cover[0] if cover else None,
             saved_file[0], saved_file[1], active, now()))
        flash("تم إضافة الشيت.", "success")
        return redirect(url_for("admin_sheets"))
    return render_template("admin_sheet_form.html", sheet=None, form={"active": "1"})


@app.route("/admin/sheets/<int:sheet_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_sheet_edit(sheet_id):
    sheet = query("SELECT * FROM sheets WHERE id=?", (sheet_id,), one=True)
    if not sheet:
        abort(404)
    if request.method == "POST":
        title, description, price_raw, active = _sheet_form_values()
        errors = []
        if not title:
            errors.append("اكتب عنوان الشيت.")
        if not price_raw.isdigit() or int(price_raw) <= 0:
            errors.append("السعر لازم يكون رقم أكبر من صفر.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("admin_sheet_form.html", sheet=sheet, form=request.form), 400

        file_name, original = sheet["file"], sheet["original_name"]
        new_file = save_upload(request.files.get("file"), SHEETS_DIR, SHEET_EXTS)
        if new_file:
            remove_file(SHEETS_DIR, file_name)
            file_name, original = new_file
        cover_name = sheet["cover"]
        new_cover = save_upload(request.files.get("cover"), COVERS_DIR, IMAGE_EXTS, image_only=True)
        if new_cover:
            remove_file(COVERS_DIR, cover_name)
            cover_name = new_cover[0]
        execute(
            "UPDATE sheets SET title=?, description=?, price=?, cover=?, file=?, original_name=?, active=? WHERE id=?",
            (title, description, int(price_raw), cover_name, file_name, original, active, sheet_id))
        flash("تم حفظ التعديلات.", "success")
        return redirect(url_for("admin_sheets"))
    return render_template("admin_sheet_form.html", sheet=sheet, form={
        "title": sheet["title"], "description": sheet["description"],
        "price": sheet["price"], "active": "1" if sheet["active"] else ""})


@app.route("/admin/sheets/<int:sheet_id>/toggle", methods=["POST"])
@admin_required
def admin_sheet_toggle(sheet_id):
    execute("UPDATE sheets SET active = 1 - active WHERE id=?", (sheet_id,))
    return redirect(url_for("admin_sheets"))


@app.route("/admin/sheets/<int:sheet_id>/delete", methods=["POST"])
@admin_required
def admin_sheet_delete(sheet_id):
    sheet = query("SELECT * FROM sheets WHERE id=?", (sheet_id,), one=True)
    if not sheet:
        abort(404)
    has_orders = query("SELECT COUNT(*) c FROM orders WHERE sheet_id=?", (sheet_id,), one=True)["c"]
    if has_orders:
        flash("الشيت ده عليه طلبات فمينفعش يتمسح. اخفيه بدل ما تمسحه.", "error")
    else:
        remove_file(SHEETS_DIR, sheet["file"])
        remove_file(COVERS_DIR, sheet["cover"])
        execute("DELETE FROM sheets WHERE id=?", (sheet_id,))
        flash("تم مسح الشيت.", "success")
    return redirect(url_for("admin_sheets"))


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="الصفحة دي مش موجودة."), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="مش مسموح لك تفتح الصفحة دي. لو دفعت استنى التأكيد."), 403


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message="حصلت مشكلة في الطلب. ارجع جرّب تاني."), 400


@app.errorhandler(413)
def too_large(e):
    return render_template("error.html", code=413, message="الملف حجمه كبير (الحد الأقصى 64 ميجا)."), 413


if __name__ == "__main__":
    if ADMIN_PASSWORD == "admin123":
        print("⚠️  غيّر ADMIN_PASSWORD قبل ما تنشر الموقع!")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
