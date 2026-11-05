# Mac app development

The Mac app lives under `apple/`. It is a SwiftUI shell that starts `fo serve` as a child
process and shows the dashboard in a `WKWebView`; all office logic stays in the Python package.

```text
apple/
  project.yml                 XcodeGen spec (source of truth for the Xcode project)
  FamilyOffice.xcodeproj      generated from project.yml, committed
  FamilyOffice/
    App/                      @main app, AppState, ServerProcess, WebView, ContentView,
                              Power, LoginItem, CommandLineTool, FoCommand, SessionPrimer
    MenuBar/                  the menu bar item and the 30 s status poller
    Settings/                 the Settings window: General, Devices, Advanced
    Assets.xcassets           placeholder icon
    Info.plist                generated from project.yml, committed
  FOKit/                      Swift package shared with the iOS app: Handshake, APIClient, Reachability,
                              OfficeSummary, Tailscale, Pairing (payload and QR), Subprocess (macOS)
  Scripts/bundle-python.sh    builds apple/Resources/fo (the bundled runtime)
  Resources/fo/               build product, git-ignored
```

Requirements: Xcode 16 or later (Swift 6), macOS 14 or later, `uv`, and
[XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`) when you change the
project.

## Generate the project

Edit `apple/project.yml`, never the `.xcodeproj`, then:

```sh
cd apple
xcodegen generate
```

Commit `project.yml`, `FamilyOffice.xcodeproj` and `FamilyOffice/Info.plist` together. CI
regenerates the project and fails when the committed files differ.

## Build and test

```sh
cd apple/FOKit && swift build && swift test
cd apple && xcodebuild -project FamilyOffice.xcodeproj -scheme FamilyOffice \
  -configuration Debug CODE_SIGNING_ALLOWED=NO build
```

Signing, notarization and the universal release build come later; development builds are
unsigned (or ad-hoc signed by Xcode).

## Bundle Python

```sh
apple/Scripts/bundle-python.sh
```

The script, runnable from any directory and safe to run again:

1. downloads the python-build-standalone 3.12 `install_only` archive for the host architecture
   (`FO_BUNDLE_ARCH=x86_64` or `arm64` overrides it) by the exact tag and SHA-256 pinned at the
   top of the script, caching it under `apple/build/python-cache/`;
2. unpacks it to `apple/Resources/fo/python/`;
3. builds the wheel with `uv build --wheel` and installs it, with the dependency versions from
   `uv.lock` (hash-checked), into the relocatable virtual environment `apple/Resources/fo/venv/`;
4. prunes `__pycache__`, `test`, `tests`, `idlelib`, `tkinter` (with Tcl/Tk), `ensurepip` and
   docs;
5. writes `apple/Resources/fo/bin/fo`, the launcher the app runs, and prints the bundle size
   (about 95 MB for arm64).

When `apple/Resources/fo/` exists, the build copies it to `Contents/Resources/fo` in the app.
Without it the app builds anyway and finds `fo` as described below. The bundle is never
committed. To move to a new python-build-standalone release, update the tag, version and both
checksums together from the release's `SHA256SUMS`.

## Run against a repo checkout

The app resolves the `fo` executable in this order and never uses a `fo` on `PATH`:

1. `FamilyOffice.app/Contents/Resources/fo/bin/fo` (the bundled runtime);
2. the `FO_EXECUTABLE` environment variable;
3. the `foExecutablePath` user default (development only).

For development against your checkout, build without `apple/Resources/fo/` and point the app at
the checkout's virtual environment:

```sh
uv sync
uv run fo setup /tmp/fo-dev-office --offline       # a synthetic office
FO_EXECUTABLE="$PWD/.venv/bin/fo" \
  path/to/DerivedData/.../FamilyOffice.app/Contents/MacOS/FamilyOffice \
  -officePath /tmp/fo-dev-office
```

In Xcode, set `FO_EXECUTABLE` under Product > Scheme > Edit Scheme > Run > Environment, or run
`defaults write com.familyoffice.app foExecutablePath ~/path/to/family-office/.venv/bin/fo`.
The `-officePath` argument overrides the stored office for one launch without writing it.

Before starting the server the app runs `fo --version` and refuses to start unless the output
contains `FOExpectedVersion` from `Info.plist` (set in `project.yml`; keep it equal to the
version in `pyproject.toml`).

## Handshake contract

The app launches:

```text
fo [--office PATH] serve --port 0 --app
fo [--office PATH] serve --remote --app     # with Allow phone access over Tailscale on
```

with stdin closed, the working directory set to the home folder, and a scrubbed environment:
`PATH` is the runtime's `bin` plus `/usr/bin:/bin`; `HOME`, `USER`, `LANG`, `TMPDIR` and, when
set, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CONFIG_DIR` and `CODEX_HOME` pass
through; `PYTHONUNBUFFERED=1` is added. Port 0 lets the system choose a free loopback port.
With phone access on, the app omits `--port` so the server takes `[serve] port` from
`office.toml` (default 4790) and `tailscale serve --bg PORT` keeps pointing at it.

The first stdout line is one JSON object:

```json
{"port": 4790, "token": "<per-launch secret>", "office": "/path/or/null", "state": "ready", "version": "2.0.0"}
```

`port` and `token` are required; a line without them, or with anything after the object, is
rejected (`FOKit.Handshake.parse`). After the handshake the server behaves exactly like
`fo serve`. The app loads `http://127.0.0.1:<port>/?t=<token>` in the web view, which sets the
session cookie; it never sends the token in its own requests. `FOKit.APIClient` authenticates
with the cookie copied from the web view's store.

Transitional fallback: until every supported `fo` has `--app`, the app checks `fo serve --help`
for the flag and omits it when absent. A first stdout line that is not JSON then counts as no
handshake, and the app takes port and token from the printed `  Open: http://127.0.0.1:PORT/?t=TOKEN`
line (`Handshake.parseOpenLine`). Remove both once the minimum supported version prints the
handshake.

The token is never logged or stored: the rest of stdout and all of stderr go to an in-memory log
of the last 500 lines with the token and any `t=` query value redacted, and nothing is written
to disk. The web view uses a non-persistent website data store created per launch, so the
cookie dies with the app.

## What the app stores

`UserDefaults` (domain `com.familyoffice.app`):

| Key                    | Value                                                                  |
| ---------------------- | ---------------------------------------------------------------------- |
| `officePath`           | the office folder (first-launch sheet or General > Change…)            |
| `keepAwakeWhilePaired` | General > Keep Mac awake while a phone is paired                       |
| `allowPhoneAccess`     | General > Allow phone access over Tailscale (`fo serve --remote`)      |
| `settingsTab`          | the Settings tab shown last (`general`, `devices`, `advanced`)         |
| `foExecutablePath`     | development only: a `fo` to run when no bundle is present              |

Launch at login is not a default: macOS keeps it (`SMAppService.mainApp`), and the toggle
reads its status every time General appears. Every `office.toml` setting (port, run caps,
retention, web fetch cap, tailnet name) is written by `fo config set` and read by
`fo config get`; the app never edits the file. Outside the office the app writes only the
optional `/usr/local/bin/fo` link. Nothing else: no tokens, cookies, pairing codes, logs or
office data. Pairing codes exist only in memory and on screen.

Any default can be set for one launch on the command line without writing it, for example
`-allowPhoneAccess YES -keepAwakeWhilePaired YES -settingsTab devices`. Debug builds also
accept `-openSettingsOnLaunch YES`, which opens Settings without clicking.

The app logs state changes to the unified log under subsystem `com.familyoffice.app`
(categories `monitor`, `power`, `settings`): kinds and counts only, never names, paths,
codes or tokens. Read them with:

```sh
/usr/bin/log show --last 5m --info --predicate 'subsystem == "com.familyoffice.app"' --style compact
```

## Menu bar and power

The menu bar item lists the office folder, the sync age (`office.last_sync.as_of` from
`/api/status`), `Run in progress: <advisor>` while `/api/runs` has a queued, running or
verifying run, and `Phone: reachable` (seen in the last five minutes) or
`Phone: last seen <time>` from `/api/devices`, then Open Family Office, Restart Server,
Settings… and Quit. It polls the three routes every 30 seconds through `FOKit.APIClient`,
each on its own, so a server without chat still shows status and devices.

Closing the main window does not quit: the menu bar keeps the app and its server running.
After a restart an off-screen web view (`SessionPrimer`) loads the new landing URL into the
same non-persistent store to get the cookie, so polling works with no window open.

`Power` holds one `PreventUserIdleSystemSleep` assertion (reason "Family Office keeps this
Mac awake so a paired phone can reach it.") only while keep awake is on and the devices list
is non-empty, and releases it when either changes and on quit. `pmset -g assertions` shows it.

## Settings

- **General.** Office folder (Change… picks a folder and restarts the server); Launch at
  login (`SMAppService.mainApp`, with the Login Items link while macOS reports
  `requiresApproval`); Allow phone access over Tailscale (runs `--remote`; refused until
  `serve.tailnet_name` is set); Keep Mac awake while a phone is paired (disabled until a
  device exists); Command line tool.
- **Command line tool.** Install links `/usr/local/bin/fo` to
  `FamilyOffice.app/Contents/Resources/fo/bin/fo` when `/usr/local/bin` is writable;
  otherwise it shows the exact command (`sudo ln -s '<bundle>/Contents/Resources/fo/bin/fo'
  /usr/local/bin/fo`, with `sudo mkdir -p /usr/local/bin &&` when the directory is missing)
  with Copy Command and Open Terminal. The app never asks for an administrator password, and
  only replaces or removes a link that points into a Family Office bundle. The state is
  verified at launch and whenever General appears. The bundled launcher follows symlinks, so
  the linked `fo` finds its runtime. Development builds without the bundle show the tool as
  unavailable.
- **Devices.** See below.
- **Advanced.** Port (`serve.port`; a change restarts the server), Run budget
  (`serve.max_budget_usd`), Run timeout (`serve.run_timeout_minutes`), Runs kept
  (`serve.keep_runs`) and Web fetch cap (`serve.web_fetch_cap`). Each Set runs
  `fo --json --office PATH config set KEY VALUE` with the server's scrubbed environment; a
  refusal shows the CLI's `message` (for example `serve.port expects an integer from 1 to
  65535 other than 8182.`). A key the installed `fo config set` rejects with `invalid_key` is
  shown as not settable instead of being written another way; all five keys are settable
  on the current server.

## Devices and Tailscale

`FOKit.Tailscale` looks for the CLI at `/Applications/Tailscale.app/Contents/MacOS/Tailscale`,
then `/usr/local/bin/tailscale`, then `/opt/homebrew/bin/tailscale`, runs `status --json`
with a 10 second timeout, and reads only `BackendState` and `Self.DNSName` (trailing dot
removed). The pane shows one of:

- **not installed**: the download link (https://tailscale.com/download/mac) and the command to
  run after signing in, `tailscale serve --bg 4790` (the configured port);
- **installed but stopped**: what the backend state means, Open Tailscale and Check Again;
- **running**: this Mac's MagicDNS name, the office's `serve.tailnet_name`, and Use this name
  (`fo config set serve.tailnet_name NAME`).

Start Tailnet Access asks for confirmation, then runs `tailscale serve --bg PORT` (the live
port when phone access is on, else `serve.port`) and shows its output. Stop runs
`tailscale serve --https=443 off`, which removes only the HTTPS listener that command made;
`tailscale serve reset` would also clear any other serve configuration, so the app does not
use it. The serve configuration outlives the app until stopped.

Pair a Phone calls `POST /api/devices/pairing` (cookie, loopback, `Origin` set) and shows a
QR code of

```json
{"v":1,"url":"https://<tailnet_name>","code":"<code>"}
```

with the code as `ABCD-2345` and a countdown to `expires_at`. While it is on screen the pane
reloads the devices list every three seconds and hides the code when a new device appears.
The list shows name, paired date and last seen; Revoke confirms, then calls
`DELETE /api/devices/{id}`.

The launch cookie is marked `Secure` only on a landing reached through the tailnet name;
on loopback it is plain, because WebKit drops a `Secure` cookie set over `http://127.0.0.1`
and the Mac's own web view would otherwise have no session with phone access on.

The app passes `--parent-pid <its pid>` when it starts the server, so a server whose app
died without a normal quit (a crash or SIGKILL) stops itself within a few seconds.

## Restart behavior

- Closing the main window keeps the app running in the menu bar; Quit (menu bar, app menu or
  Command-Q) stops the server.

- Quitting the app sends SIGTERM to the server, waits up to five seconds, then sends SIGKILL.
- If the server exits unexpectedly, the app shows a banner and restarts it after 1, 2, 4, 8 and
  8 seconds, five attempts in all; a server that ran for 30 seconds or more resets the count.
  After five failures the banner says so and View > Restart Server tries again.
- A server that prints no handshake within 30 seconds is stopped and counts as a failure.
- Each restart rotates the token and usually the port; the web view loads the new landing URL.
- A version mismatch or a missing executable is not retried; the banner explains it.

## Manual walkthrough: menu bar, settings and devices (U11, U14)

Use a synthetic office (`uv run fo setup /tmp/fo-dev-office --offline`) and
`FO_EXECUTABLE="$PWD/.venv/bin/fo"`. For the command line tool, use a build with
`apple/Resources/fo/` bundled. Tick each item:

- [ ] The menu bar item appears at launch and lists the office folder, `Never synced`, and
      no phone line; after `fo sync` in a terminal it reads `Synced … ago` within 30 s.
- [ ] Starting an advisor run shows `Run in progress: <advisor>` until it finishes.
- [ ] Closing the window leaves the menu bar item; Open Family Office brings the window back;
      Restart Server restarts it (the log shows a new poll); Quit stops the server
      (`lsof -iTCP -sTCP:LISTEN | grep python` is empty).
- [ ] Settings… opens Settings; General, Devices and Advanced each render.
- [ ] Launch at login on: System Settings > General > Login Items lists Family Office (or the
      pane says approval is needed and its button opens Login Items); off: it is gone.
      Signing out and in with it on opens the app.
- [ ] Keep awake is disabled with no paired device. With a device paired and the toggle on,
      `pmset -g assertions` lists `PreventUserIdleSystemSleep` for FamilyOffice; turning it
      off, revoking the last device, or quitting removes it.
- [ ] Advanced > Port: `4791` saves and restarts the server (with phone access on, the
      handshake port follows); `70000` shows `serve.port expects an integer from 1 to 65535
      other than 8182.` and changes nothing. Keys the installed `fo` cannot set say so.
- [ ] Command line tool: Install creates `/usr/local/bin/fo` pointing into the app bundle, and
      `fo --version` in a new Terminal matches the app's `FOExpectedVersion`; with
      `/usr/local/bin` not writable the pane shows the `sudo ln -s …` command and Copy
      Command puts it on the clipboard; Remove deletes only that link.
- [ ] Tailscale not installed (or temporarily renamed): the pane shows the download link and
      `tailscale serve --bg 4790`. Stopped (quit the Tailscale app): "turned off" with Open
      Tailscale. Running: the MagicDNS name, and Use this name writes `serve.tailnet_name`
      (`fo config get serve.tailnet_name`).
- [ ] Allow phone access refuses without a tailnet name and restarts the server with
      `--remote` once one is set.
- [ ] Start Tailnet Access shows the confirmation sheet, then `tailscale serve status` lists the
      HTTPS listener for the port; Stop removes it and leaves other serve entries alone.
- [ ] Pair a Phone shows a QR code, the code and a countdown from 5:00; scanning the QR with
      the Camera app shows the `{"v":1,"url":"https://…","code":"…"}` text; at 0:00 it says
      expired. The iOS app (or a `curl` over the tailnet) pairing with it makes the code
      disappear and the device appear.
- [ ] Revoke asks for confirmation, removes the row, and the phone's next request gets 401.
- [ ] The unified log for the run carries no token, pairing code, device name or path.
