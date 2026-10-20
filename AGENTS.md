# Alwan release repository agent rules

Before modifying compatibility/**, read compatibility/CONTRACT.md.
Before modifying device-media/**, read PROTECTED_PUBLISHING.md, the isolated .github/release-guards/verify_media.py and media_integrity_guard.py, and the mandatory .github/workflows/infinix_media_integrity_ci.yml. Existing legacy bot staging also follows tools/infinix-image-bot/README.md.

Never push production data directly to main: always use a branch, PR and both required release checks.
Never delete published files or record IDs. Correct existing records in place and append new records.
For published media, retain all historical ZIP objects; controlled migrations may correct references only.
Do not weaken validators or integrity guards merely to make a change pass.
When a gate fails, report the exact policy/error code and repair the underlying data.

Compatibility data and device media are independently updatable production channels. APK/application releases are separate.

New tracked files in this PUBLIC distribution repository must be client data/media, public safety docs, or CI configuration only. Do not add new bot/research source files, source caches, internal reports, phone SQLite, logs, archived backups or credentials. The required `compatibility-contract` job checks new paths through `.github/release_scope_guard.py` before accepting updates. Existing legacy public tools remain temporarily until private migration is proven safe. Changes to distribution formats, existing published records, or old ZIPs are outside a bot-cleanup PR.

Required release validator sources live in .github/release-guards/ (production integrity only). The old research bot remains under tools/infinix-image-bot/ temporarily for the independent legacy discovery/publish workflow. The separate legacy_bot_regressions.yml test workflow is diagnostic and must never gain publishing privileges; release status contexts stay compatibility-contract and media-integrity.
