# TeamSpeak Server Info for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)

A Home Assistant integration for TeamSpeak 6 servers. It talks to the HTTP web query (not the old telnet ServerQuery) and exposes server statistics, plus a device per TeamSpeak user that you pick yourself, showing whether they are online, for how long, and what they are doing.

## Server device

Every virtual server becomes one device with these sensors:

| Sensor             | Description                                      | Attributes                                 |
| ------------------ | ------------------------------------------------ | ------------------------------------------ |
| Clients online     | Connected users, query clients not counted       | `client_list` (trimmed), `query_clients`   |
| Channels           | Number of channels                               | `channel_list`                             |
| Uptime             | Server uptime in seconds                         |                                            |
| Max clients        | Maximum allowed clients                          |                                            |
| Bandwidth received | Incoming bandwidth in bytes/s                    | `total_bytes`, `last_minute`               |
| Bandwidth sent     | Outgoing bandwidth in bytes/s                    | `total_bytes`, `last_minute`               |
| Server status      | Current server status                            | server name, version, platform, port       |

`client_list` only contains channel id, client id, database id, nickname and client type. IP addresses and unique identifiers are never exposed.

## Tracking users

Open **Settings → Devices & Services → TeamSpeak Server Info → Configure** and choose Add user, Edit user or Remove user. Adding a user means picking someone from the list of everyone the server has ever seen and giving them a display name. The list shows `Nickname (ID n)`, so two accounts with the same nickname can be told apart. Query clients are left out.

Each tracked user gets a device `TeamSpeak <name>` below the server device. Users are matched by their database id, never by nickname. The unique identifier is stored as a fallback in case database ids change.

| Entity                                            | Notes                                                                                                                                                                  |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `binary_sensor.tsonline_<name>`                   | Presence. Attributes: `since`, `since_estimated`, `nickname`, `database_id`, `channel`, `microphone_muted`, `headphones_muted`, `away`, `talking`                      |
| Microphone muted, Headphones muted, Away, Talking | Unavailable while the user is offline. Only headphones muted and away are enabled by default.                                                                          |
| Channel                                           | Channel name, unavailable while offline                                                                                                                                |
| Online since / last seen                          | Timestamp sensor                                                                                                                                                       |
| Total connections                                 | Diagnostic                                                                                                                                                             |

The presence sensor's entity id is `binary_sensor.tsonline_` followed by the slugified display name. If a template sensor already uses that id, rename or delete it first, otherwise Home Assistant appends `_2`. Renaming a user later changes the device name but keeps the entity id.

### How `since` works

While a user is online, `since` is the start of their current session. Once they leave, it becomes the moment the integration noticed it, and that value is stored on disk so it survives Home Assistant restarts. If the user left while Home Assistant was not running, there is no such moment. In that case `since` falls back to the start of their last session as reported by the server, and `since_estimated` is `true`.

### Load on the server

The TeamSpeak query runs on a single thread, so the integration keeps its traffic low and sends one request at a time. Every poll requests `serverinfo` and `clientlist`. `clientdblist` and `channellist` are requested at most every five minutes, which also means channel names and total connections update at that pace. If a poll fails, the entities become unavailable, the polling interval backs off up to 15 minutes, and a single warning is logged.

## Installation

### HACS

1. Open HACS, choose the three-dot menu and then Custom repositories.
2. Add `https://github.com/SamuelReithmeir/teamspeak_status_sensors` with the category Integration.
3. Install TeamSpeak Server Info and restart Home Assistant.

### Manual

Download the latest release from the [releases page][releases], copy `custom_components/samuelre_teamspeak` into your `custom_components` directory and restart Home Assistant.

## Setup

You need the web query enabled on your TeamSpeak server and an API key. Then add the integration under **Settings → Devices & Services → Add Integration** and enter:

- **Host**: address of the TeamSpeak server
- **Port**: web query port, 10080 by default
- **Virtual server ID**: usually 1
- **API key**: your web query API key
- **Update interval**: seconds between polls, 60 by default, minimum 5

## Examples

Notify when the server is full:

```yaml
automation:
  - alias: "TeamSpeak server full"
    triggers:
      - trigger: template
        value_template: >
          {{ states('sensor.teamspeak_server_clients_online') | int
             >= states('sensor.teamspeak_server_max_clients') | int }}
    actions:
      - action: notify.mobile_app
        data:
          message: "The TeamSpeak server is full."
```

How long has Bob been online (or offline)?

```yaml
template:
  - sensor:
      - name: "Bob TeamSpeak duration"
        state: >
          {% set since = state_attr('binary_sensor.tsonline_bob', 'since') %}
          {{ (now() - as_datetime(since)).total_seconds() | int if since else none }}
```

## Troubleshooting

If the integration cannot connect, check that the web query is enabled, that the port is reachable from Home Assistant, and that the API key is correct. A quick manual test:

```bash
curl -X POST "http://YOUR_SERVER_IP:10080/1/serverinfo?api-key=YOUR_API_KEY"
```

Avoid sending other query commands by hand in bursts. The TeamSpeak 6 beta handles them on one thread and can stop answering. Errors from the integration are logged under `custom_components.samuelre_teamspeak`.

## Development

Tests use mocked HTTP and masked fixtures, no live server is needed:

```bash
pip install -r requirements_test.txt
pytest
```

## License

MIT, see [LICENSE](LICENSE). This project is not affiliated with or endorsed by TeamSpeak Systems GmbH.

[releases-shield]: https://img.shields.io/github/release/SamuelReithmeir/teamspeak_status_sensors.svg
[releases]: https://github.com/SamuelReithmeir/teamspeak_status_sensors/releases
[license-shield]: https://img.shields.io/github/license/SamuelReithmeir/teamspeak_status_sensors.svg
