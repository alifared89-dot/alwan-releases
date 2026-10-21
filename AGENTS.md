# Alwan release repository agent rules

Before modifying compatibility/**, read compatibility/CONTRACT.md.
Before modifying device-media/**, read PROTECTED_PUBLISHING.md, the isolated .github/release-guards/verify_media.py and media_integrity_guard.py, and the mandatory .github/workflows/infinix_media_integrity_ci.yml. All image discovery, originals, rights reviews and staging code are PRIVATE in `alwan-bot-control`.

Never push production data directly to main: always use a branch, PR and both required release checks.
Never delete published files or record IDs. Correct existing records in place and append new records.
For published media, retain all historical ZIP objects; controlled migrations may correct references only.
Do not weaken validators or integrity guards merely to make a change pass.
When a gate fails, report the exact policy/error code and repair the underlying data.

Compatibility data and device media are independently updatable production channels. APK/application releases are separate.

New tracked files in this PUBLIC distribution repository must be client data/media, public safety docs, or CI configuration only. Do not add new bot/research source files, source caches, internal reports, phone SQLite, logs, archived backups or credentials. The required `compatibility-contract` job checks new paths through `.github/release_scope_guard.py` before accepting updates. Public tools and the old manual image workflow were retired after independent PRIVATE discovery and manually reviewed Mac-to-public staging tests; never reintroduce them. Changes to distribution formats, existing published records, or old ZIPs are outside a bot-cleanup PR.

Required release validation code and all 42 regression tests reside in `.github/release-guards/` (PUBLIC, client-safe). They must remain independent, read-only and fully executable from PUBLIC without fetching PRIVATE source or credentials. EXACT required job contexts: `compatibility-contract` and `media-integrity`.

The research bot, original phone image evidence, 89 legacy research tests, and all 10 historical public bot tool source/config files remain PRIVATE under `alifared89-dot/alwan-bot-control`. Operator discovery uses PRIVATE `.github/workflows/private_image_discovery.yml`. A rights-reviewed image may be staged only from the trusted Mac with PRIVATE `maintenance/stage_reviewed_media_pr.py`, requiring a human rights/identity evidence packet and the exact manual submit confirmation. It must create a NEW branch + PUBLIC protected PR, NEVER auto-merge or write public main. Phone/Termux stays the research source of truth. Synthetic tests and schema-valid packets are NOT proof of legal image redistribution rights.

No `tools/**` content or old `.github/workflows/infinix_device_images.yml` may return to PUBLIC. This exact all-or-none 10-file retirement is enforced by `.github/release_scope_guard.py`, which pins the old Git blobs and prohibits mixing deletion with ANY customer media, compatibility or APK modification. Git history was NOT rewritten; previous public code remains visible in historical commits.
