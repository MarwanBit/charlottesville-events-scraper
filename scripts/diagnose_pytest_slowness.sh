#!/usr/bin/env bash
# Quick checks to find what makes pytest slow. Run from project root.

set -e
cd "$(dirname "$0")/.."

echo "=== 1. Disk space (low space = slow I/O → real time >> user+sys) ==="
df -h . 2>/dev/null || df -h
echo ""

echo "=== 2. Time: import only (no pytest) ==="
echo "If real >> user+sys, the process is blocked on I/O (often disk)."
time python -c "from src.app.explore_georgia_parsing import parse_event_datetime_range" 2>/dev/null
echo ""

echo "=== 3. Time: pytest collect only (where it often stalls) ==="
time python -m pytest tests/unit/test_parse_explore_georgia_date_parsing.py --collect-only -q 2>/dev/null
echo ""

echo "=== 4. Run tests WITHOUT pytest (skips collection; use while fixing disk) ==="
time python tests/unit/test_parse_explore_georgia_date_parsing.py 2>/dev/null
echo ""

echo "=== 5. Full pytest run with durations ==="
python -m pytest tests/unit/test_parse_explore_georgia_date_parsing.py -v --durations=0 2>/dev/null
echo ""

echo "--- Tips ---"
echo "If step 2 or 3 is slow with real >> user+sys: free disk (./scripts/free_some_space.sh), then retry."
echo "To see which import blocks: python -v -c 'from src.app.explore_georgia_parsing import parse_event_datetime_range' 2>&1 | tail -20"
