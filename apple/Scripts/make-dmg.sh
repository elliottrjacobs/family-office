#!/usr/bin/env bash
# Build the distribution DMG from a signed app.
#
#   apple/Scripts/make-dmg.sh path/to/FamilyOffice.app [IDENTITY] [OUTDIR]
#
# Writes OUTDIR/FamilyOffice-<version>-<arch>.dmg (OUTDIR defaults to the current directory):
# a compressed read-only image holding the app and a link to /Applications. <version> is the
# app's CFBundleShortVersionString; <arch> is the bundled interpreter's architecture (arm64 or
# x86_64), or FO_DMG_ARCH when set. With IDENTITY (not "-") the image is signed with a secure
# timestamp; "-" signs it ad-hoc and an empty or omitted IDENTITY leaves it unsigned.
# The path of the DMG is the last line of output.
set -euo pipefail

die() {
    echo "make-dmg: $*" >&2
    exit 1
}

[ $# -ge 1 ] && [ $# -le 3 ] || die "usage: make-dmg.sh APP [IDENTITY] [OUTDIR]"
app="${1%/}"
identity="${2:-}"
outdir="${3:-.}"
[ -d "$app/Contents/MacOS" ] || die "not an app bundle: $app"
codesign --verify --deep --strict "$app" || die "sign the app first (Scripts/sign-bundle.sh)"

version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")"
[ -n "$version" ] || die "no CFBundleShortVersionString in $app"

arch="${FO_DMG_ARCH:-}"
if [ -z "$arch" ]; then
    interpreter="$app/Contents/Resources/fo/python/bin/python3.12"
    [ -f "$interpreter" ] || die "no bundled runtime in $app; set FO_DMG_ARCH to name the image"
    arch="$(lipo -archs "$interpreter")"
    case "$arch" in
        arm64 | x86_64) ;;
        *) die "unexpected interpreter architecture: $arch" ;;
    esac
fi

mkdir -p "$outdir"
dmg="$(cd "$outdir" && pwd)/FamilyOffice-${version}-${arch}.dmg"

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
ditto "$app" "$staging/$(basename "$app")"
ln -s /Applications "$staging/Applications"

rm -f "$dmg"
hdiutil create -quiet -volname "Family Office" -srcfolder "$staging" -fs HFS+ \
    -format UDZO -imagekey zlib-level=9 -ov "$dmg"

if [ -n "$identity" ]; then
    flags=(--force --sign "$identity")
    [ "$identity" = "-" ] || flags+=(--timestamp)
    codesign "${flags[@]}" "$dmg"
    codesign --verify "$dmg"
fi
hdiutil verify -quiet "$dmg"
echo "$dmg"
