#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ $(uname -s) != Darwin || $(uname -m) != arm64 ]]; then
  echo 'Build this target on an Apple Silicon Mac.' >&2
  exit 1
fi
PYTHON="${PYTHON:-python3}"
VENV="${VENV:-.venv}"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --index-url https://pypi.org/simple -r packaging/macos/requirements-build.lock.txt
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/scg-build-test-XXXXXX")
trap 'rm -rf "$TEST_TMP"' EXIT
PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m pytest -q -p no:cacheprovider --basetemp="$TEST_TMP/pytest"
"$VENV/bin/python" -m PyInstaller --noconfirm packaging/macos/SCG_StereoRejoin.spec
codesign --verify --deep --strict 'dist/SCG StereoRejoin.app'
echo 'Built: dist/SCG StereoRejoin.app (Apple Silicon, macOS 14 or later)'
