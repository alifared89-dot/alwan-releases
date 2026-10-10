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

## اكتشاف بالفهرس الرسمي — نسخة تجريبية على الهاتف (بدون نشر)

تشغيل Termux من مجلد البوت: `python bot.py indexed-discover --limit 8`.

- يقرأ Sitemap رسمي من ماليزيا والعراق، بدون تخمين أرقام صفحات متجر متسلسلة.
- يربط أسماء الصفحات بكتالوج علوان ويحدد الأجهزة الناقصة والمنشورة.
- إذا تشابه الاسم بين أكثر من كود موديل، تبقى النتيجة للمراجعة فقط.
- يكتب تغطية كل جهاز ناقص وأسباب الغياب مع روابط تسويقية رسمية محتملة.
- المخرجات `output/official-index-report.json` ليست ترخيصاً أو موافقة نشر.
- أسماء الأجهزة والصور التسويقية لا تثبت كود العتاد أو منظر الأمام والخلف.
- اختبار المصدر المرجعي إلزامي؛ فشل المرجع يجعل التشغيل فاشلاً.
- الاختبارات: `python -m unittest test_discovery test_official_index -v`.
- لا يغير approved.json أو device-media أو main.
- ربط المسار الجديد بمركز التحكم السحابي يحتاج اختباراً مستقلاً قبل اعتماده.

### البحث الحقيقي عبر واجهة متجر Infinix الرسمية

لجهاز محدد ناقص الصور: `python bot.py store-search --name "SMART 10 Plus" --market malaysia --image-limit 3`.

- يستخدم واجهة البحث العامة الرسمية في متجر الشركة، وليس تخمين أرقام صفحات المنتج.
- يتحقق من SKU وكود الموديل داخل الكتالوج ثم يعيد فتح صفحة المنتج الرسمية للتحقق.
- يستبعد deviceId المنشور مسبقاً، أو SKU غير حاسم، أو اختلاف الاسم.
- ينزّل صوراً للمراجعة فقط ويسجل sourceSha256 بعد نجاح تحميل الصورة.
- المخرجات: `output/official-search-report.json` و`output/official-search-review.jpg`.
- ملاحظة: صور المعاينة ليست معتمدة تلقائياً لإظهار الأمام والخلف، وحقوق إعادة النشر غير مثبتة.
- لا تشغيل publish ولا تعديل manifest أو distribution في هذا الوضع.
- الاختبارات: `python -m unittest test_discovery test_official_index test_official_search -q`.

### تشغيل 20 موديل بالتوازي على الهاتف

- أول دفعة: `python batch_scan.py --limit 20 --workers 4 --images 3`
- الدفعة التالية بدون تكرار: `python batch_scan.py --offset 20 --limit 20 --workers 4 --images 3`
- البحث يستهلك الإنترنت والهاتف، وليس توكنات المحادثة لكل صفحة. عدد النتائج الصالحة يعتمد على توفر الصور والأكواد الصحيحة بالمصدر.
- مراجعة النتائج: `output/batch-review.json` و`output/batch-review-sheet.jpg`.
- كل نتيجة تحتاج فحص الأمام والخلف والحقوق قبل نشرها، ولا يلمس السكربت manifest أو approved.json.

### Multi-market discovery (read-only / تجريبي على الهاتف)

- `python multimarket_scan.py --limit 20 --offset 0 --market my --market iq --market np --market ng --market ph --market id --workers 4 --images 5`
- يختبر البحث الفعلي في متاجر Infinix الرسمية، ثم يفتح صفحات النتائج للتحقق من SKU والاسم قبل تنزيل الصور الأصلية.
- النطاقات المعتمدة محددة صراحة، ومنها نطاقات صور ماليزيا والعراق ونيجيريا ونيبال والفلبين وإندونيسيا. أي رابط غير مطابق يُرفض.
- ملفات المراجعة: `output/multimarket-review.json` و`output/multimarket-sheet.jpg`؛ صور المعاينة قابلة للتبديل عند كل تشغيل.
- نتيجة HTTP 200 لا تعني نجاح المهمة، ويعتبر الاختبار فاشلاً لو فشل مصدر مرجعي أو طلب API.
- لا يعتمد الصورة آلياً مهما تشابه الاسم: يلزم مراجعة فعلية للأمام والخلف والحقوق، ولا يستخدم وضع النشر إطلاقاً.
- الانتباه إلى روابط cache: تُزال وصلة الصورة المصغّرة المعروفة ضمن نفس نطاق الشركة لاسترجاع الصورة الأصلية، مع فحص الحجم والبصمة.

