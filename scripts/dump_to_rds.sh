#!/usr/bin/env bash
# Dump PostgreSQL from local Docker container and restore to RDS.
# Usage:
#   ./scripts/dump_to_rds.sh <rds_host>
#   ./scripts/dump_to_rds.sh   # uses terraform output -rds_address
#
# Prereqs: Docker container "charlottesville_db" running, psql and pg_dump on PATH (or use Docker for restore).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -n "${1:-}" ]]; then
  RDS_HOST="$1"
else
  RDS_HOST="$(terraform -chdir="$REPO_ROOT" output -raw rds_address 2>/dev/null)" || true
fi
RDS_USER="events"
RDS_PASSWORD="eventspassword"
RDS_DB="events"
CONTAINER="${CONTAINER:-charlottesville_db}"

if [[ -z "$RDS_HOST" ]]; then
  echo "Usage: $0 <rds_host>"
  echo "  or run 'terraform output rds_address' and pass it, or run this from repo root after terraform apply"
  exit 1
fi

echo "Dumping from container $CONTAINER..."
docker exec "$CONTAINER" pg_dump -U events --no-owner --no-acl events > /tmp/events_dump.sql

echo "Restoring to RDS at $RDS_HOST..."
export PGPASSWORD="$RDS_PASSWORD"
if command -v psql &>/dev/null; then
  psql -h "$RDS_HOST" -U "$RDS_USER" -d "$RDS_DB" -f /tmp/events_dump.sql
else
  echo "psql not found; using Docker..."
  docker run --rm -i -e PGPASSWORD="$RDS_PASSWORD" postgres:16 \
    psql -h "$RDS_HOST" -U "$RDS_USER" -d "$RDS_DB" -f - < /tmp/events_dump.sql
fi

echo "Done. Remove dump file with: rm /tmp/events_dump.sql"
