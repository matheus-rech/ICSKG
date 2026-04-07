#!/usr/bin/env bash
# ============================================================================
# ICSKG-BR replication self-test
# ============================================================================
# Exercises docs/REPLICATION.md end-to-end on a fresh clone of THIS repo.
# If this script exits 0, the replication walkthrough is accurate. If it
# fails at step N, fix step N in REPLICATION.md before the next release.
#
# Run this before every release / before sending the dataset to BMJ reviewers.
#
# Usage:
#     export HF_TOKEN=hf_...
#     bash docs/REPLICATION.test.sh                # default: clean up after
#     bash docs/REPLICATION.test.sh --keep         # leave the temp clone
#                                                  # for inspection
#
# Requirements:
#     - python 3.12 (or uv)
#     - git
#     - HF_TOKEN env var with read access to matheus-rech/icskg-br-processed
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------

if [ -t 1 ]; then
    GREEN="$(printf '\033[0;32m')"
    RED="$(printf '\033[0;31m')"
    YELLOW="$(printf '\033[0;33m')"
    BOLD="$(printf '\033[1m')"
    RESET="$(printf '\033[0m')"
else
    GREEN=""; RED=""; YELLOW=""; BOLD=""; RESET=""
fi

step() {
    printf "%s%s==>%s%s %s%s\n" "$BOLD" "$GREEN" "$RESET" "$BOLD" "$1" "$RESET"
}

warn() {
    printf "%s%s[warn]%s %s\n" "$BOLD" "$YELLOW" "$RESET" "$1"
}

fail() {
    printf "%s%s[fail]%s %s\n" "$BOLD" "$RED" "$RESET" "$1" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

KEEP=0
for arg in "$@"; do
    case "$arg" in
        --keep)  KEEP=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            fail "Unknown arg: $arg"
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

step "Pre-flight checks"

if [ -z "${HF_TOKEN:-}" ]; then
    fail "HF_TOKEN environment variable is required.
       Get a read-scoped token from https://huggingface.co/settings/tokens
       and run: export HF_TOKEN=hf_yourtokenhere"
fi

if ! command -v git >/dev/null 2>&1; then
    fail "git not found in PATH"
fi

if ! command -v python3.12 >/dev/null 2>&1 && ! command -v uv >/dev/null 2>&1; then
    fail "Need either python3.12 or uv in PATH. Install one and retry."
fi

# Find the repo root that contains this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
    fail "Could not find pyproject.toml at $REPO_ROOT — is this script in docs/?"
fi
echo "  source repo: $REPO_ROOT"

# ---------------------------------------------------------------------------
# Set up isolated workspace
# ---------------------------------------------------------------------------

WORK="$(mktemp -d)"

cleanup() {
    if [ "$KEEP" -eq 1 ]; then
        warn "Leaving workspace at: $WORK"
    else
        rm -rf "$WORK"
    fi
}
trap cleanup EXIT INT TERM

step "Created isolated workspace: $WORK"

# ---------------------------------------------------------------------------
# Step 1: Clone the repo (file:// URL — uses local commits, no network)
# ---------------------------------------------------------------------------

step "[step 1/6] Clone the repository"
cd "$WORK"
git clone --quiet "file://$REPO_ROOT" ICSKG
cd ICSKG

# ---------------------------------------------------------------------------
# Step 2: Install dependencies
# ---------------------------------------------------------------------------

step "[step 2/6] Install dependencies"
if command -v uv >/dev/null 2>&1; then
    uv sync --quiet
    PYTHON="uv run python"
    PYTEST="uv run pytest"
    PYMOD="uv run python -m"
else
    python3.12 -m venv .venv
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -e .
    pip install --quiet pytest
    PYTHON="python"
    PYTEST="python -m pytest"
    PYMOD="python -m"
fi

# ---------------------------------------------------------------------------
# Step 3: Run the unit test suite
# ---------------------------------------------------------------------------

step "[step 3/6] Run unit test suite (sanity check)"
$PYTEST tests/ -q --tb=line >/tmp/icskg_replication_pytest.log 2>&1 || {
    cat /tmp/icskg_replication_pytest.log
    fail "Unit tests failed. Check /tmp/icskg_replication_pytest.log"
}
TEST_COUNT="$(grep -oE '[0-9]+ passed' /tmp/icskg_replication_pytest.log | head -1 || echo "?")"
echo "  $TEST_COUNT"

# ---------------------------------------------------------------------------
# Step 4: Fetch + verify + materialize the database
# ---------------------------------------------------------------------------

step "[step 4/6] Fetch + verify + materialize from HF (revision v0.1.0)"
$PYMOD database.fetch_processed_data \
    --revision v0.1.0 \
    --to database/icskg_br.sqlite \
    >/tmp/icskg_replication_fetch.log 2>&1 || {
    cat /tmp/icskg_replication_fetch.log
    fail "Fetch failed. Check /tmp/icskg_replication_fetch.log"
}

# ---------------------------------------------------------------------------
# Step 5: Verify the materialized SQLite
# ---------------------------------------------------------------------------

step "[step 5/6] Verify materialized SQLite"
if [ ! -f database/icskg_br.sqlite ]; then
    fail "database/icskg_br.sqlite was not created"
fi

# Use a heredoc + os.environ pattern (no string interpolation, no injection)
$PYTHON <<'PYCHECK' || fail "SQLite verification failed"
import sqlite3
import sys

conn = sqlite3.connect("database/icskg_br.sqlite")
try:
    n = conn.execute("SELECT COUNT(*) FROM municipal_health").fetchone()[0]
    if n != 50130:
        print(f"FAIL: expected 50130 rows in municipal_health, got {n}", file=sys.stderr)
        sys.exit(1)

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    required = {"municipal_health"}
    missing = required - set(tables)
    if missing:
        print(f"FAIL: missing required tables: {missing}", file=sys.stderr)
        sys.exit(1)

    print(f"OK: {n} rows in municipal_health, tables: {tables}")
finally:
    conn.close()
PYCHECK

# ---------------------------------------------------------------------------
# Step 6: Spot-check a known cell
# ---------------------------------------------------------------------------

step "[step 6/6] Spot-check a known panel value"
$PYTHON <<'PYSPOT' || fail "Spot-check failed — published data may have changed"
import sqlite3
import sys

conn = sqlite3.connect("database/icskg_br.sqlite")
try:
    # São Paulo 2023 should always have a CUDS value
    row = conn.execute(
        "SELECT cuds FROM municipal_health "
        "WHERE cod_ibge = '3550308' AND year = 2023"
    ).fetchone()
    if row is None or row[0] is None:
        print("FAIL: São Paulo 2023 CUDS is missing", file=sys.stderr)
        sys.exit(1)
    print(f"OK: São Paulo 2023 CUDS = {row[0]:.4f}")
finally:
    conn.close()
PYSPOT

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

step "All replication steps passed"
echo ""
echo "  ${GREEN}✓${RESET} clone"
echo "  ${GREEN}✓${RESET} install dependencies"
echo "  ${GREEN}✓${RESET} unit tests ($TEST_COUNT)"
echo "  ${GREEN}✓${RESET} fetch + verify + materialize"
echo "  ${GREEN}✓${RESET} sqlite has 50130 rows in municipal_health"
echo "  ${GREEN}✓${RESET} São Paulo 2023 cell present"
echo ""
echo "  ${BOLD}docs/REPLICATION.md is accurate.${RESET}"
exit 0
