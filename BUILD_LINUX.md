# Linux Android build guide

This guide builds only the Android client in `mobile_expo`. The WMCA bridge stays on the Windows PC because WMCA depends on a Windows DLL.

## Option A: EAS cloud APK

This is the simplest way to create an installable APK from Linux.
If EAS says the free Android build quota is used up, skip this option and use the local build below.

```bash
cd mobile_expo
npm install
npm install -g eas-cli
eas login
npm run apk:cloud
```

The `preview` profile in `eas.json` builds an `.apk` file that can be installed directly on Android.

## Option B: Local Android build

This does not use EAS cloud quota.

Requires Linux packages:

- Node.js 18 or newer
- JDK 17
- Android SDK / command line tools
- `ANDROID_HOME` set

Commands:

```bash
bash build_android_local.sh
```

Or run the same steps manually:

```bash
cd mobile_expo
npm install
npm run apk:local
```

The APK is usually created at:

```text
mobile_expo/android/app/build/outputs/apk/release/app-release.apk
```

If Android refuses to install it, build a debug APK first:

```bash
cd mobile_expo/android
./gradlew assembleDebug
```

Debug APK path:

```text
mobile_expo/android/app/build/outputs/apk/debug/app-debug.apk
```

## Runtime setup

On the Windows PC:

```bat
android_companion\run_pc_bridge.bat --host 0.0.0.0 --port 8765 --token CHANGE_ME
```

On Android:

- Server URL: `http://<WINDOWS_PC_LAN_IP>:8765`
- Token: `CHANGE_ME`

Keep the bridge on a private trusted network only.
