# ha-zyxel

<img src="https://raw.githubusercontent.com/oscarsanchezdm/ha-zyxel/refs/heads/main/resources/logo.png" alt="Zyxel Logo" width="128"/>

__Home Assistant integration for Zyxel devices__

Fork of [zulufoxtrot/ha-zyxel](https://github.com/zulufoxtrot/ha-zyxel) with SMS support, device tracking, lighter default polling, and several reliability / UX fixes. See [Differences from upstream](#differences-from-upstream).

<img src="https://raw.githubusercontent.com/oscarsanchezdm/ha-zyxel/refs/heads/main/resources/screenshot.png" alt="Zyxel Screenshot" />

[![Open ha-zyxel on Home Assistant Community Store (HACS)](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=oscarsanchezdm&repository=ha-zyxel&category=integration)

## Differences from upstream

Compared with [zulufoxtrot/ha-zyxel](https://github.com/zulufoxtrot/ha-zyxel):

| Area | What this fork adds / changes |
|------|-------------------------------|
| **SMS** | `ha_zyxel.send_sms` service for cellular modems (e.g. FWA505). Uses the same encrypted `nr7101` session as sensors (avoids 401 from a separate plaintext login). |
| **Device tracking** | LAN clients as `device_tracker` entities, optional per-client diagnostic sensors, and a connectivity `binary_sensor`. Based on upstream [PR #57](https://github.com/zulufoxtrot/ha-zyxel/pull/57). |
| **Reboot** | Reboot button entity (also present in recent upstream). |
| **Session reliability** | Isolated cookies per router instance, authenticate before status fetch, bounded re-auth, self-heal by recreating the session on poll failure. |
| **Lighter defaults** | Core polls are `status` + `lanhosts` only. Optional OIDs (`cellwan_status`, `lan`, `Traffic_Status`, `cardpage_status`, EasyMesh, One Connect) are **off by default** and configurable. Disabling an option removes related entities. |
| **Fewer duplicates** | Overlapping fields from different API roots are collapsed to one sensor identity where appropriate. |
| **Numeric sensors** | Values like CPU usage are coerced to numbers for history/statistics. Most auto-generated router sensors are **diagnostic** and **disabled by default**. |
| **Uptime** | Duration device class where applicable, plus a stable **startup time** timestamp sensor. |
| **Memory** | Derived **memory usage %** sensor from Total/Free. |
| **Friendly names** | Readable entity names with translations in **English, Catalan, and French** (Home Assistant language setting). |
| **Options UI** | Configure scan interval, consider-home, track-all, and optional OID polls from the integration options dialog. |

Current integration version: **1.0.0**

## Supported devices

Confirmed working on (inherited from upstream, plus continued use on FWA505 and similar CPEs):

- AX7501-B0
- FWA505
- FWA510
- FWA710 5G V2
- LTE3202-M437
- LTE7490-M904
- LTE5398-M904
- NR5103E
- NR5103v2
- NR5307
- NR7101
- NR7102
- NR7302
- VMG3625-T50B
- VMG4005-B50A
- VMG8825-T50

Potentially compatible with a lot more devices.
If you test another model successfully, please open an [issue](https://github.com/oscarsanchezdm/ha-zyxel/issues) or pull request.

## Installation

Prerequisites:

1. The device must be reachable from your Home Assistant instance (same local network)
2. HTTP/HTTPS access must be enabled in the device settings (default on most models)

### Install via HACS (recommended)

1. Install HACS
2. Add this repository as a custom repository (or use the badge above)
3. Download **Zyxel** / `ha-zyxel`
4. Restart Home Assistant

### Install manually

1. Clone `https://github.com/oscarsanchezdm/ha-zyxel`
2. Copy `custom_components/ha_zyxel` into your HA `custom_components` directory
3. Restart Home Assistant

## Adding a device

1. Go to HA Settings → Devices & Services
2. Add Integration → search for **Zyxel**
3. Host: full URL, e.g. `https://192.168.1.1` (include the scheme)
4. Admin username and password
5. Submit

If connection fails, try `http://` instead of `https://`.

After setup, open **Configure** on the integration to set scan interval, device tracking, and optional OID polls.

## Adding cards to your dashboard

Add [this code](resources/card_example.yml) to your dashboard for cards similar to the screenshot. Follow the animation below.

Note: the Mushroom card extension is required for that example.

![](resources/import_demo.gif)

## Available entities

Entities are generated dynamically from what the router exposes (see [example status output](https://github.com/pkorpine/nr7101?tab=readme-ov-file#example-output)). Many diagnostic sensors are disabled by default — enable only what you need.

### Reboot button

Press **Reboot** on the device page, or call `button.press` on the reboot entity.

### Device tracking

LAN clients appear as `device_tracker` entities (with consider-home). Optional per-client sensors (signal, rates, etc.) and a connectivity binary sensor are disabled by default.

Options: **scan interval**, **consider home**, **track all**.

### Send SMS

On cellular devices that support SMS (e.g. FWA505):

```yaml
service: ha_zyxel.send_sms
data:
  number: "+34600111222"
  text: "Hello from Home Assistant"
```

Optional `device_id` is the config entry id when multiple Zyxel devices are configured.

## Support

Please submit an [issue](https://github.com/oscarsanchezdm/ha-zyxel/issues) on this fork.

## Credits

- Upstream project: [zulufoxtrot/ha-zyxel](https://github.com/zulufoxtrot/ha-zyxel)
- Device tracking / session work: [PR #57](https://github.com/zulufoxtrot/ha-zyxel/pull/57) and related contributions
- Router API library: [nr7101](https://github.com/zulufoxtrot/nr7101) (also [pkorpine/nr7101](https://github.com/pkorpine/nr7101))
