#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/mobile_expo"
APK_PATH="$APP_DIR/android/app/build/outputs/apk/release/app-release.apk"

cd "$APP_DIR"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required. Install Node.js 18 or newer first." >&2
  exit 1
fi

if ! command -v java >/dev/null 2>&1; then
  echo "Java JDK 17 is required. Install openjdk-17-jdk first." >&2
  exit 1
fi

if [ -z "${ANDROID_HOME:-}" ] && [ -z "${ANDROID_SDK_ROOT:-}" ]; then
  echo "ANDROID_HOME or ANDROID_SDK_ROOT is not set." >&2
  echo "Install Android SDK command-line tools and export ANDROID_HOME." >&2
  exit 1
fi

npm install
npx expo prebuild --platform android --no-install

cd "$APP_DIR/android"
./gradlew assembleRelease

echo
echo "APK created:"
echo "$APK_PATH"
