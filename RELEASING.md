# Releasing the Mac app

A release is a pushed `v*` tag. `.github/workflows/release-mac.yml` then builds the Apple Silicon
DMG (`FamilyOffice-<version>-arm64.dmg`), signs it with the Developer ID, notarizes and staples
it, signs the Sparkle appcast, and attaches both to a draft GitHub Release. Publishing the draft is what makes installed apps see the
update.

Signing material lives only in the GitHub `release` environment's secrets. Nothing in this
repository, and nothing on a developer Mac, needs the certificate, the notarization key or the
Sparkle private key.

## Repository protection

- The `release` environment holds all twelve signing and upload secrets (Mac, notary, Sparkle,
  iOS, App Store Connect). It requires the maintainer's approval for every run and accepts
  deployments only from `main` and `v*` tags. Only the Mac build job and the iOS job use it;
  the job that writes the release holds no secret. Keep no copies as repository secrets.
- Rulesets: `v*` tags can be created, moved or deleted only by repository admins; `main`
  refuses force-pushes and deletion, and changes land through pull requests with the `checks`,
  `app` and `apple` jobs passing.
- Every action in `.github/workflows/` is pinned by commit SHA, with the version in a comment.
  Bump the SHA and the comment together.

## Prerequisites

- An Apple Developer Program membership with a **Developer ID Application** certificate.
- An **App Store Connect API key** with the Developer role, for `notarytool`.
- Admin access to the GitHub repository's `release` environment and its secrets.
- For the one-time Sparkle setup only: a Mac with Xcode, to run Sparkle's `generate_keys`.

## One-time setup

### 1. Developer ID certificate

1. In Xcode > Settings > Accounts, or at developer.apple.com, create a Developer ID Application
   certificate. Export it from Keychain Access with its private key as a `.p12` and a strong
   export password.
2. Add two `release` environment secrets:
   - `MAC_CERT_P12`: the `.p12`, base64-encoded (`base64 -i cert.p12 | pbcopy`);
   - `MAC_CERT_PASSWORD`: the export password.
3. Delete the exported `.p12` file.

The workflow imports the certificate into a temporary keychain that it deletes at the end of
the job.

### 2. Notarization key

1. In App Store Connect > Users and Access > Integrations > Team Keys, create a key with the
   Developer role and download the `.p8` (it can be downloaded once).
2. Add three `release` environment secrets:
   - `NOTARY_KEY_ID`: the key ID;
   - `NOTARY_ISSUER_ID`: the issuer ID shown above the key list;
   - `NOTARY_KEY_P8`: the full contents of the `.p8` file, including the BEGIN and END lines.
3. Store the `.p8` in your password manager or delete it.

### 3. Sparkle update key

Sparkle refuses an update whose EdDSA signature does not verify against the public key built
into the installed app, so this key pair is what makes updates trustworthy. Generate it once and
never rotate it casually: apps already installed only trust the key they shipped with.

1. Download the Sparkle release that `project.yml` pins (`Sparkle-<version>.tar.xz` from
   github.com/sparkle-project/Sparkle/releases), unpack it, and run:

   ```sh
   ./bin/generate_keys                       # creates the key pair in your login keychain
   ./bin/generate_keys -x sparkle-private.key  # exports the private key to a file
   ```

   `generate_keys` prints the public key.
2. Add the `release` environment secret `SPARKLE_PRIVATE_KEY` with the contents of `sparkle-private.key`,
   then delete the file. Keep the keychain item (or a password-manager copy) as the backup; if
   the private key is lost, installed apps can no longer be updated by Sparkle.
3. Paste the public key into `apple/project.yml` in place of
   `SPARKLE_PUBLIC_ED_KEY_PLACEHOLDER` (the `SUPublicEDKey` entry), run `xcodegen generate` in
   `apple/`, and commit `project.yml` and `FamilyOffice/Info.plist`. The public key is not a
   secret.

Until step 3 is done the app does not start the updater: Check for Updates… and the Settings
toggle are disabled, and the workflow skips the appcast while `SPARKLE_PRIVATE_KEY` is unset.

### Without secrets

Every secret-using step is skipped with a notice when its secret is missing. A fork, or this
repository before the setup above, still gets ad-hoc signed DMGs (as workflow artifacts and on
a draft release) that run on the Mac that downloads them only after the quarantine attribute is
removed. They are for testing, never for distribution.

## Cutting a release

1. Make sure `main` is green in CI and `CHANGELOG.md` has the release's entry.
2. Keep the versions in step: `version` in `pyproject.toml`, `FOExpectedVersion` and
   `MARKETING_VERSION` in `apple/project.yml`. The workflow overrides `MARKETING_VERSION` with
   the tag (without its `v`) and sets the build number (`CFBundleVersion`, which Sparkle
   compares) to the commit count, so later tags always update earlier ones.
3. Tag and push:

   ```sh
   git tag -a v2.0.0 -m "family-office 2.0.0"
   git push origin v2.0.0
   ```

4. Approve the `release` deployments for the **Release Mac app** and **Release iOS** runs
   (Actions > the run > Review deployments). The Mac build job takes most of the time;
   notarization usually returns within a few minutes but can take longer.
5. Open the draft release, write the notes (include the `spctl` result from the next section),
   and publish it. Only a published, non-prerelease release is served at
   `releases/latest/download/appcast.xml`, the URL in `SUFeedURL`.

For a test run without a public release, use a tag such as `v0.0.0-test` on a fork, or run the
workflow from the Actions tab (**Run workflow**), optionally naming an existing tag whose
release should receive the assets. Delete test releases and tags afterwards.

## Verifying a release

On a Mac that has never built the app, download the DMG from the release page, then:

```sh
spctl -a -vv -t open --context context:primary-signature FamilyOffice-2.0.0-arm64.dmg
xcrun stapler validate FamilyOffice-2.0.0-arm64.dmg
hdiutil attach -nobrowse FamilyOffice-2.0.0-arm64.dmg
spctl -a -vv /Volumes/Family\ Office/FamilyOffice.app   # "accepted, source=Notarized Developer ID"
codesign --verify --deep --strict --verbose=2 /Volumes/Family\ Office/FamilyOffice.app
/Volumes/Family\ Office/FamilyOffice.app/Contents/Resources/fo/bin/fo --version
hdiutil detach /Volumes/Family\ Office
```

Then install it by dragging to Applications, open it (Gatekeeper must not warn beyond the
standard "downloaded from the internet" prompt), and check:

- Family Office > Check for Updates… is enabled and reports the app up to date;
- an older installed build, opened after the release is published, offers this version and
  installs it (Settings > General > Updates shows the last check);
- `appcast.xml` on the release has an `sparkle:edSignature` on its enclosure;
- the workflow log shows no secret values (GitHub masks them; nothing should print them).

## Rolling back

Sparkle never downgrades, so a bad release is replaced by a newer one rather than removed.

1. If the release is still a draft, delete it and its tag; nothing reached users.
2. If it is published and broken, mark it as a pre-release right away. `releases/latest` then
   falls back to the previous published release, so apps that have not updated yet stop being
   offered the bad build.
3. Fix forward: revert or fix on `main` and tag the next patch version. Installed copies of the
   bad build update to it through Sparkle.
4. If the bad build cannot update itself (for example the updater is broken), say so in the
   release notes and on the README with a link to the previous DMG; users reinstall by hand.
5. If a signing secret leaked: revoke the Developer ID certificate or the API key at Apple and
   replace the secret. A leaked Sparkle private key cannot be revoked in installed apps; ship a
   build with a new `SUPublicEDKey` signed by the old key, then use the new key from then on.
