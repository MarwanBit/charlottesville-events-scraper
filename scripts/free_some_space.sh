#!/usr/bin/env bash
# Free disk space by removing caches and build artifacts. Safe (no source deleted).
# Run from project root.

cd "$(dirname "$0")/.."

echo "=== Before ==="
df -h . 2>/dev/null || df -h
echo ""

echo "Removing .pytest_cache..."
rm -rf .pytest_cache 2>/dev/null || true

echo "Removing __pycache__ (excluding .venv)..."
find . -type d -name __pycache__ -not -path './.venv/*' 2>/dev/null | while read -r d; do rm -rf "$d" 2>/dev/null; done || true

echo "Removing .mypy_cache, .ruff_cache..."
rm -rf .mypy_cache .ruff_cache 2>/dev/null || true

echo "Removing build/ dist/ *.egg-info..."
rm -rf build dist *.egg-info 2>/dev/null || true
find . -maxdepth 3 -type d -name "*.egg-info" -not -path './.venv/*' 2>/dev/null | while read -r d; do rm -rf "$d" 2>/dev/null; done || true

echo "Removing coverage artifacts..."
rm -rf .coverage htmlcov 2>/dev/null || true

echo "Clearing pip cache (packages re-download when needed)..."
pip cache purge 2>/dev/null || true

echo ""
echo "=== After ==="
df -h . 2>/dev/null || df -h
echo ""
echo "Done."
echo ""
echo "--- More space (run these yourself if needed) ---"
echo "  Pip (all projects):    pip cache purge"
echo "  Homebrew:              brew cleanup -s"
echo "  Docker:                docker system prune -a   (removes unused images/containers)"
echo "  macOS caches:          rm -rf ~/Library/Caches/* (careful: app caches)"
echo "  Xcode derived data:    rm -rf ~/Library/Developer/Xcode/DerivedData/*"
echo "  npm:                   npm cache clean --force"
