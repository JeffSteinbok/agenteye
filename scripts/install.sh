#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="agenteye-app"
MINOR_MIN=11
MARKER_BEGIN="# >>> agenteye >>>"
MARKER_END="# <<< agenteye <<<"

is_wsl() {
  [ -f /proc/version ] && grep -qiE "(microsoft|wsl)" /proc/version
}

find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, ${MINOR_MIN}) else 1)" >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

select_profile() {
  case "${SHELL:-}" in
    */zsh) printf '%s\n' "${HOME}/.zshrc" ;;
    */bash) printf '%s\n' "${HOME}/.bashrc" ;;
    *) printf '%s\n' "${HOME}/.profile" ;;
  esac
}

ensure_path_entry() {
  local target="$1"
  local scripts_dir="$2"
  local line="export PATH=\"${scripts_dir}:\$PATH\""

  mkdir -p "$(dirname "$target")"
  touch "$target"

  if ! grep -F "$MARKER_BEGIN" "$target" >/dev/null 2>&1; then
    {
      printf '\n%s\n' "$MARKER_BEGIN"
      printf '%s\n' "$line"
      printf '%s\n' "$MARKER_END"
    } >>"$target"
  fi
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "Agent Eye requires Python 3.11 or newer. Install Python first, then rerun this script." >&2
  exit 1
fi

PLATFORM_NAME="Linux"
if [ "$(uname -s)" = "Darwin" ]; then
  PLATFORM_NAME="macOS"
elif is_wsl; then
  PLATFORM_NAME="WSL2"
fi

echo "Installing Agent Eye for ${PLATFORM_NAME} using ${PYTHON_BIN}..."
"$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$PYTHON_BIN" -m pip install --user --upgrade "$PACKAGE_NAME"

SCRIPTS_DIR="$("$PYTHON_BIN" -c 'import os, sysconfig; print(sysconfig.get_path("scripts", scheme=sysconfig.get_preferred_scheme("user")))' )"
PROFILE_TARGET="$(select_profile)"

ensure_path_entry "$PROFILE_TARGET" "$SCRIPTS_DIR"
export PATH="${SCRIPTS_DIR}:$PATH"

"$PYTHON_BIN" -m src.session_dashboard _record-install \
  --method bootstrap-user-pip \
  --scripts-dir "$SCRIPTS_DIR" \
  --path-target "$PROFILE_TARGET" \
  --python-executable "$("$PYTHON_BIN" -c 'import os, sys; print(os.path.abspath(sys.executable))')"

if [ -x "${SCRIPTS_DIR}/agenteye" ]; then
  echo "Agent Eye installed to ${SCRIPTS_DIR}/agenteye"
else
  echo "Agent Eye was installed, but ${SCRIPTS_DIR}/agenteye was not found on disk." >&2
  exit 1
fi

echo "PATH persistence updated in ${PROFILE_TARGET}"
echo "Run 'agenteye start' in a new shell, or run:"
echo "  export PATH=\"${SCRIPTS_DIR}:\$PATH\""