### Stage 2: catalog-first index + exact-view composition (Termux only)

**Immutable scope:** Infinix only; all outputs under `tools/infinix-image-bot/output/`. No edits to the Flutter application, releases/media manifests, approval records, or existing published photos.

**Fast catalog acquisition**, official live JSON:
```bash
python catalog_first.py --market iq --market my --market np --market ng --market ph --market id --max-details 20
```
- Tries one whole-catalog API query per market (100 rows/page, max 3 pages). For unsupported/empty sources, falls back to 7 known official family queries. Only the official domains enumerated in `multimarket_scan.py` are accessed. Use at most four workers for product-detail corroboration.
- Source products and raw API pages are cached for 12 hours in `output/catalog-first.sqlite`, each page committed immediately for resumable operation.
- A network-free retry is possible: `python catalog_first.py --market iq --market my --offline --max-details 0`. Requires those query pages to have been cached.
- `output/catalog-first-report.json` distinguishes verified original detail pages from unresolved name conflicts, missing photos and source failures.
- Never treats fuzzy name similarity as model-code verification; a code absent from the catalog is NOT auto-accepted. Unlike publishing, this stage fetches no product photos and changes no manifests.

**Separate front/back image composition**, only after verified matching device code and color:
```bash
python compose_views.py output/your-explicit-two-view-evidence.json
```
An evidence JSON document MUST include `deviceId`, `modelCode`, `colorKey`, and exactly two `sources` of roles `front` and `back`. Each source must have `localPath` under bot output, `sourceSha256`, same `deviceId`, `modelCode`, `colorKey`, `productEvidenceUrl`, and human-confirmed `visualRoleVerified: true`, `modelMatchVerified: true`. Images with complex opaque backgrounds are rejected; only homogenous nearly white can be removed conservatively. Aspect ratio, existing phone details, alpha transparency, and consistent back-left/front-right placement are preserved. Image output is `960×960 PNG RGBA`, review-only in `output/composites/`, never published.

**Safety/QA:** `python -m unittest test_catalog_first test_compose_views test_multimarket_scan -q`. Not even an exact SKU proves that two photos are the same color; source visual review remains mandatory. All sources need legitimate permitted access and attribution details for later distribution decisions. `publish()` is intentionally **NOT wired** to these new staged outputs.

### Measured fallback for storefronts that use marketing names in the SKU field

The official catalog-first pilot returned 351 regional product listings from six markets with 4 new HTTP requests and 2 prior cache hits. After exact catalog-SKU matching, 25 unpublished/unprepared catalog device names had a unique **exact product-name match** but no usable code in the storefront API SKU field. These cannot be automatically approved by name.

```bash
python official_model_evidence.py --max-models 20 --sources-per-model 2 --images 3
```

This bounded **evidence-only** fallback checks the product's official page title against the unique exact Infinix catalog name, and checks product gallery filenames for the **complete model code as an isolated token**, rejecting missing codes and mixed/other device variants. It deliberately rejects the HOT 12 PLAY NFC (X6816D) page if its gallery images only contain X6816, for example. Output: `output/official-model-evidence.json`, `output/official-model-evidence-sheet.jpg`; each run is archived. No image approval is automatic.

Once an operator independently reviews an individual photo and confirms **front+back on one transparent image**, stage it explicitly:

```bash
python stage_review_candidate.py --official-model-evidence --code X6853 --image-index 0
```

