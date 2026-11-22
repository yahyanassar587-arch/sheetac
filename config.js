// ===== إعدادات التطبيق — عدّل القيم دي بس =====
window.APP_CONFIG = {
  APP_NAME: "إدارة السايبر",

  // من Supabase: Project Settings ← API
  SUPABASE_URL: "",        // مثال: https://abcdxyz.supabase.co
  SUPABASE_ANON_KEY: "",   // المفتاح اللي اسمه anon / public (مش service_role!)

  // true = التطبيق يطلب اشتراك بعد انتهاء التجربة المجانية. false = من غير اشتراك (للتجربة).
  REQUIRE_SUBSCRIPTION: true,

  // رابط الدفع الشهري (Payment Link من بوابة الدفع). سيبه فاضي لو بتفعّل الاشتراك يدوي.
  CHECKOUT_URL: "",

  // رقم أو إيميل للتواصل بيظهر للي خلصت تجربته ومفيش رابط دفع
  SUPPORT: ""
};
