# Mac app development

The Mac app lives under `apple/`. It is a SwiftUI shell that starts `fo serve` as a child
process and shows the dashboard in a `WKWebView`; all office logic stays in the Python package.

```text
apple/
  project.yml                 XcodeGen spec (source of truth for the Xcode project)
  FamilyOffice.xcodeproj      generated from project.yml, committed
  FamilyOffice/
    App/                      @main app, AppState, ServerProcess, WebView, ContentView
    Assets.xcassets           placeholder icon
    Info.plist                generated from project.yml, committed
  FOKit/                      Swift package shared with the iOS app: Handshake, APIClient, Reachability
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
```

with stdin closed, the working directory set to the home folder, and a scrubbed environment:
`PATH` is the runtime's `bin` plus `/usr/bin:/bin`; `HOME`, `USER`, `LANG`, `TMPDIR` and, when
set, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CONFIG_DIR` and `CODEX_HOME` pass
through; `PYTHONUNBUFFERED=1` is added. Port 0 lets the system choose a free loopback port.

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

| Key                | Value                                                     |
| ------------------ | --------------------------------------------------------- |
| `officePath`       | the office folder chosen in the first-launch sheet        |
| `foExecutablePath` | development only: a `fo` to run when no bundle is present |

Nothing else: no tokens, cookies, logs or office data.

## Restart behavior

- Quitting the app sends SIGTERM to the server, waits up to five seconds, then sends SIGKILL.
- If the server exits unexpectedly, the app shows a banner and restarts it after 1, 2, 4, 8 and
  8 seconds, five attempts in all; a server that ran for 30 seconds or more resets the count.
  After five failures the banner says so and View > Restart Server tries again.
- A server that prints no handshake within 30 seconds is stopped and counts as a failure.
- Each restart rotates the token and usually the port; the web view loads the new landing URL.
- A version mismatch or a missing executable is not retried; the banner explains it.
