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
                              Power, LoginItem, CommandLineTool, FoCommand, SessionPrimer,
                              SetupVersion, Updater (Sparkle)
    MenuBar/                  the menu bar item and the 30 s status poller
    Settings/                 the Settings window: General, Engines, Connectors, Devices, Advanced
    Setup/                    the first-run setup dialog: SetupModel, SetupDialog, one view per step
    Terminal/                 FoTerminalView: the embedded terminal (SwiftTerm) for four fo commands
    Assets.xcassets           placeholder icon
    Info.plist                generated from project.yml, committed
    FamilyOffice.entitlements the bundled interpreter's entitlements (applied by sign-bundle.sh)
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
                              TerminalCommand (the terminal's allowed commands), Setup (the
                              setup dialog's steps, profile, version and Return rules), Keychain and
                              DeviceSession (the phone's credential and pairing state)
  Scripts/bundle-python.sh    builds apple/Resources/fo (the bundled runtime)
  Scripts/sign-bundle.sh      signs the runtime, the frameworks and the app, inside out
  Scripts/make-dmg.sh         builds FamilyOffice-<version>-<arch>.dmg from the signed app
  Scripts/notarize.sh         submits a zip or DMG to notarytool and waits (CI only)
  Resources/fo/               build product, git-ignored
```

Requirements: Xcode 16 or later (Swift 6), macOS 14 or later, `uv`, and
[XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`) when you change the
project.

## Dependencies

The Mac app has two third-party Swift packages; the iPhone app has none:

| Package | Version | License | Used for |
| ------- | ------- | ------- | -------- |
| [SwiftTerm](https://github.com/migueldeicaza/SwiftTerm) | 1.10.1 (exact) | MIT | the embedded terminal (`Terminal/`) |
| [Sparkle](https://github.com/sparkle-project/Sparkle) | 2.10.1 (exact) | MIT | in-app updates (`App/Updater.swift`) |

Each is declared in `project.yml` with `exactVersion`, and
`FamilyOffice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved` pins its
revision; commit both. When Sparkle moves, update `SPARKLE_VERSION` and `SPARKLE_SHA256` in
`.github/workflows/release-mac.yml` to the same release. SwiftPM also resolves SwiftTerm's own `swift-argument-parser`
dependency, which only its `termcast` tool uses and which is not linked into the app.
SwiftTerm 1.11 and later add a SwiftPM build-tool plugin that `xcodebuild` refuses to run
unless plugin validation is skipped, so stay on 1.10.x until that is acceptable for CI.

## Building

The order is generate, build and test, then bundle Python. Signing is in
[Signing and releases](#signing-and-releases).

### Generate the project

Edit `apple/project.yml`, never the `.xcodeproj`, then:

```sh
cd apple
xcodegen generate
```

Commit `project.yml`, `FamilyOffice.xcodeproj`, `FamilyOffice/Info.plist` and
`FamilyOfficePhone/Info.plist` together. CI regenerates the project and fails when the
committed files differ.

### Build and test

```sh
cd apple/FOKit && swift build && swift test
cd apple && xcodebuild -project FamilyOffice.xcodeproj -scheme FamilyOffice \
  -configuration Debug CODE_SIGNING_ALLOWED=NO build
```

Development builds are unsigned (or ad-hoc signed by Xcode). Release builds are signed by
`Scripts/sign-bundle.sh`; see [Signing and releases](#signing-and-releases).

### Bundle Python

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

## Signing and releases

Releases are built by `.github/workflows/release-mac.yml` on a `v*` tag; the steps, secrets and
checks are in [RELEASING.md](../../RELEASING.md). Only CI holds the Developer ID certificate, the
notarization key and the Sparkle private key. Locally you sign ad-hoc.

### sign-bundle.sh

```sh
apple/Scripts/sign-bundle.sh path/to/FamilyOffice.app            # ad-hoc ("-")
apple/Scripts/sign-bundle.sh path/to/FamilyOffice.app IDENTITY   # CI: Developer ID
```

It signs from the inside out, because each signature seals what is already signed inside it:

1. every Mach-O file under `Contents/Resources/fo/` (found with `file`): the shared libraries
   and extension modules first, then the `python3.12` interpreter with
   `FamilyOffice/FamilyOffice.entitlements`. The launchers `bin/fo` and `venv/bin/fo` are shell
   scripts, sealed as resources by the app's signature;
2. each framework in `Contents/Frameworks/` (Sparkle; SwiftTerm is linked statically): its
   XPC services, `Updater.app` and `Autoupdate`, deepest first with their own entitlements
   preserved, then the framework;
3. the app, without entitlements;

and ends with `codesign --verify --deep --strict`. With a real identity every signature gets
`--options runtime --timestamp`, as notarization requires. Ad-hoc runs leave the hardened
runtime off: an ad-hoc signature has no Team ID, so under the hardened runtime library
validation rejects `Sparkle.framework` and the app cannot launch. `FO_SIGN_RUNTIME=1` turns the
runtime on for an ad-hoc run anyway (the bundled `fo` then runs, the app does not);
`FO_SIGN_ENTITLEMENTS=path` swaps the interpreter entitlements.

The release workflow archives with `CODE_SIGNING_ALLOWED=NO` and lets this script do all of the
signing, so there is one signing path for every Mach-O in the bundle.

### Entitlements the bundled Python needs

Tested on 2026-11-05 (arm64, python-build-standalone 3.12.16) by ad-hoc signing a Release build
with `FO_SIGN_RUNTIME=1` and each entitlement set, then running the bundled `fo --version`,
`fo serve --help`, and an import of `fo.cli` plus a `ctypes` callback:

| Interpreter entitlements | Result |
| ------------------------ | ------ |
| none | fails: importing `rpds` (an extension module) is refused, "mapping process and mapped file (non-platform) have different Team IDs" |
| `allow-unsigned-executable-memory` only | fails the same way |
| `disable-library-validation` only | passes |
| both | passes |

So the entitlements file holds only `com.apple.security.cs.disable-library-validation`, and
only the interpreter carries it. `allow-unsigned-executable-memory` is not needed: `ctypes`
callbacks work without it. The failure without library validation disabled comes from ad-hoc
signatures having no Team ID; with the Developer ID every file shares the Team ID and the
interpreter may load its modules without the entitlement. To confirm that on a test tag, point
`FO_SIGN_ENTITLEMENTS` at an empty entitlements plist in the Sign step: the workflow's "Bundled
fo runs after signing" step fails if the interpreter cannot load its modules. Drop the key only
after that passes.

### Local ad-hoc verification

```sh
apple/Scripts/bundle-python.sh                      # if apple/Resources/fo is absent
cd apple && xcodegen generate
xcodebuild -project FamilyOffice.xcodeproj -scheme FamilyOffice -configuration Release \
  CODE_SIGNING_ALLOWED=NO -derivedDataPath /tmp/fo-dd build
scratch="$(mktemp -d)"
ditto /tmp/fo-dd/Build/Products/Release/FamilyOffice.app "$scratch/FamilyOffice.app"
Scripts/sign-bundle.sh "$scratch/FamilyOffice.app" -
codesign --verify --deep --strict --verbose=2 "$scratch/FamilyOffice.app"
"$scratch/FamilyOffice.app/Contents/Resources/fo/bin/fo" --version
Scripts/make-dmg.sh "$scratch/FamilyOffice.app" - "$scratch"   # prints the DMG path
hdiutil attach -nobrowse -readonly "$scratch"/FamilyOffice-*.dmg  # then detach it
rm -rf "$scratch" /tmp/fo-dd
```

`spctl --assess` rejects an ad-hoc signed app ("source=no usable signature"); that is expected.
Gatekeeper acceptance can only be checked on a notarized build:

```sh
spctl -a -vv FamilyOffice.app            # accepted, source=Notarized Developer ID
spctl -a -vv -t open --context context:primary-signature FamilyOffice-<version>-<arch>.dmg
xcrun stapler validate FamilyOffice-<version>-<arch>.dmg
```

### Updates (Sparkle)

`App/Updater.swift` owns an `SPUStandardUpdaterController`. `Info.plist` sets `SUFeedURL` to
`appcast.xml` on the latest GitHub Release and `SUEnableAutomaticChecks` to true; Intel builds
read `appcast-x86_64.xml` beside it (each architecture has its own DMG and appcast).
`SUPublicEDKey` is a placeholder until the release key pair exists (RELEASING.md, one-time
setup); while it is, the updater is not started and the menu item and the Settings controls
are disabled, so development builds never show Sparkle's "failed to start" alert.

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
through; `PYTHONUNBUFFERED=1` is added, and `FO_CLAUDE_EXECUTABLE` and `FO_CODEX_EXECUTABLE`
name the CLIs the app found (see Engines). Port 0 lets the system choose a free loopback port.
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
| `officePath`           | the office folder (setup dialog, File > Choose Office Folder… or General > Change…) |
| `setupVersion`         | the setup dialog version last finished (an integer, currently `1`)     |
| `keepAwakeWhilePaired` | General > Keep Mac awake while a phone is paired                       |
| `allowPhoneAccess`     | General > Allow phone access over Tailscale (`fo serve --remote`)      |
| `settingsTab`          | the Settings tab shown last (`general`, `engines`, `connectors`, `devices`, `advanced`) |
| `foExecutablePath`     | development only: a `fo` to run when no bundle is present              |
| `SU*` (Sparkle)        | Sparkle's own keys, such as `SUEnableAutomaticChecks` (General > Updates) and `SULastCheckTime`; written only once the updater is configured |

Launch at login is not a default: macOS keeps it (`SMAppService.mainApp`), and the toggle
reads its status every time General appears. Every `office.toml` setting (port, run caps,
retention, web fetch cap, tailnet name) is written by `fo config set` and read by
`fo config get`; the app never edits the file. Outside the office the app writes only the
optional `/usr/local/bin/fo` link and, in configured release builds, Sparkle's update
cache under `~/Library/Caches/com.familyoffice.app/org.sparkle-project.Sparkle/`. Nothing else: no tokens, cookies, pairing codes, logs or
office data. Pairing codes exist only in memory and on screen.

Any default can be set for one launch on the command line without writing it, for example
`-allowPhoneAccess YES -keepAwakeWhilePaired YES -settingsTab devices`. Debug builds also
accept `-openSettingsOnLaunch YES`, which opens Settings without clicking, and two
walkthrough hooks: `-terminalCommand "WORDS"` opens the embedded terminal with those words
(anything outside the allowed set is refused), and, with `-settingsTab connectors`,
`-debugSaveSyntheticKey PROVIDER` saves the made-up key `synthetic-walkthrough-key-0000`
through the Save path once the server is up. Neither exists in Release builds. The setup
dialog has four more Debug-only hooks, described under Setup dialog: `-debugSetupWalk`,
`-debugIgnoreSetupVersion`, `-debugSetupVersion` and `-debugNewSteps`.

The app logs state changes to the unified log under subsystem `com.familyoffice.app`
(categories `monitor`, `power`, `settings`, `setup`, `terminal`, `updates`): kinds and counts only, never names,
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
  device exists); Command line tool; Updates.
- **Updates.** "Check for updates automatically" is Sparkle's
  `automaticallyChecksForUpdates` (stored by Sparkle in the app's user defaults; on by
  default through `SUEnableAutomaticChecks`, so Sparkle never asks), with the last check time
  and Check Now. Family Office > Check for Updates… in the app menu does the same as Check
  Now. Both are disabled while `SUPublicEDKey` is the placeholder (development builds and
  any build before the release key exists); see Signing and releases.
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

The server's scrubbed PATH (the runtime's `bin`, `/usr/bin`, `/bin`) would miss an nvm,
Homebrew or `~/.local/bin` install, so the app names what it found in the server's
environment: `FO_CLAUDE_EXECUTABLE` and `FO_CODEX_EXECUTABLE` (`FOKit.EngineExecutables`),
set from the same resolver before the first server start and again whenever the Engines
pane detects (on appear and Check Again). An engine not found sets nothing, and the server
falls back to its own PATH. When the found paths change, the app restarts a running server
so the next advisor run uses them. The server honors `FO_CLAUDE_EXECUTABLE` when the path is
executable; `FO_CODEX_EXECUTABLE` is passed the same way for the Codex runner.

## Connectors

| Provider | Kind | Connect | Remove | State from |
| -------- | ---- | ------- | ------ | ---------- |
| Schwab, SimpleFIN | account | Connect… opens the terminal with `fo auth schwab` or `fo auth simplefin` | (not in the app) | `/api/onboarding` `providers[].connected`, else a masked entry in `/api/config` `secrets` |
| Alpha Vantage, FRED, Exa, Firecrawl, Gemini | API key | Save runs `fo --json --office PATH connect <provider>` with the key on stdin | Remove… runs `fo connect --remove <provider>` after confirmation | the last Save or Remove in this session, else a masked `/api/config` `secrets` entry |
| SEC EDGAR | contact | Save runs `fo connect edgar --user-agent "Name email"` | Remove runs `fo connect --remove edgar` | `/api/config` `settings.providers.edgar.user_agent` |

The key never appears in an argument list: `FOKit.Subprocess` writes it to stdin and closes
it, the field is emptied the moment Save is pressed, and the row shows only the CLI's
public result (`Saved. … accepted the key.` or, for example, `The provider rejected the API
key.`). A field that is empty, contains spaces or is longer than 512 characters is refused
in the app without running `fo`. The app never reads the per-machine credentials
folder outside the office.

`fo connect` writes keys to `<provider>.json` in that credentials folder, and
`GET /api/config` lists each such file in `secrets` as
`{"<provider>": {"api_key": "***"}}` beside the masked `keys.toml` entries,
so a key saved in an earlier session shows Connected after a restart, and a provider the route does not list shows Not connected. "Not reported by the
server" appears only while the route cannot be read. Alpha Vantage answers
an unknown key with ordinary data, so its Save can succeed for a made-up key; FRED, Exa,
Firecrawl and Gemini reject one.

## Setup dialog

The first-run dialog (plan R7 to R11, flow F1) is a 720 by 520 point sheet on the main
window with a progress bar and "Step N of M", the current step, and a footer with Finish
Later, Back, Skip (Later on the engine step) and a primary button whose label follows the
step. `FOKit.SetupFlow` holds the logic, so it is unit tested; `Setup/SetupModel.swift`
wraps it with the step actions, and each step is its own view in `Setup/`.

| Step | Shows | Primary | Skip |
| ---- | ----- | ------- | ---- |
| welcome | what the app is in two sentences | Get Started | no |
| office | Create (a parent folder from `NSOpenPanel` and a name, default `family-office`, then `fo setup PATH --offline` in the embedded terminal) or Open existing (a folder holding `office.toml`) | Continue, once the server reports the office | no |
| engine | the Engines pane (detection, the server's verdict, default engine, model, effort) | Continue | Later |
| accounts | the Connectors pane's Schwab and SimpleFIN rows (`fo auth` in the terminal), a CSV note, and Run First Sync (`fo sync` in the terminal) once one is connected | Continue | yes |
| research | the Connectors pane's five key rows | Continue | yes |
| phone | the Devices pane: Tailscale status and pairing | Continue | yes |
| done | what was set up and what was skipped, with where to finish each | Open Family Office | no |

- **Profile.** `new` when no office path is stored or the stored folder has no
  `office.toml`; otherwise `existing`. A new profile shows all seven steps. An existing one
  starts at the engine step, never shows welcome or office, and uses copy for an office
  that is already set up.
- **Office step.** After `fo setup` exits 0, or a folder with `office.toml` is chosen, the
  app stores `officePath` and restarts the server on it (`AppState.setOffice`); Continue is
  enabled once `GET /api/onboarding` reports an office (any state other than `no_office`
  and `uninitialized_path`). A folder that already exists and is not empty is refused
  before `fo` runs; `fo setup` refuses anything else it would refuse in a terminal.
- **Choices.** Continue records one line for the done step's summary (`Office created at
  …`, `Default engine: Codex`, `Connected Schwab, first sync finished`, `2 research keys`,
  `1 phone paired`); Continue with nothing done counts as skipped. Back keeps what a step
  finished.
- **Return.** A local key monitor gives Return (and keypad Enter) to the primary button
  unless the window's first responder is a text field's editor or the embedded terminal,
  where Return is input, or the primary button is disabled. Return in another window, such
  as a terminal sheet over the dialog, is left alone. Escape does nothing, so it can reach
  the terminal.
- **When it opens.** At launch when `setupVersion` is missing, when it is older than
  `SetupFlow.currentVersion` and some step is newer than it, or when the profile is new (the
  office is gone); and always from Help > Set Up Family Office…, which brings the main
  window forward. Finish Later closes it without storing anything, so it opens again at the
  next launch. Open Family Office on the done step stores `setupVersion` and reloads the
  page.
- **Versioning.** Every step has a `newSince` version (all `1` today). A release that adds a
  step raises `SetupFlow.currentVersion` and gives the new step that `newSince`; an install
  that finished the older version then sees only the newer steps and done, with everything
  it set up before untouched.
- **Nothing bypasses `fo`.** The office is created by `fo setup`, engine defaults are written
  by `fo config set`, accounts by `fo auth`, keys by `fo connect`, the first sync by
  `fo sync`, and pairing through the server's routes, each through the same model the
  Settings pane uses. The only file the app itself looks at is whether `office.toml`
  exists, to choose the profile and to accept Open existing.
- **Log.** Category `setup`: the profile, the step list, each step change with whether the
  previous one was completed or skipped, `fo setup`'s exit status, the server's onboarding
  state, and the version stored. No paths or names.

Debug-only hooks for walkthroughs:

| Argument | Effect |
| -------- | ------ |
| `-debugIgnoreSetupVersion YES` | act as though `setupVersion` were missing |
| `-debugSetupVersion N` | pretend this build ships setup version `N` |
| `-debugNewSteps research,phone` | mark those steps new in the pretended version |
| `-debugSetupWalk PARENT` | drive the dialog without clicking: Get Started, create `PARENT/family-office` with `fo setup --offline`, Continue once the server reports it, skip the optional steps, and finish |

To walk the dialog without touching your own app's defaults, build a copy with its own
defaults domain and delete it afterwards:

```sh
cd apple
xcodebuild -project FamilyOffice.xcodeproj -scheme FamilyOffice -configuration Debug \
  CODE_SIGNING_ALLOWED=NO -derivedDataPath /tmp/fo-dd \
  PRODUCT_BUNDLE_IDENTIFIER=com.familyoffice.app.walkthrough build
FO_EXECUTABLE="$PWD/../.venv/bin/fo" \
  /tmp/fo-dd/Build/Products/Debug/FamilyOffice.app/Contents/MacOS/FamilyOffice
# afterwards
defaults delete com.familyoffice.app.walkthrough; rm -rf /tmp/fo-dd
```

### Home checklist

`GET /api/onboarding` carries `checklist`, empty until an office exists, then four items
`{id, done, label}` re-derived from the office on every poll:

| id | Done when |
| -- | --------- |
| `account_connected` | a live provider is connected or the account registry lists any account |
| `first_sync` | `data/sync_log.jsonl` has a complete sync |
| `first_run` | `cache/serve/runs/` holds a run record |
| `device_paired` | the credentials folder's `devices.json` lists at least one device |

Home shows a "Getting started" card with the open items and how to finish each, hidden once
every item is done. Dismiss hides it for good in that browser (`fo.checklist.dismissed.v1`
in `localStorage`); the Mac app's web view uses a non-persistent store, so there it returns
at the next launch until the items are done.

## Embedded terminal

`Terminal/FoTerminalView.swift` hosts SwiftTerm's `LocalProcessTerminalView`. It runs exactly
one of these, as typed in `FOKit.TerminalCommand`:

| Command | Arguments after `fo` |
| ------- | -------------------- |
| setup | `--office PATH setup PATH [--provider schwab\|simplefin]` or `--office PATH setup PATH --offline` (the setup dialog) |
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
      is empty, and the credentials folder's `fred.json` exists at 0600. Remove… asks, then deletes it.
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

## Manual walkthrough: setup dialog and Home checklist (U15)

Use the walkthrough build above (its own defaults domain), `FO_EXECUTABLE` pointing at the
checkout's `.venv/bin/fo`, and a scratch folder outside the repository. Tick each item:

- [ ] First launch from a cleared defaults domain opens the dialog on Welcome at Step 1 of
      7; Return presses Get Started.
- [ ] Office > Create: Choose… picks the scratch folder, the name defaults to
      `family-office`, Create Office runs `fo setup --offline` in the terminal, which ends
      with `Finished successfully`; the server restarts, Continue becomes available, and
      `defaults read com.familyoffice.app.walkthrough officePath` names the new folder.
      Return while the name field has focus does not advance.
- [ ] Office > Open existing refuses a folder without `office.toml` and accepts an office.
- [ ] Engine shows the Engines pane; Later moves on.
- [ ] Accounts: skip it. Research and Phone: skip them. Done lists the office under Set up
      and Accounts, Research keys and Phone under Skipped for now; Open Family Office
      closes the dialog and `setupVersion` reads `1`.
- [ ] Home shows Getting started with Connect an account, Run the first sync, Talk to an
      advisor and Pair a phone; Dismiss hides it (in a browser, it stays hidden after a
      reload).
- [ ] Relaunching does not open the dialog (the `setup` log says the version is finished).
- [ ] Help > Set Up Family Office… opens it on the engine step with the existing copy.
- [ ] Bump the version in a Debug build: `-debugSetupVersion 2 -debugNewSteps research`
      opens the dialog with only Research and Done (`steps=research,done` in the log).
- [ ] Deleting `office.toml` from the scratch office (or choosing an empty folder in General)
      makes the next launch open the dialog on Welcome again.
- [ ] The `setup` and `terminal` log categories carry no path, name, key or token.
- [ ] Delete the scratch office and the walkthrough defaults domain.

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
flag out, as above).

### TestFlight builds

`.github/workflows/release-ios.yml` runs on `v*` tags and by hand on a `macos-latest` runner:
`xcodegen generate`, then `xcodebuild archive` of the `FamilyOfficePhone` scheme, an export
with `method: app-store-connect`, and `xcrun altool --upload-app` with an App Store Connect API
key. `altool` is used rather than an upload action so the key never reaches third-party code.
It needs six secrets: `IOS_CERT_P12`, `IOS_CERT_PASSWORD`, `IOS_PROVISIONING_PROFILE`,
`ASC_KEY_ID`, `ASC_ISSUER_ID` and `ASC_KEY_P8` (the three files base64-encoded). When any is
missing, every signing and upload step is skipped with a notice naming the missing secrets, and
the job only builds the app for the simulator. The build number is the workflow run number.

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
