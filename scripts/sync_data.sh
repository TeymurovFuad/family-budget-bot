#!/bin/bash
# sync_data.sh
# Upload your updated Excel file to the GCS bucket.
# Requires: gcloud CLI or gsutil, or falls back to Python.
#
# Set these in your shell profile (~/.zshrc or ~/.bashrc):
#   export XLSX_PATH="$HOME/Documents/Expenses_Improved.xlsx"
#   export GCS_BUCKET_NAME="your-bucket-name"
#   export GCS_KEY_JSON="$(cat /path/to/service-account-key.json)"
#
# Usage: ./scripts/sync_data.sh

EXCEL_SOURCE="${XLSX_PATH:-${BUDGET_EXCEL_PATH:-$HOME/Documents/Expenses_Improved.xlsx}}"
BUCKET="${GCS_BUCKET_NAME}"
OBJECT="${GCS_OBJECT_NAME:-Expenses_Improved.xlsx}"
# Backward compatibility: BUDGET_EXCEL_PATH is supported if XLSX_PATH is unset.

if [ ! -f "$EXCEL_SOURCE" ]; then
  echo "ERROR: Excel file not found at $EXCEL_SOURCE"
  echo "Set XLSX_PATH in your shell profile."
  exit 1
fi

if [ -z "$BUCKET" ]; then
  echo "ERROR: GCS_BUCKET_NAME is not set."
  echo "Set it in your shell profile: export GCS_BUCKET_NAME=your-bucket-name"
  exit 1
fi

echo "Uploading $EXCEL_SOURCE to gs://$BUCKET/$OBJECT ..."

# Try gsutil first (fastest if gcloud is installed)
if command -v gsutil &> /dev/null; then
  gsutil cp "$EXCEL_SOURCE" "gs://$BUCKET/$OBJECT"
  echo "Done (via gsutil)."
  exit 0
fi

# Fall back to Python + google-cloud-storage
python3 - << PYEOF
import os, json
from google.cloud import storage
from google.oauth2 import service_account

key_json = os.environ.get("GCS_KEY_JSON", "")
if key_json:
    credentials = service_account.Credentials.from_service_account_info(json.loads(key_json))
    client = storage.Client(credentials=credentials)
else:
    client = storage.Client()

bucket = client.bucket("$BUCKET")
blob   = bucket.blob("$OBJECT")
blob.upload_from_filename("$EXCEL_SOURCE")
print("Done (via Python).")
PYEOF
