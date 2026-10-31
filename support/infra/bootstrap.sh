#!/usr/bin/env bash
# One-time GCP setup for Tidy (Phase 0). Run by the owner from Cloud Shell or a
# Mac with gcloud. Identifiers come from the environment and are never committed.
#
#   export TIDY_GCP_PROJECT=<new project id>
#   export TIDY_BILLING_ACCOUNT=<billing account id>
#   bash support/infra/bootstrap.sh
#
# Keep the AI Studio API key's own project WITHOUT billing: a billed project
# moves the key off the free tier. Only the key's value is copied here, into
# Secret Manager. Budget calls bill their API quota to the Tidy project, never
# to the gcloud default project.
set -euo pipefail

: "${TIDY_GCP_PROJECT:?set TIDY_GCP_PROJECT}"
: "${TIDY_BILLING_ACCOUNT:?set TIDY_BILLING_ACCOUNT}"
REGION="${TIDY_REGION:-us-west1}"
P="$TIDY_GCP_PROJECT"

echo "== project and billing"
gcloud projects describe "$P" >/dev/null 2>&1 || gcloud projects create "$P" --name="tidy-dev"
gcloud billing projects link "$P" --billing-account="$TIDY_BILLING_ACCOUNT"

echo "== budget: alerts at \$1, \$5 and \$20 (alerts do not stop spend)"
gcloud services enable billingbudgets.googleapis.com --project="$P"
if ! gcloud billing budgets list --billing-account="$TIDY_BILLING_ACCOUNT" --billing-project="$P" \
     --format="value(displayName)" | grep -qx "tidy-dev"; then
  gcloud billing budgets create --billing-account="$TIDY_BILLING_ACCOUNT" --billing-project="$P" \
    --display-name="tidy-dev" --budget-amount=20USD \
    --filter-projects="projects/$P" \
    --threshold-rule=percent=0.05 --threshold-rule=percent=0.25 --threshold-rule=percent=1.0
fi

echo "== APIs needed in Phase 0 (later phases enable their own)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com \
  --project="$P"

echo "== Artifact Registry with a keep-last-2 cleanup policy"
gcloud artifacts repositories describe tidy --location="$REGION" --project="$P" >/dev/null 2>&1 || \
  gcloud artifacts repositories create tidy --repository-format=docker \
    --location="$REGION" --project="$P" --description="Tidy images"
policy=$(mktemp)
cat > "$policy" <<'JSON'
[
  {"name": "keep-last-2", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 2}},
  {"name": "delete-rest", "action": {"type": "Delete"}, "condition": {"tagState": "any"}}
]
JSON
gcloud artifacts repositories set-cleanup-policies tidy --location="$REGION" \
  --project="$P" --policy="$policy" --no-dry-run
rm -f "$policy"

echo "== runtime identity (no keys)"
SA="tidy-app@$P.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$SA" --project="$P" >/dev/null 2>&1 || \
  gcloud iam service-accounts create tidy-app --project="$P" --display-name="Tidy app runtime"

echo "== Gemini API key secret (value never echoed)"
gcloud secrets describe gemini-api-key --project="$P" >/dev/null 2>&1 || \
  gcloud secrets create gemini-api-key --project="$P" --replication-policy=user-managed \
    --locations="$REGION"
if [ -z "$(gcloud secrets versions list gemini-api-key --project="$P" \
             --filter=state=enabled --format='value(name)' --limit=1)" ]; then
  # Prefer Keychain (python -m keyring set tidy gemini-api-key); else prompt if interactive.
  ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
  PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
  KEY="$("$PY" -c "import keyring; print(keyring.get_password('tidy', 'gemini-api-key') or '')" 2>/dev/null || true)"
  if [ -z "$KEY" ] && [ -t 0 ]; then
    read -rsp "Paste the AI Studio API key: " KEY; echo
  fi
  if [ -n "$KEY" ]; then
    printf '%s' "$KEY" | gcloud secrets versions add gemini-api-key --project="$P" --data-file=-
  else
    echo "WARNING: no key in Keychain and no terminal to prompt. Add it later with:"
    echo "  python -m keyring set tidy gemini-api-key && bash support/infra/bootstrap.sh"
  fi
  unset KEY
fi
gcloud secrets add-iam-policy-binding gemini-api-key --project="$P" \
  --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" >/dev/null

echo "Done. Next: bash support/infra/deploy.sh"
