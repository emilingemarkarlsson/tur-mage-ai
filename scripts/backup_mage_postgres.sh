#!/usr/bin/env bash
# Backup Mage's Postgres metadata-DB till MinIO (platform-backups bucket).
#
# Körs från Coolify-servern (tha). Kan också köras lokalt via SSH:
#   ssh tha "bash -s" < scripts/backup_mage_postgres.sh
#
# Upload-path: s3://platform-backups/mage-postgres/YYYY-MM-DD_HH-MM-SS.dump.gz
# Retention: 30 dagar (äldre raderas automatiskt av scriptet)
#
# Env-vars (MINIO_*) läses från mage-containern.

set -euo pipefail

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres-k0oooc8ok4848880sk0g0kkc}"
MAGE_CONTAINER="${MAGE_CONTAINER:-mage-k0oooc8ok4848880sk0g0kkc}"
BACKUP_BUCKET="${BACKUP_BUCKET:-platform-backups}"
BACKUP_PREFIX="${BACKUP_PREFIX:-mage-postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

TS="$(date +%Y-%m-%d_%H-%M-%S)"
LOG_PREFIX="[mage-backup $TS]"

log() { echo "$LOG_PREFIX $*"; }

log "Starting backup of $POSTGRES_CONTAINER → s3://$BACKUP_BUCKET/$BACKUP_PREFIX/"

# Steg 1: dumpa postgres till tmp-fil i postgres-container (format=custom = compressed by default)
TMP_DUMP="/tmp/mage-backup-${TS}.dump"
docker exec "$POSTGRES_CONTAINER" bash -c "
  pg_dump -U \$POSTGRES_USER -d \$POSTGRES_DB --clean --if-exists --no-owner \
    --format=custom --compress=6 -f $TMP_DUMP
  stat -c %s $TMP_DUMP
" | tail -1 | read DUMP_SIZE || true
log "Dump ready"

# Steg 2: kopiera ut och in i mage-container
HOST_TMP="/tmp/mage-backup-${TS}.dump"
docker cp "$POSTGRES_CONTAINER:$TMP_DUMP" "$HOST_TMP"
docker exec "$POSTGRES_CONTAINER" rm -f "$TMP_DUMP"

SIZE=$(stat -c %s "$HOST_TMP")
log "Dump size: $SIZE bytes"

docker cp "$HOST_TMP" "$MAGE_CONTAINER:/tmp/backup.dump"
rm -f "$HOST_TMP"

# Steg 3: Upload till MinIO + retention
docker exec -i \
  -e BACKUP_BUCKET="$BACKUP_BUCKET" \
  -e BACKUP_KEY="$BACKUP_PREFIX/${TS}.dump" \
  -e RETENTION_DAYS="$RETENTION_DAYS" \
  "$MAGE_CONTAINER" python3 - <<'PYEOF'
import os, sys, boto3
from datetime import datetime, timezone, timedelta

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["MINIO_ENDPOINT"],
    aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
    aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
    region_name=os.environ.get("MINIO_REGION", "us-east-1"),
)

bucket = os.environ["BACKUP_BUCKET"]
key = os.environ["BACKUP_KEY"]
retention_days = int(os.environ["RETENTION_DAYS"])

s3.upload_file("/tmp/backup.dump", bucket, key)
size = os.path.getsize("/tmp/backup.dump")
print(f"Uploaded {size:,} bytes to s3://{bucket}/{key}", flush=True)
os.remove("/tmp/backup.dump")

cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
paginator = s3.get_paginator("list_objects_v2")
prefix = key.rsplit("/", 1)[0] + "/"
deleted = 0
kept = 0
for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
    for obj in page.get("Contents", []):
        if obj["LastModified"] < cutoff:
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
            print(f"  deleted: {obj['Key']} ({obj['LastModified'].date()})", flush=True)
            deleted += 1
        else:
            kept += 1
print(f"Retention: kept {kept}, deleted {deleted} backups older than {retention_days} days", flush=True)
PYEOF

log "Backup complete"
