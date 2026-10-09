# علوان — بوت صور Infinix (من الهاتف دون الماك)

**مكان التشغيل:** [GitHub Actions — Infinix Device Images](https://github.com/alifared89-dot/alwan-releases/actions/workflows/infinix_device_images.yml)

**المستودع:** `alifared89-dot/alwan-releases` — الفرع `main`.

## مراحل العمل

1. على الهاتف افتح رابط Actions، واضغط **Run workflow**، واختر `discover` ونطاق أرقام صفحات المتجر الرسمية (حتى 250 صفحة في التشغيل الواحد).
2. انتظر نجاح التشغيل؛ افتح **Artifacts → infinix-review** لتحميل تقرير `candidates.json` ولوحة `review_contact_sheet.jpg`. هذا *بحث فقط* ولا ينشر صوراً.
3. راجع الصور بنفسك أو اطلب من ChatGPT مراجعتها. لا تعتمد صورة أمام فقط أو خلف فقط؛ المطلوب **frontBack** حقيقي. راجع تطابق اسم وكود الجهاز مع الصفحة الرسمية، وكذلك حقوق إعادة الاستخدام قبل أي نشر.
4. عدّل [approved.json](./approved.json) من GitHub، وأضف فقط الصور الموافق عليها مع `deviceId`, `modelCode`, `officialPageId`, `imageUrl`, `sourceSha256`, `frontBackApproved: true`. يلزم بصمة الملف الأصلي من تقرير الاكتشاف، ولا يُقبل غياب أي حقل. مثال:

```json
{
  "items": [
    {
      "deviceId": "dev_EXAMPLE_REPLACE",
      "modelCode": "X0000",
      "officialPageId": 123,
      "imageUrl": "https://southeast-asia.pro.infinixmobility.com/media/catalog/product/EXAMPLE.png",
      "sourceSha256": "REPLACE_WITH_REAL_64_DIGIT_SHA256",
      "frontBackApproved": true
    }
  ]
}
```

5. شغّل نفس Workflow بوضع `publish` واكتب `PUBLISH_VERIFIED` في حقل التأكيد. يتأكد من الكود والصفحة والصورة والبصمات، ويقصها ويحفظها، ثم ينشر جميع الصور المقبولة عبر `GITHUB_TOKEN` ضمن نفس مستودع التحديثات.
6. افتح **علوان → التوافقات → Infinix** على الهاتف وأعد الدخول للقسم مع الاتصال بالإنترنت.

## للمحادثة الجديدة

أرسل هذا الرابط فقط:
`https://github.com/alifared89-dot/alwan-releases/tree/main/tools/infinix-image-bot`

ثم قل: «كمّل بوت صور Infinix من هذا المجلد. اقرأ README والبوت والـWorkflow، افحص آخر Run وآخر manifest، لا تستخدم الماك ولا ترفع صوراً غير موثقة. المراجعة قبل النشر إلزامية».

## الأمان والحدود

- لا مفاتيح من الماك. يستخدم GitHub Actions رمز `GITHUB_TOKEN` المؤقت بصلاحية `contents: write` لهذا المستودع فقط.
- فهرس `catalog-infinix.json` لقطة من 249 جهازاً في كود التطبيق بتاريخ إعداد البوت، ويجب تحديثه عند تغيير الأجهزة أو الأكواد.
- المصادر المستخدمة حالياً: صفحات متجر Infinix الرسمية؛ أسماء ملفات الصور ليست دليلاً كافياً على المطابقة.
- **الفحص البصري ليس آلياً**: لا يسمح النشر بدون اعتماد الصورة صراحة. لا تعني عبارة `frontBackApproved` أنها خضعت لمراجعة خارجية تلقائية.
- مفاتيح ترخيص التطبيق، توقيع APK، والنسخ الاحتياطي ليست جزءاً من هذا البوت.
- حقوق إعادة نشر الصور الرسمية لم تُحسم قانونياً؛ يلزم التأكد منها قبل توزيع الصور تجارياً.
- لا تكتب أسراراً أو Tokens داخل هذا المجلد أو المحادثة.
