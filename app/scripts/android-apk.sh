#!/bin/sh
# Build the debug Android APK (aarch64) for the mangaka (non-series) app.
# Requires: Android SDK + NDK 27, JDK 21, Rust target aarch64-linux-android.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
: "${ANDROID_HOME:=$HOME/Library/Android/sdk}"
if [ -z "${NDK_HOME:-}" ]; then NDK_HOME=$(ls -d "$ANDROID_HOME"/ndk/* | sort | tail -1); fi
export ANDROID_HOME NDK_HOME
cd "$root"
test -x node_modules/.bin/tauri || npm ci
npm run build
if [ ! -d "$root/src-tauri/gen/android" ]; then
  node_modules/.bin/tauri android init --ci
fi
# The WebView fetches the public reader API (https://mangaka.itonami.cloud),
# so INTERNET is required. The freshly generated manifest is patched
# idempotently here so the permission survives a fresh `android init`
# (gen/ is gitignored): without it the APK builds but cannot load works.
manifest="$root/src-tauri/gen/android/app/src/main/AndroidManifest.xml"
if [ -f "$manifest" ] && ! grep -q 'uses-permission.*INTERNET' "$manifest"; then
  python3 - "$manifest" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
perm = '<uses-permission android:name="android.permission.INTERNET" />'
text = text.replace("<manifest", perm + "\n    <manifest", 1) if "<manifest" in text else perm + "\n" + text
open(path, "w", encoding="utf-8").write(text)
PY
fi
# AGP packages incrementally into the old APK and keeps the space of replaced entries; start from none.
rm -rf "$root/src-tauri/gen/android/app/build/outputs/apk" "$root/src-tauri/gen/android/app/build/intermediates/apk"
node_modules/.bin/tauri android build --debug --apk --target aarch64 --ci
apk="$root/src-tauri/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk"
test -f "$apk"
shasum -a 256 "$apk"
