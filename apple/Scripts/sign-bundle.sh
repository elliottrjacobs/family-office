#!/usr/bin/env bash
# Sign the Mac app bundle from the inside out.
#
#   apple/Scripts/sign-bundle.sh path/to/FamilyOffice.app                 # ad-hoc ("-")
#   apple/Scripts/sign-bundle.sh path/to/FamilyOffice.app "Developer ID Application: …"
#
# Order (codesign seals each container over what is already signed inside it):
#   1. every Mach-O file under Contents/Resources/fo/ (the bundled Python): shared libraries
#      and extension modules first, then the executables (the python3.12 interpreter), which
#      get the interpreter entitlements in apple/FamilyOffice/FamilyOffice.entitlements;
#   2. each framework in Contents/Frameworks/: its nested XPC services, helper apps and loose
#      executables (Sparkle's Installer.xpc, Downloader.xpc, Updater.app and Autoupdate),
#      deepest first, keeping their own entitlements, then the framework itself;
#   3. the app, without entitlements (it needs none; only the interpreter does).
#
# The launchers bin/fo and venv/bin/fo are shell scripts, not Mach-O: the app's signature
# seals them as resources.
#
# With a real identity every signature gets the hardened runtime and a secure timestamp, as
# notarization requires. Ad-hoc signatures get neither by default: an ad-hoc signature has no
# Team ID, so under the hardened runtime library validation rejects every framework the app
# links (Sparkle) and the app cannot launch. FO_SIGN_RUNTIME=1 adds the hardened runtime to an
# ad-hoc run anyway, which is how the interpreter entitlements were tested (the bundled fo runs;
# the app itself does not). FO_SIGN_ENTITLEMENTS overrides the interpreter entitlements file.
set -euo pipefail

die() {
    echo "sign-bundle: $*" >&2
    exit 1
}

[ $# -ge 1 ] && [ $# -le 2 ] || die "usage: sign-bundle.sh APP [IDENTITY]"
app="${1%/}"
identity="${2:--}"
[ -d "$app/Contents/MacOS" ] || die "not an app bundle: $app"

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLE="$(dirname "$SCRIPTS")"
entitlements="${FO_SIGN_ENTITLEMENTS:-$APPLE/FamilyOffice/FamilyOffice.entitlements}"
[ -f "$entitlements" ] || die "entitlements file not found: $entitlements"

flags=(--force --sign "$identity")
if [ "$identity" = "-" ]; then
    runtime="${FO_SIGN_RUNTIME:-0}"
else
    runtime="${FO_SIGN_RUNTIME:-1}"
    [ "$runtime" = "1" ] || die "a real identity always signs with the hardened runtime"
    flags+=(--timestamp)
fi
if [ "$runtime" = "1" ]; then
    flags+=(--options runtime)
fi

sign() {
    codesign "${flags[@]}" "$@"
}

is_macho() {
    file -b "$1" | grep -q '^Mach-O'
}

count=0

# 1. The bundled Python runtime.
fo="$app/Contents/Resources/fo"
if [ -d "$fo" ]; then
    libraries=()
    executables=()
    while IFS= read -r -d '' path; do
        is_macho "$path" || continue
        if file -b "$path" | grep -q 'executable'; then
            executables+=("$path")
        else
            libraries+=("$path")
        fi
    done < <(find "$fo" -type f -print0)
    for path in ${libraries[@]+"${libraries[@]}"}; do
        sign "$path"
        count=$((count + 1))
    done
    for path in ${executables[@]+"${executables[@]}"}; do
        sign --entitlements "$entitlements" "$path"
        count=$((count + 1))
    done
    echo "Signed ${#libraries[@]} libraries and ${#executables[@]} executables in Resources/fo"
else
    echo "note: $fo not found; signing the app without the bundled runtime."
fi

# 2. Embedded frameworks (SwiftTerm is linked statically; Sparkle is a framework).
if [ -d "$app/Contents/Frameworks" ]; then
    while IFS= read -r -d '' framework; do
        # Nested bundles, deepest first, so each container is signed after its contents.
        while IFS= read -r nested; do
            sign --preserve-metadata=entitlements "$nested"
            count=$((count + 1))
        done < <(find "$framework" \( -name '*.xpc' -o -name '*.app' \) -type d |
            awk '{ print gsub("/", "/"), $0 }' | sort -rn | cut -d' ' -f2-)
        # Loose helper executables directly in the framework's version directories.
        while IFS= read -r -d '' path; do
            is_macho "$path" || continue
            [ "$(basename "$path")" = "$(basename "$framework" .framework)" ] && continue
            sign --preserve-metadata=entitlements "$path"
            count=$((count + 1))
        done < <(find "$framework/Versions" -mindepth 2 -maxdepth 2 -type f -perm -u+x -print0 2>/dev/null)
        sign "$framework"
        count=$((count + 1))
        echo "Signed $(basename "$framework")"
    done < <(find "$app/Contents/Frameworks" -mindepth 1 -maxdepth 1 \
        \( -name '*.framework' -o -name '*.dylib' \) -print0)
fi

# 3. The app.
sign "$app"
count=$((count + 1))
echo "Signed $count items with identity '$identity' (hardened runtime: $([ "$runtime" = 1 ] && echo on || echo off))"

codesign --verify --deep --strict "$app"
echo "codesign --verify --deep --strict: ok"
