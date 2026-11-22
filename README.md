# تشغيل النسخة السحابية (حسابات + حفظ أونلاين + اشتراك)

## 1) Supabase
1. أنشئ مشروع على supabase.com.
2. SQL Editor ← New query ← الصق محتوى `setup.sql` ← Run.
3. Authentication ← URL Configuration: حط رابط موقعك في **Site URL** وفي **Redirect URLs**.
4. Authentication ← Providers ← Email: سيب التأكيد بالإيميل شغّال (مُوصى به)، أو قفله للتجربة.
5. Project Settings ← API: انسخ **Project URL** و **anon public key**.

## 2) config.js
اكتب الـ URL والـ key في `config.js` (مفتاح anon آمن إنه يبان في الموقع، الحماية من سياسات قاعدة البيانات).

## 3) الرفع
ارفع كل الملفات على GitHub Pages (في أول المستودع).

## 4) الاشتراك
- يدوي: بعد ما العميل يدفع (فودافون كاش/إنستاباي)، من Supabase ← Table Editor ← `subscriptions` ضيف صف فيه `user_id` و `status = active` و `current_period_end` (تاريخ نهاية الشهر).
- تلقائي: حط رابط الدفع في `CHECKOUT_URL`، وبوابة الدفع تبعت webhook يحدّث جدول `subscriptions` (محتاج Edge Function).
