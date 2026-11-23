# Mangaka app (Tauri v3)

Awai Android (aarch64) Tauri v3 app for mangaka — the public reader's real
UI in the WebView. Debug APK only in this phase (no store signature).

## Identity (single definition)

This is a non-series app (see `tauri-series-app-scaffold` step 2): identity
is derived once from the repository name plus the canonical site, and
`app/package.json` `itonami` is the single definition that `tauri.conf.json`,
the Android `applicationId` and the store catalog id are generated from.
The series name-parse branch is not used.

- id: `network.itonami.mangaka`
- title / productName: `mangaka (漫画家) — AI manga publishing and reworking`
- source (repo name): `app-itonami-mangaka`
- origin / catalog: `https://mangaka.itonami.cloud` / `https://mangaka.itonami.cloud/api`

`npm run build` fails closed when `package.json` and `src-tauri/tauri.conf.json`
disagree with `blueprint.edn`; re-run the scaffold values after any
`blueprint.edn` change.

## First screen: reader (not studio)

Chosen: the reader's works list. Reasons — mobile consumption first;
the reader's client is pure DATA-driven JS already in `reader/` (`assets`
reader-client-js) and reads the public API with `access-control-allow-origin: *`;
the studio is a WASM-heavy canvas editor (`kami-genko`) aimed at desktop
and pulls image generation from murakumo, a heavier approval boundary.
The studio lands as a later phase behind its own broker/murakumo review.

## Network and approval boundary

- WebView fetches `GET https://mangaka.itonami.cloud/api/works` and
  `GET https://mangaka.itonami.cloud/api/work/<rkey>` plus page images
  `/img/<key>` on the same origin. CORS `*` verified against the live API.
- No POST, no secrets, no D1/R2, no broker, no murakumo in phase 1.
- Rust exposes only `awai_host_info`; there is no filesystem/shell/installer
  permission. The Android `INTERNET` permission is declared by
  `scripts/android-apk.sh` (see below).

## Build and test

- `npm ci`
- `npm run build`: static build into `app/dist/`.
- `npm test`: builds, then `node --test test/*.test.mjs`.
- `cargo build --locked` in `app/src-tauri` (after `cargo generate-lockfile`
  if the lock is absent).
- `npm run build:android`: via `sh scripts/android-apk.sh` (needs Android
  SDK + NDK 27, JDK 21, `aarch64-linux-android` Rust target).

## Screen inventory (390x844)

| Screen | States | Main operations |
|---|---|---|
| 作品一覧 (`#screen-works`) | loading / empty / error (retry) / loaded | search filter, refresh （↻), tap card → reader |
| 作品リーダー (`#screen-reader`) | loading / loaded / 404 / error (retry) | back （←), version bar, mode toggle （見開き/単頁/縦読）, tap zones left/right, swipe |
| このアプリについて (`#screen-about`) | static | bottom nav toggle only |

`dist/` and `src-tauri/gen/` are gitignored build artifacts; `dist/release.json`
pins sources by SHA-256 but is never committed.
