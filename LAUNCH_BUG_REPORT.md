# Bug Report: Game cards fail to launch on unrecognized hardware

**App:** GameHub Lite 5.1.4
**Affected method:** `LauncherHelper.fetchStartTypeInfoAndSwitchModeInternal`
**Symptom:** Tapping a game card or pressing A on a controller does nothing — the game never launches
**Device confirmed affected:** AYANEO Pocket FIT (Adreno 750 / Snapdragon 8 Gen 3)
**Affects:** Any device not present in GameHub's hardware whitelist

---

## Symptom

On an AYANEO Pocket FIT running Android 14, tapping any game card or pressing the controller A button on a game card has no visible effect. The app returns to the main screen without launching the game and without showing any error message to the user.

The same A button works correctly everywhere else in the app (sidebar navigation, menus, settings). The issue is specific to game card launch attempts, both via touch and controller.

---

## Root Cause

### The launch gate

Before any game is allowed to launch, `LauncherHelper.fetchStartTypeInfoAndSwitchModeInternal` (a Kotlin suspend function) runs. It checks the hardware and fetches a recommended launch configuration from the GameHub backend. If this function returns `false`, the launch is silently cancelled.

### The device path that fails

The coroutine checks the device against `DeviceWhiteListManager`. If the device adapter type is `GENERIC` (i.e. not a known branded device), it then checks two conditions before allowing the shortcut past the API call:

```kotlin
if (deviceName.isNotEmpty() && isGamepad) return true  // fast path: known gamepad
if (sharedPrefs.getBoolean(deviceName, false)) return true  // fast path: user already saw tip
```

The AYANEO Pocket FIT hits neither condition:
- `deviceName = "DEVICE"` (non-empty, so first check passes partially)
- **`isGamepad = false`** — the device's controller is not recognized as a gamepad by `HandleHelper.a(deviceName)`

Because `isGamepad` is `false`, both fast paths are skipped and the code falls through to the backend API call.

### The two API calls that fail

Two HTTP POST requests are made:

1. **`devices/getUnknownDevices`** — submits the device name to the server to get a tip/notice about unrecognized hardware
2. **`/vtouch/startType`** — fetches the recommended Wine/Proton launch configuration for the game

Both return **HTTP 404** on the AYANEO Pocket FIT. The server has no entry for this device.

### The JSON parsing crash

The app uses a `GsonConverter` to parse the HTTP response. When the server returns a 404 response, the response body is (or is interpreted as) the integer `404`. `GsonConverter.a()` passes this to `JSONObject(string)`, which throws:

```
org.json.JSONException: Value 404 of type java.lang.Integer cannot be converted to JSONObject
```

This is wrapped by the Drake.net library into:

```
com.drake.net.exception.ConvertException: https://gamehub-lite-api.emuready.workers.dev/devices/getUnknownDevices ...(null)
```

### The exception handler returns `false`

The `invokeSuspend` state machine has a single catch block for `java.lang.Exception` that routes all exceptions to a `:goto_9` handler. That handler reads:

```smali
:goto_9
invoke-virtual {v0}, Ljava/lang/Throwable;->printStackTrace()V   # prints stack trace (silently)

instance-of v0, v0, Lcom/drake/net/exception/NetUnknownHostException;
if-eqz v0, :cond_14          # if NOT a no-internet exception → jump to cond_14

invoke-static {v13}, ...Boxing;->a(Z)Ljava/lang/Boolean;   # v13 = true
return-object v0              # return true  (proceed with launch)

:cond_14
invoke-static {v11}, ...Boxing;->a(Z)Ljava/lang/Boolean;   # v11 = 0 = false
return-object v0              # return false (BLOCK launch)
```

In plain terms:
- `NetUnknownHostException` (no internet) → return `true` → proceed
- **Any other exception (including `ConvertException` from HTTP 404) → return `false` → block launch**

The `ConvertException` from the 404 response is not a `NetUnknownHostException`, so `false` is returned, and the game never launches. The stack trace is printed to logcat but **no error is shown to the user**.

### Why the controller A button also appears broken

The `KEYCODE_BUTTON_A` press on a game card fires the click handler, which calls into the launch flow, which calls `fetchStartTypeInfoAndSwitchModeInternal`, which immediately hits the API, gets 404, and returns `false`. The logcat shows `Cancelling event (no window focus)` for the A button UP event — this is a red herring. The window transition (a brief permission fragment) happens *because* the launch flow started, not because the A button was mishandled. The launch cancels at the API level before any game activity is started.

---

## Evidence from logcat

