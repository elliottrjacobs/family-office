# Mac and iPhone app development

The Mac app lives under `apple/`. It is a SwiftUI shell that starts `fo serve` as a child
process and shows the dashboard in a `WKWebView`; all office logic stays in the Python package.
The iPhone app (see [iPhone app](#iphone-app)) pairs with it and shows the same dashboard over
the tailnet.

```text
apple/
  project.yml                 XcodeGen spec (source of truth for the Xcode project)
  FamilyOffice.xcodeproj      generated from project.yml, committed
  FamilyOffice/
    App/                      @main app, AppState, ServerProcess, WebView, ContentView,
                              Power, LoginItem, CommandLineTool, FoCommand, SessionPrimer
    MenuBar/                  the menu bar item and the 30 s status poller
    Settings/                 the Settings window: General, Engines, Connectors, Devices, Advanced
    Terminal/                 FoTerminalView: the embedded terminal (SwiftTerm) for four fo commands
    Assets.xcassets           placeholder icon
    Info.plist                generated from project.yml, committed
  FamilyOfficePhone/
    App/                      @main app, RootView, OfficeScreen, PhoneModel
    Pairing/                  PairingView, PairingInput (scanned or typed text to a payload)
    Scanner/                  QRScannerView (DataScannerViewController, AVCaptureSession fallback)
    Connection/               ConnectionView
    Web/                      OfficeWebView
    Assets.xcassets           placeholder icon
    Info.plist                generated from project.yml, committed
  FamilyOfficePhoneTests/     unit tests hosted in the iPhone app
  FOKit/                      Swift package shared with the iOS app: Handshake, APIClient, Reachability,
                              OfficeSummary, Tailscale, Pairing (payload and QR), Subprocess (macOS),
                              Engines (CLI resolver, version and sign-in parsers), Connectors,
                              TerminalCommand (the terminal's allowed commands), Keychain and
                              DeviceSession (the phone's credential and pairing state)
  Scripts/bundle-python.sh    builds apple/Resources/fo (the bundled runtime)
  Resources/fo/               build product, git-ignored
```

Requirements: Xcode 16 or later (Swift 6), macOS 14 or later, `uv`, and
[XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`) when you change the
project.

## Dependencies

The Mac app has one third-party Swift package; the iPhone app has none:

| Package | Version | License | Used for |
| ------- | ------- | ------- | -------- |
| [SwiftTerm](https://github.com/migueldeicaza/SwiftTerm) | 1.10.1 (exact) | MIT | the embedded terminal (`Terminal/`) |

It is declared in `project.yml` with `exactVersion`, and
`FamilyOffice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved` pins its
revision; commit both. SwiftPM also resolves SwiftTerm's own `swift-argument-parser`
dependency, which only its `termcast` tool uses and which is not linked into the app.
SwiftTerm 1.11 and later add a SwiftPM build-tool plugin that `xcodebuild` refuses to run
unless plugin validation is skipped, so stay on 1.10.x until that is acceptable for CI.

## Generate the project

Edit `apple/project.yml`, never the `.xcodeproj`, then:

```sh
cd apple
xcodegen generate
```

Commit `project.yml`, `FamilyOffice.xcodeproj`, `FamilyOffice/Info.plist` and
`FamilyOfficePhone/Info.plist` together. CI regenerates the project and fails when the
committed files differ.

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
fo [--office PATH] serve --port 0 --app --parent-pid APP_PID
fo [--office PATH] serve --remote --app --parent-pid APP_PID   # with phone access on
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
for the flag and omits it when absent; it does the same for `--parent-pid`. A first stdout line that is not JSON then counts as no
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
| `settingsTab`          | the Settings tab shown last (`general`, `engines`, `connectors`, `devices`, `advanced`) |
| `foExecutablePath`     | development only: a `fo` to run when no bundle is present              |

Launch at login is not a default: macOS keeps it (`SMAppService.mainApp`), and the toggle
reads its status every time General appears. Every `office.toml` setting (port, run caps,
retention, web fetch cap, tailnet name) is written by `fo config set` and read by
`fo config get`; the app never edits the file. Outside the office the app writes only the
optional `/usr/local/bin/fo` link. Nothing else: no tokens, cookies, pairing codes, logs or
office data. Pairing codes exist only in memory and on screen.

Any default can be set for one launch on the command line without writing it, for example
`-allowPhoneAccess YES -keepAwakeWhilePaired YES -settingsTab devices`. Debug builds also
accept `-openSettingsOnLaunch YES`, which opens Settings without clicking, and two
walkthrough hooks: `-terminalCommand "WORDS"` opens the embedded terminal with those words
(anything outside the allowed set is refused), and, with `-settingsTab connectors`,
`-debugSaveSyntheticKey PROVIDER` saves the made-up key `synthetic-walkthrough-key-0000`
through the Save path once the server is up. Neither exists in Release builds.

The app logs state changes to the unified log under subsystem `com.familyoffice.app`
(categories `monitor`, `power`, `settings`, `terminal`): kinds and counts only, never names,
paths, codes, keys or tokens. Read them with:

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
- **Engines** and **Connectors.** See below.
- **Devices.** See below.
- **Advanced.** Port (`serve.port`; a change restarts the server), Run budget
  (`serve.max_budget_usd`), Run timeout (`serve.run_timeout_minutes`), Runs kept
  (`serve.keep_runs`) and Web fetch cap (`serve.web_fetch_cap`). Each Set runs
  `fo --json --office PATH config set KEY VALUE` with the server's scrubbed environment; a
  refusal shows the CLI's `message` (for example `serve.port expects an integer from 1 to
  65535 other than 8182.`). A key the installed `fo config set` rejects with `invalid_key` is
  shown as not settable instead of being written another way; all five keys are settable
  on the current server.

## Engines

`FOKit.CLIResolver` looks for `claude` and `codex`, in order, at:

1. `command -v <cli>` in the user's login shell (`/bin/zsh -lc`, 5 second timeout; only an
   absolute path counts, so aliases and profile chatter are ignored);
2. `~/.nvm/versions/node/*/bin/<cli>`, newest Node version first;
3. `/opt/homebrew/bin/<cli>`, `/usr/local/bin/<cli>`, `~/.local/bin/<cli>`;
4. for Claude Code, `~/.claude/local/claude`.

The first executable file wins (a symlink to one already found is skipped). `EngineDetector`
then runs `<cli> --version` (10 second timeout) with the CLI's own directory first on PATH,
so an nvm or Homebrew install finds its `node`, and the account variables the server passes
through (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`).
The sign-in check is `claude auth status` (JSON `loggedIn`) when `claude --help` lists the
`auth` command, otherwise "unknown", and `codex login status` for Codex. Only signed in or
not is kept; account names and emails in the output are never shown, stored or logged.

Each engine shows the path found and how, the version, the sign-in state, and the server's
own verdict from `GET /api/runner` (`usable`, or its `message`). A missing engine shows the
official install commands with Copy buttons (Claude Code: the `claude.ai/install.sh`
script, `brew install --cask claude-code` or `npm install -g @anthropic-ai/claude-code`;
Codex: `npm install -g @openai/codex` or `brew install --cask codex`), the install guide,
and that runs bill through the user's own Claude or ChatGPT/OpenAI account. A signed-out
engine shows its sign-in command. The app never installs or signs in an engine.

Defaults come from `GET /api/models` (the curated list and the office's values) and are
written with `fo config set`: Default engine (segmented, `serve.engines.default`), Model (a
picker of the curated models plus Other… for any id, `serve.engines.<name>.model`), Effort
(low, medium, high, `serve.engines.<name>.effort`), Budget per run
(`serve.engines.<name>.max_budget_usd`) and Enabled (`serve.engines.<name>.enabled`). A
refusal shows the CLI's message under the field, and `/api/runner` is read again after
every write.

The server resolves `claude` and `codex` from its own PATH (`shutil.which`); it has no
executable override such as `FO_CLAUDE_EXECUTABLE`, so the app passes none. With the app's
scrubbed PATH (the runtime's `bin`, `/usr/bin`, `/bin`) an nvm, Homebrew or `~/.local/bin`
install is therefore found by the pane but reported `runner_missing` by the server. The
pane shows both side by side and does no more.

## Connectors

| Provider | Kind | Connect | Remove | State from |
| -------- | ---- | ------- | ------ | ---------- |
| Schwab, SimpleFIN | account | Connect… opens the terminal with `fo auth schwab` or `fo auth simplefin` | (not in the app) | `/api/onboarding` `providers[].connected`, else a masked entry in `/api/config` `secrets` |
| Alpha Vantage, FRED, Exa, Firecrawl, Gemini | API key | Save runs `fo --json --office PATH connect <provider>` with the key on stdin | Remove… runs `fo connect --remove <provider>` after confirmation | a masked `/api/config` `secrets` entry (a key `fo auth` stored), else the last Save or Remove in this session |
| SEC EDGAR | contact | Save runs `fo connect edgar --user-agent "Name email"` | Remove runs `fo connect --remove edgar` | `/api/config` `settings.providers.edgar.user_agent` |

The key never appears in an argument list: `FOKit.Subprocess` writes it to stdin and closes
it, the field is emptied the moment Save is pressed, and the row shows only the CLI's
public result (`Saved. … accepted the key.` or, for example, `The provider rejected the API
key.`). A field that is empty, contains spaces or is longer than 512 characters is refused
in the app without running `fo`. The app never reads `secrets/`.

`fo connect` writes keys to `secrets/<provider>.json`, and no server route reports those
files yet (`/api/config` masks only `secrets/keys.toml`), so a key saved in an earlier
session shows "Not reported by the server" until it is saved again. Alpha Vantage answers
an unknown key with ordinary data, so its Save can succeed for a made-up key; FRED, Exa,
Firecrawl and Gemini reject one.

## Embedded terminal

`Terminal/FoTerminalView.swift` hosts SwiftTerm's `LocalProcessTerminalView`. It runs exactly
one of these, as typed in `FOKit.TerminalCommand`:

| Command | Arguments after `fo` |
| ------- | -------------------- |
| setup | `--office PATH setup PATH [--provider schwab\|simplefin]` |
| auth | `--office PATH auth schwab` or `--office PATH auth simplefin` |
| sync | `--office PATH sync` |
| doctor | `--office PATH doctor` |

Anything else (another subcommand, another provider, extra flags, a shell) is refused in
code before a process exists, and the sheet says so. The executable is the bundled or
configured `fo` (`ServerProcess.resolveExecutable`), started directly by `forkpty` and
`execve` with the server's scrubbed environment plus `TERM=xterm-256color`, the home folder
as working directory, and no shell. Keystrokes reach the process only while it runs, so the
CLI's hidden prompts and the Schwab consent flow work unchanged; when it exits the view is
read-only and shows the exit status. Closing the sheet stops the command. Output exists only
in the terminal's scrollback in memory; it is never logged or written to disk (the unified
log records only `started <subcommand>` and the exit status).

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

The app passes `--parent-pid <its pid>` when it starts the server (when `fo serve --help`
lists the flag), so a server whose app died without a normal quit (a crash or SIGKILL)
stops itself within a few seconds.

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

## Manual walkthrough: engines, connectors and the terminal (U13)

Use a synthetic office (`uv run fo setup /tmp/fo-dev-office --offline`),
`FO_EXECUTABLE="$PWD/.venv/bin/fo"` and `-openSettingsOnLaunch YES -settingsTab engines`
(or `connectors`). Use made-up keys only. Tick each item:

- [ ] Engines with one CLI missing (rename it or test on a Mac without it): the installed
      engine shows its path, `via nvm` (or Homebrew, login shell, …), its version and
      sign-in state; the missing one shows Not installed, the install commands with Copy
      buttons, the billing note and the guide link. Check Again picks up an install.
- [ ] The Server line matches `fo serve`'s `/api/runner`: Usable with a version, or Not
      usable with the server's message (for example `runner_missing` when the CLI is only
      on an nvm or Homebrew PATH the server does not see).
- [ ] Default engine, Model (a listed model and Other… with a custom id), Effort, Budget per
      run and Enabled each save; `fo config get serve.engines.claude.model` (and the other
      keys) shows the value, and `0` as a budget shows `… expects a number greater than 0.`
      and changes nothing. Turning an engine off makes its Server line say it is turned off.
- [ ] Connectors: saving a made-up FRED key shows `The provider rejected the API key.` and
      writes nothing; saving a real key shows `Saved.`, the row turns Connected, the field
      is empty, and `secrets/fred.json` exists at 0600. Remove… asks, then deletes it.
- [ ] EDGAR: a name and email save (`fo config get providers.edgar.user_agent`), a name
      without an email cannot be saved, and Remove clears it.
- [ ] Connect… on Schwab opens the terminal running `fo auth schwab`: the app key and
      secret prompts hide what is typed, then the default browser opens Schwab's consent
      page; after approval the command ends, the status line shows the exit status, the
      terminal no longer takes input, and the row reads Connected.
- [ ] Connect… on SimpleFIN hides the setup token as it is typed.
- [ ] The terminal refuses other commands: `-terminalCommand bash`,
      `-terminalCommand "auth fred"` and `-terminalCommand "sync --office /elsewhere"` show
      the refusal and start no process (`ps -ax | grep '[f]o --office'` shows none);
      `-terminalCommand doctor` runs and ends with `Finished successfully`.
- [ ] Closing the terminal sheet while a command waits for input stops it (no `fo auth`
      process remains), and quitting the app leaves no `fo serve` either.
- [ ] The unified log (categories `settings` and `terminal`) and `ps` output never contain
      a key, token, account name, email or path.

## iPhone app

`FamilyOfficePhone` is a SwiftUI app for iPhone, iOS 17 or later, bundle id
`com.familyoffice.phone`. It depends only on FOKit, has no entitlements, and asks for the
camera only to scan the pairing code. It holds no office data: everything it shows is the
Mac's own web app, loaded over the tailnet.

### Build and run on a simulator

```sh
cd apple
xcodebuild -project FamilyOffice.xcodeproj -scheme FamilyOfficePhone \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/fo-dd-ios build test
xcrun simctl boot 'iPhone 17 Pro'      # if it is not booted yet
xcrun simctl install booted /tmp/fo-dd-ios/Build/Products/Debug-iphonesimulator/FamilyOfficePhone.app
xcrun simctl launch booted com.familyoffice.phone
```

CI builds with `CODE_SIGNING_ALLOWED=NO`, which is enough to compile and run the tests. An
unsigned app cannot use the Keychain, though, and opens on pairing with "The Keychain could
not be read"; to try it by hand keep Xcode's ad-hoc "Sign to Run Locally" signing (leave the
flag out, as above). TestFlight builds come with the release unit (U17).

### Screens

- **Unpaired:** "Pair with your Mac" lists the steps on the Mac (open Family Office, Settings >
  Devices, Pair a Phone), a name for the phone (the device name by default), Scan Code and
  Enter Code Manually. Scan Code uses VisionKit's `DataScannerViewController`, falls back to an
  `AVCaptureSession` QR reader, and offers manual entry when there is no camera or no camera
  permission. A refusal or a revoke shows its reason above the steps.
- **Paired and reachable:** the office web app fills the screen under a one-line status bar
  (the Mac's name, Connected, Reload, and a button for the connection screen); pull down to
  reload. Links to other sites open in Safari.
- **Paired and not reachable:** the connection screen shows the Mac's name and tailnet host,
  Reachable or Not reachable, when it last answered, the server's version, the sentence "Your
  Mac must be awake and on your tailnet, with Family Office open.", Retry, and Unpair This
  iPhone (after confirmation it forgets the token on the phone only; revoke it on the Mac to
  remove it there). When the server is newer than this build knows (`DeviceSession`
  `knownServerVersions`, now 2.0.x) a note advises updating the app.

While the app is in front it probes `GET /api/status` every ten seconds, each probe giving up
after five seconds; any HTTP answer counts as reachable. It moves to the web view when the Mac
comes back and to the connection screen when it goes away.

### Pairing without a camera

The simulator has no camera, so Scan Code offers Enter Code Manually: type the address and the
code the Mac shows under Pair a Phone. The address is the Mac's tailnet name
(`example-mac.tail0000.ts.net`; `https://` is assumed). Plain `http://` is accepted only for
`localhost` and `127.0.0.1`, which a simulator shares with the Mac. The code may be typed in
either case, with or without its hyphen.

To walk the flow on one Mac without a tailnet, use a synthetic office whose tailnet name is
`localhost` and put a small proxy of your own in front of the server that does what
`tailscale serve` would:

```sh
uv run fo setup /tmp/fo-phone-office --offline
uv run fo --office /tmp/fo-phone-office config set serve.tailnet_name localhost
uv run fo --office /tmp/fo-phone-office serve --remote --port 4799 --app
```

The proxy listens on another port (say 4800), forwards to 4799 with `Host: localhost` and
`Tailscale-User-Login: tester@example.com`, and, because it is plain HTTP rather than HTTPS,
drops `Secure` from `Set-Cookie` and sends `Origin: https://localhost`. Get a code over
loopback with the launch cookie (the landing URL from the handshake line, then
`POST /api/devices/pairing` with `Origin: http://127.0.0.1:4799`), and enter
`http://localhost:4800` and the code on the phone. Pointing the phone at 4799 directly shows
the refusal for a request that did not come over the tailnet. Revoke with
`DELETE /api/devices/{id}` the same way. Delete the office afterwards.

### What the phone keeps

- **Keychain:** one generic password item, service `com.familyoffice.phone`, account `device`,
  `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` (never in a backup restored to another
  device). It holds the server URL, the device id and name, and the device token shown once in
  the pairing response.
- **UserDefaults:** `lastSeen`, when the Mac last answered.
- **Nothing else.** The web view's store is non-persistent: the session cookie from
  `POST /api/devices/login` is copied into it on each launch and dies with the app. Codes and
  tokens are never logged or shown after pairing.

### When the Mac says 401

The token is sent only to `POST /api/devices/login`, as `Authorization: Bearer`; every other
request uses the session cookie. A 401 from that login, from a page the web view loads, or
from a status probe made with the session cookie means the Mac no longer knows this phone
(usually a revoke in Settings > Devices). The phone deletes the Keychain item and opens
pairing with "This iPhone is no longer paired with the Mac." Pairing again with a new code
works at once. A Mac that does not answer is not a 401: the phone stays paired and shows the
connection screen. A 403 `forbidden_login` while pairing means the request arrived without a
Tailscale identity the office allows, and the phone says so.
