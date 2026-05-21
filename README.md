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

Laoer overseas order is still limited by the current broker implementation: the local WMCA adapter does not yet contain an overseas stock order TR. The bridge will expose the same blocked status rather than sending a wrong domestic order.