```
W/System.err: com.drake.net.exception.ConvertException:
              https://gamehub-lite-api.emuready.workers.dev/devices/getUnknownDevices ...(null:254)
    at LauncherHelper$fetchStartTypeInfoAndSwitchModeInternal$2$1$invokeSuspend$$inlined$Post$default$1.invokeSuspend(Unknown Source:139)
    ...
Caused by: org.json.JSONException: Value 404 of type java.lang.Integer cannot be converted to JSONObject
    at org.json.JSON.typeMismatch(JSON.java:112)
    at org.json.JSONObject.<init>(JSONObject.java:172)
    at com.xj.common.http.GsonConverter.a(Unknown Source:146)
    at LauncherHelper$fetchStartTypeInfoAndSwitchModeInternal$2$1$invokeSuspend$$inlined$Post$default$1.invokeSuspend(Unknown Source:117)

W/System.err: com.drake.net.exception.ConvertException:
              https://gamehub-lite-api.emuready.workers.dev/devices/getUnknownDevices ...(null:254)
    at LauncherHelper$fetchStartTypeInfoAndSwitchModeInternal$2$1$invokeSuspend$$inlined$Post$default$1.invokeSuspend(Unknown Source:139)
```

This appears every time a game card is tapped or the A button is pressed on a game card. The game never launches.

---

## Affected hardware profile

```
Device:     AYANEO Pocket FIT
Chipset:    Qualcomm Snapdragon 8 Gen 3
GPU:        Adreno 750 (driver 0762.24, build 07/17/24)
Android:    14 (API 34)
isGamepad:  false  (reported by HandleHelper)
Whitelist:  GENERIC  (not in DeviceWhiteListManager)
```

---

## The Fix

### Option A — Recommended: graceful API fallback in the exception handler

In `LauncherHelper$fetchStartTypeInfoAndSwitchModeInternal$2$1.invokeSuspend`, change the `:goto_9` exception handler to proceed with the current launch settings on any API error, not just on no-internet errors.

**Current behavior:**
```
Any exception other than NetUnknownHostException  →  return false  →  block launch
```

**Fixed behavior:**
```
Any exception (including HTTP 404 / ConvertException)  →  return true  →  proceed with current settings
```

The smali change is the removal of two lines from the `:goto_9` block:

```diff
     :goto_9
     invoke-virtual {v0}, Ljava/lang/Throwable;->printStackTrace()V

-    instance-of v0, v0, Lcom/drake/net/exception/NetUnknownHostException;
-    if-eqz v0, :cond_14

     invoke-static {v13}, Lkotlin/coroutines/jvm/internal/Boxing;->a(Z)Ljava/lang/Boolean;
     move-result-object v0
     return-object v0
```

In Kotlin source terms, this is equivalent to changing:

```kotlin
} catch (e: Exception) {
    e.printStackTrace()
    if (e is NetUnknownHostException) return@withContext true
    return@withContext false   // ← blocks all non-internet API failures
}
```

to:

```kotlin
} catch (e: Exception) {
    e.printStackTrace()
    return@withContext true    // ← API unavailable / error → use current settings
}
```

### Option B — Better long-term: handle non-200 responses in GsonConverter

`GsonConverter.a()` should check the HTTP response code before attempting to parse the body as JSON. If the response code is not 2xx, it should return `null` or throw a typed exception that the caller can handle gracefully, rather than passing the status code integer to `JSONObject()`.

### Option C — Better long-term: add AYANEO devices to the hardware whitelist

The AYANEO Pocket FIT, Air 1S, Flip DS, and similar Snapdragon-based handheld PCs are increasingly common GameHub Lite users. Adding them to `DeviceWhiteListManager` with the appropriate adapter type would route them through the non-GENERIC path and avoid hitting the `getUnknownDevices` API entirely.

---

## Impact

Any device that is:
1. Not in `DeviceWhiteListManager` (adapter type = GENERIC), **and**
2. Has `isGamepad = false` from `HandleHelper.a(deviceName)`, **and**
3. Is either offline, or the GameHub API returns 404 for the device

...will be completely unable to launch any game. The failure is silent — no toast, no dialog, no error state visible to the user.

Given that the AYANEO Pocket FIT is a dedicated gaming handheld running GameHub Lite as its primary purpose, this bug renders the core functionality of the app unusable on that hardware.

---

## Files

| File | Change |
|---|---|
| `LauncherHelper$fetchStartTypeInfoAndSwitchModeInternal$2$1.smali` (smali_classes5) | Remove `instance-of` + `if-eqz` from `:goto_9` exception handler |

The fix is 2 lines of smali removed (or ~2 lines of Kotlin changed). No new logic is added.
