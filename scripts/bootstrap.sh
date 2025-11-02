#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'USAGE'
Usage: scripts/bootstrap.sh [options]

Creates (if needed) a local Python virtual environment, installs project
requirements, initialises the database, optionally seeds demo data, and launches
the Flask development server.

Options:
  --no-seed      Skip loading demo data via `flask --app manage.py seed-demo`.
  --skip-run     Only perform setup steps without starting the dev server.
  -h, --help     Show this help message and exit.
USAGE
}

SEED_DEMO=1
RUN_SERVER=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-seed)
      SEED_DEMO=0
      ;;
    --skip-run)
      RUN_SERVER=0
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      show_help >&2
      exit 1
      ;;
  esac
  shift
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found in PATH" >&2
  exit 1
fi

VENV_DIR="$PROJECT_ROOT/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

flask --app manage.py init-db

if [[ "$SEED_DEMO" -eq 1 ]]; then
  flask --app manage.py seed-demo
fi

if [[ "$RUN_SERVER" -eq 1 ]]; then
  flask --app app run --debug
fi