The stager checks deviceId, gallery's exact hardware model-code, official page evidence, SHA256, >=650px resolution, transparency and existing manifest/audit; rejects duplicates and conflicting content, and never edits publication data. Output is an independent PNG in phone Downloads plus a JSON audit record. No batch auto-approval.

**Observed pilot (not a guarantee):** 20 model names -> 16 model-evidence candidates, 27 source photos, 10 human-checked source composites with sufficient resolution/alpha staged for review, 7 incompatible official regional page leads rejected. Source gaps/old models still require alternative permitted image repositories or a separate front/rear composition step; do not claim all remaining 200+ devices are solved. Use `python progress_report.py` to check the cumulative state.

**Second evidence pass:** ten remaining corroborated candidates were found, four additional transparent 1000×1000 front+back images visually checked and staged. Total under this model-filename fallback: 14 new staged review PNGs; 22 total pending review when combined with the earlier 8. Source photos of 500×500 were deliberately not upscaled or accepted. An end-to-end separate front/back composition smoke test using two different genuine NOTE 30 Pro X678B official gallery pictures also passed; its distinct review-only PNG is available in Downloads. No GitHub push or publication happened.

### 2026-10-10: version 2 (bounded source caching + quality evidence)

- `evidence_cache.py` adds **SHA-256 checked and atomic** official image caches (30 days), positive corroborated source-page cache (24 hours), and known conflicting-variant negative cache (12 hours). The source URL still must match the explicitly allowed official market host; corrupt files fail closed, and no file cleanup is done.
- `official_model_evidence.py --offline` can reprocess prior official sources with no HTTP requests. Output explicitly reports `detailCacheHits`, `detailHttpRequests`, `imageCacheHits`, `imageHttpRequests`, `qualityEligibleImages`, and `qualityEligibleDevices`. Do not interpret a cached repeat as an improvement in first-time discovery yield.
- `quality_triage.py`: conservative source-image eligibility based on verified source SHA, exact hardware code in official gallery image filename, alpha transparency, visible size and resolution >=650 px. Passing is **not** evidence that a device is shown front and back; manual visual check remains mandatory.
- `github_manifest_guard.py` fetches the *public* main media manifest using **GitHub REST API**, compares it to the local file and fails if they differ. It never writes to GitHub and does not require OAuth tokens. On the tested run, GitHub and local manifests were identical (33 total, 32 Infinix).
- Source evaluation on user's phone: GSMArena pictures page and UniversalDisplay, All-Spares, IT-Ricambi, RapidGSM, Impextrom, and MobileLandLCD responded; GSMnet returned 403 (no bypass attempted); JabalMatch could not resolve DNS. Most of these are primarily parts/compatibility references, **not verified high-quality device render feeds**, so do not automatically trust or import images from them. A GSMArena Zero 20 photo was 606x562 / 710x309, too small for current >=650 px quality rule.
- The previous 14 high-resolution, manually-reviewed official source images passed all 14 new objective pixel/alpha/SHA/model-filename checks. Their subject, front/back viewpoints and color were already manually examined; passing the new gate is not an independent proof of image identity.
- Actual same-cohort **repeat-search benchmark (11 models / 18 official product-detail references):** uncached first test 15.8 seconds, 18 detail HTTP fetches and 8 image HTTP fetches, 6 candidates with 8 images (all below new quality threshold); verified offline cache pass 0.1 seconds, 18 positive+negative cached detail results, 8 image cache hits, 0 HTTP requests. This shows much faster **reprocessing**, not faster first-time acquisition or better yield for old devices. The cold run still needs network and source coverage.
- All updates are local under bot source and ignored output. No GitHub push, merge, publication, or deletes. New source adapters and higher-resolution sources remain future work; don't claim this pass solved the remaining old-device gaps.

Run:
```bash
python catalog_first.py --market iq --market my --market np --market ng --market ph --market id --offline --max-details 0
python official_model_evidence.py --max-models 15 --sources-per-model 2 --images 3 --offline
python github_manifest_guard.py
python -m unittest test_discovery test_official_index test_official_search test_batch_scan test_multimarket_scan test_catalog_first test_compose_views test_official_model_evidence test_evidence_cache test_github_manifest_guard -q
```

