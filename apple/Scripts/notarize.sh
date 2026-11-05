#!/usr/bin/env bash
# Submit a zip or DMG to Apple's notary service and wait for the verdict.
#
#   NOTARY_KEY_ID=… NOTARY_ISSUER_ID=… NOTARY_KEY_PATH=key.p8 apple/Scripts/notarize.sh FILE
#
# Uses an App Store Connect API key (Users and Access > Integrations > Team Keys). Exits 0 only
# when the submission is Accepted; otherwise prints the notary log, which names every file that
# failed, and exits 1. Stapling is left to the caller.
set -euo pipefail

die() {
    echo "notarize: $*" >&2
    exit 1
}

[ $# -eq 1 ] || die "usage: notarize.sh FILE"
file="$1"
[ -f "$file" ] || die "not a file: $file"
[ -n "${NOTARY_KEY_ID:-}" ] || die "NOTARY_KEY_ID is not set"
[ -n "${NOTARY_ISSUER_ID:-}" ] || die "NOTARY_ISSUER_ID is not set"
[ -f "${NOTARY_KEY_PATH:-}" ] || die "NOTARY_KEY_PATH does not name a file"

auth=(--key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER_ID")

echo "Submitting $(basename "$file") for notarization"
result="$(xcrun notarytool submit "$file" "${auth[@]}" --wait --timeout 1h --output-format json)" || true
id="$(plutil -extract id raw -o - - <<<"$result" 2>/dev/null || true)"
status="$(plutil -extract status raw -o - - <<<"$result" 2>/dev/null || true)"
echo "Submission ${id:-unknown}: ${status:-no status}"

if [ "$status" != "Accepted" ]; then
    if [ -n "$id" ]; then
        xcrun notarytool log "$id" "${auth[@]}" || true
    fi
    die "notarization of $(basename "$file") was not accepted"
fi
