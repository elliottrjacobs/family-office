#!/usr/bin/env bash
# Build the Python runtime the Mac app ships in Contents/Resources/fo.
#
#   apple/Scripts/bundle-python.sh            # host architecture
#   FO_BUNDLE_ARCH=x86_64 apple/Scripts/...   # force one architecture
#
# Output, under apple/Resources/fo/ (a build product, never committed):
#   python/   python-build-standalone 3.12 install_only runtime
#   venv/     virtual environment with the family-office wheel and its locked dependencies
#   bin/fo    launcher the app runs; it execs venv/bin/fo
#
# The result is relocatable: the venv's interpreter is a relative symlink into python/, its
# pyvenv.cfg carries no absolute home, and its entry points are uv's relocatable trampolines,
# so the tree works after Xcode copies it into the app bundle.
#
# Running it again rebuilds the tree from scratch; the downloaded archive is cached under
# apple/build/python-cache/ and re-verified against its checksum on every run.
#
# TODO(U12): sign every Mach-O file under python/ and venv/ with the Developer ID, the hardened
# runtime and the interpreter's entitlements before the app itself is signed and notarized.
set -euo pipefail

# python-build-standalone release pinned by exact tag and SHA-256 (from the release's
# SHA256SUMS, checked 2026-11-04). Update all four values together.
PBS_TAG="20261026"
PBS_PYTHON="3.12.16"
PBS_SHA256_AARCH64="fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e"
PBS_SHA256_X86_64="a962e47df522889eaa7ff0d6a56203f1079f68aabb65ffdbe8455f362bc769f3"

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLE="$(dirname "$SCRIPTS")"
REPO="$(dirname "$APPLE")"
OUT="$APPLE/Resources/fo"
CACHE="${FO_BUNDLE_CACHE:-$APPLE/build/python-cache}"

die() {
    echo "bundle-python: $*" >&2
    exit 1
}

command -v uv >/dev/null || die "uv is required (https://docs.astral.sh/uv/)."

arch="${FO_BUNDLE_ARCH:-$(uname -m)}"
case "$arch" in
    arm64 | aarch64)
        triple="aarch64-apple-darwin"
        sha="$PBS_SHA256_AARCH64"
        ;;
    x86_64)
        triple="x86_64-apple-darwin"
        sha="$PBS_SHA256_X86_64"
        ;;
    *) die "unsupported architecture: $arch" ;;
esac

archive="cpython-${PBS_PYTHON}+${PBS_TAG}-${triple}-install_only.tar.gz"
url="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${archive//+/%2B}"

mkdir -p "$CACHE"
if [ ! -f "$CACHE/$archive" ] || ! echo "$sha  $CACHE/$archive" | shasum -a 256 -c --status; then
    echo "Downloading $archive"
    curl -fL --retry 3 -o "$CACHE/$archive.part" "$url"
    mv "$CACHE/$archive.part" "$CACHE/$archive"
fi
echo "$sha  $CACHE/$archive" | shasum -a 256 -c --status ||
    die "checksum mismatch for $archive; delete $CACHE and retry."

echo "Unpacking the runtime"
rm -rf "$OUT"
mkdir -p "$OUT/bin"
tar -xzf "$CACHE/$archive" -C "$OUT"
runtime="$OUT/python/bin/python3"
"$runtime" -I -c 'import sys; assert sys.version_info[:2] == (3, 12)' || die "runtime is not 3.12"

version="$(cd "$REPO" && "$runtime" -I -c \
    'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
wheel="$REPO/dist/family_office-${version}-py3-none-any.whl"
echo "Building the family-office $version wheel"
(cd "$REPO" && uv build --wheel --out-dir dist >/dev/null)
[ -f "$wheel" ] || die "expected $wheel after uv build"

echo "Creating the virtual environment"
uv venv --quiet --relocatable --python "$runtime" "$OUT/venv"
requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT
(cd "$REPO" && uv export --quiet --frozen --no-dev --no-emit-project \
    --format requirements.txt --output-file "$requirements")
uv pip install --quiet --python "$OUT/venv/bin/python" --require-hashes -r "$requirements"
uv pip install --quiet --python "$OUT/venv/bin/python" --no-deps "$wheel"

# Point the venv at the bundled runtime by a relative path so the tree can move.
pyver="python3.12"
rm -f "$OUT/venv/bin/python" "$OUT/venv/bin/python3" "$OUT/venv/bin/$pyver"
ln -s "../../python/bin/$pyver" "$OUT/venv/bin/$pyver"
ln -s "$pyver" "$OUT/venv/bin/python3"
ln -s "$pyver" "$OUT/venv/bin/python"
cfg="$OUT/venv/pyvenv.cfg"
grep -v -E '^(home|executable|command|uv) *=' "$cfg" >"$cfg.new" || true
mv "$cfg.new" "$cfg"

echo "Pruning"
find "$OUT" -type d \( -name __pycache__ -o -name test -o -name tests \) -prune -exec rm -rf {} +
stdlib="$OUT/python/lib/$pyver"
rm -rf "$stdlib/idlelib" "$stdlib/tkinter" "$stdlib/ensurepip" "$stdlib/turtledemo"
rm -f "$stdlib"/lib-dynload/_tkinter*.so
rm -rf "$OUT"/python/lib/tcl* "$OUT"/python/lib/tk* "$OUT"/python/lib/itcl* "$OUT"/python/lib/thread*
rm -rf "$OUT/python/share"
rm -f "$OUT"/python/bin/idle3* "$OUT"/python/bin/pydoc3*

# The signed bundle is read-only, so the launcher never writes bytecode and ignores any
# Python variables the caller's environment might carry.
cat >"$OUT/bin/fo" <<'LAUNCHER'
#!/bin/sh
# family-office launcher inside the Mac app bundle.
# Follow links first: Settings > General installs /usr/local/bin/fo as a link to this file.
self="$0"
while [ -L "$self" ]; do
  link="$(readlink "$self")"
  case "$link" in
    /*) self="$link" ;;
    *) self="$(dirname "$self")/$link" ;;
  esac
done
here="$(cd "$(dirname "$self")" && pwd -P)"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE PYTHONEXECUTABLE
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$here/../venv/bin/fo" "$@"
LAUNCHER
chmod 755 "$OUT/bin/fo"

reported="$("$OUT/bin/fo" --version)"
[ "$reported" = "family-office $version" ] || die "launcher reported '$reported'"
echo "$reported"
echo "Bundle size: $(du -sh "$OUT" | awk '{print $1}') at apple/Resources/fo"