## 2026-10-10: multi-brand-safe engine upgrade (local, not yet pushed)

**Incremental architecture, without migrating the existing Infinix plugin paths:**
- `media_core.py` — **brand-neutral** source policy, trusted-host constraints, HTTPS and redirect blocking, bounded response, paced per-host connections, 403 pause, 429 `Retry-After` handling, and capped exponential retries for 502/503/504. Every brand must provide its own `SourcePolicy(brand,hosts,user_agent)` and is subject to the same network rules. It does **not** infer an image model or brand from a URL.
- `image_compositor.py` — **brand-neutral** RGBA layout, rear LEFT/front RIGHT, fixed output canvas, proportion-preserving scaling. `compose_views.py` delegates only geometry to this module while retaining the existing Infinix-specific deviceId/modelCode/colorKey and signed-source safeguards.
- `multimarket_scan.py` is still an **Infinix-specific adapter** with six explicitly validated regional markets. It now delegates transport to `media_core.fetch_https`; other vendor adapters can be created independently without altering the core.
- `catalog_first.py` fixes fallback pagination. Each storefront search term now counts its **own** product IDs; accumulated rows from a previous family no longer cause premature termination. Unit tests model two independent 250-row families and verify all 500 rows, plus truncated 480-item feeds. Local SQLite uses WAL and a 10s busy timeout to allow concurrent readers; existing cache is retained.
- `official_model_evidence.py` distinguishes **missing** model-code evidence from **different/mixed** model-code evidence while maintaining the existing fail-closed decision. Still no automatic model approval.
- `quality_triage.py`: exact model-code filename check precedes resolution tiering. 500x500 images with appropriate code and SHA become **reference-only for seeking a higher-resolution original**; never eligible for staging, publication, upscaling or face/back confirmation. Existing >=650 visual review quality rule remains unchanged.
- Tests `test_media_core.py` and `test_image_compositor.py` demonstrate reuse of the **same shared module** on synthetic Tecno and Samsung fixtures with no access to those providers. This validates architecture, *not* connectivity or authenticity of real alternate-brand catalogs.

**Live repeatable benchmark**: `python benchmark20.py` selects 20 presently missing/unprepared catalog device IDs using a fixed random seed. The current local indexed sources only contain official name leads for 11 of the 20; the remaining nine correctly have no available official source from this existing cached index. With isolated brand-new benchmark evidence cache: 18 official detail pages, 8 official images, 26 actual HTTP attempts, 17.6s; warm replay of identical cohort: 0 HTTP attempts, 0.1s. The cold execution has **not** been shown faster than the previous 15.8s uncached baseline (network variation). Six device IDs have *source image candidates* but zero photos satisfy the >=650px final-quality filter. Correctness: no new human or automated front/back approvals; 22 independent review photos stay unchanged, 32 Infinix photos still published. Result file is `output/benchmark20-engine-upgrade.json`, duplicated as `Download/Alwan-Infinix-Bot-Benchmark-20.json`.

**Live transport smoke test**: both official Iraqi shop detail `/shop/720` and Malaysian shop detail `/shop/767` responded successfully through the brand-neutral transport. `github_manifest_guard.py` confirmed read-only upstream and local main distribution manifests remain identical. The previously composed image of NOTE 30 Pro X678B was recomputed via the new shared compositor and retained **exactly the same SHA-256**, so its actual pixel image was not changed.

**Important before promoting this architecture across brands**: The existing `bot.py`, `catalog_first.py`, `evidence_cache.py` and Infinix registry contain vendor-specific assumptions. They remain isolated in Infinix adapter files for backward compatibility. No claim is made that Samsung/Tecno online discovery is currently implemented. Next adapter should consume shared `SourcePolicy` and `compose_photos`, have its own catalog/matching rules, and pass separate brand smoke tests before rollout. Until then only Infinix is allowed to run against live network sources.

No source pushes, merges, publication, protected branch writes, stage image approval or cache purge were performed in this round.
