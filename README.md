# Alwan — Official Releases | إصدارات علوان

Public, **distribution-only** repository for the Alwan Android application. Installed devices retrieve published update metadata, compatibility information, and media from the production files on `main`.

هذا المستودع العام مخصص **لنشر تحديثات تطبيق علوان وبيانات التوافق والصور المعتمدة فقط**. أدوات البحث والبوت والملفات الأولية غير المنشورة ليست جزءاً من هذا المستودع.

## Published content | المحتوى المنشور

| Path | Purpose |
| --- | --- |
| [GitHub Releases](https://github.com/alifared89-dot/alwan-releases/releases) | Published Android APK packages and release notes |
| [`latest.json`](latest.json) | App version/build, download URL, file size, and SHA-256 digest |
| [`compatibility/manifest.json`](compatibility/manifest.json) | Compatibility data manifest; validated payloads live under `compatibility/payloads/` |
| [`device-media/distribution.json`](device-media/distribution.json) | Published device-image distribution and immutable ZIP archives |
| [`brand-media/distribution.json`](brand-media/distribution.json) | Brand-media distribution |

## Publication integrity | حماية النشر

- Changes to production data must be reviewed through a **Pull Request**; do not push customer data directly to `main`.
- The two required checks are **`compatibility-contract`** and **`media-integrity`**. Their release validators remain independent of the research bot.
- Published client records, identifiers, and image archives are protected against accidental deletion. A file appearing historical is **not** proof it is safe to remove.
- Research bot source, phone SQLite, unpublished image originals, internal reports, and credentials do **not** belong in this public repository.

Read [Protected Publishing](PROTECTED_PUBLISHING.md), [Agent Rules](AGENTS.md), and the [Compatibility Contract](compatibility/CONTRACT.md) before proposing changes.

**Note:** Older content may remain reachable through Git history. Removing a file from the current branch does not erase historical commits.
