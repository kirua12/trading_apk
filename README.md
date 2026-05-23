# Android companion app

This folder is the first Android companion implementation for the trading app.

Important architecture note:

- WMCA/NH OpenAPI uses a Windows DLL, 32-bit Python worker, and certificate login.
- Android cannot load that DLL directly.
- The Android app therefore talks to a small PC bridge server.
- Keep the PC bridge on your trusted home network only. Do not port-forward it.

## Folder layout

- `pc_bridge/server.py`: Windows PC HTTP API bridge. It connects to WMCA and exposes account, positions, quotes, sellable quantity, manual orders, and Laoer tick.
- `mobile_expo/App.js`: Expo/React Native Android UI.
- `mobile_expo/package.json`: Expo project metadata.
- `run_pc_bridge.bat`: Starts the PC bridge with Anaconda Python.

## Start PC bridge

From this folder:

```bat
run_pc_bridge.bat --host 0.0.0.0 --port 8765 --token CHANGE_ME
```

Use `0.0.0.0` only on a trusted private network. If you only test from the same PC, use the default `127.0.0.1`.

## Android app

From `mobile_expo`:

```bat
npm install
npx expo start
```

In the app, set:

- Server URL: `http://<PC_LAN_IP>:8765`
- Token: the value passed with `--token`

## Certificate password helper

The app can act as a remote keyboard for the Windows certificate password
window. The intended flow is:

1. Start the bridge with a strong `--token`.
2. Tap `Connect` in the Android app so WMCA opens the certificate/password UI on the PC.
3. In `Search` -> `PC Certificate`, enter the certificate password.
4. Tap `Find Windows`, tap the matching certificate window if several are shown, then tap `Type to PC`.

The bridge only enables this helper when `--token` is set. The password is not
returned in API responses and is not written to bridge logs. Keep this bridge on
a trusted private network or VPN only. The bridge must run in the normal Windows
desktop session where the certificate window is visible, not as a background
Windows service.

If `Type to PC` says it succeeded but the PC field stays empty, click the
certificate password input on the PC once and try again. Some certificate
security modules block synthetic keyboard input; in that case the bridge can
detect and focus the window, but Windows may still refuse to deliver typed keys.

## Linux APK build

This folder is meant to be its own git repository. On Linux, build only the
Expo app under `mobile_expo`; the PC bridge stays on Windows.

See `BUILD_LINUX.md` for APK and AAB build commands.

## Current capabilities

- Connect WMCA on the PC.
- View account and positions.
- Search quote by ticker.
- Check sellable quantity.
- Send manual limit buy/sell orders through the PC bridge.
- Run Laoer tick through the existing Laoer runner.
- Type a one-time certificate password into the visible PC certificate window.

Laoer overseas order is still limited by the current broker implementation: the local WMCA adapter does not yet contain an overseas stock order TR. The bridge will expose the same blocked status rather than sending a wrong domestic order.
