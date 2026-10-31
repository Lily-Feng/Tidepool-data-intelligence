#!/usr/bin/env bash
# Build and deploy the Tidy service to a private Cloud Run service.
# Builds with support/ as the only upload context, so nothing else in the repo
# (private/ in particular) leaves your machine.
#
#   export TIDY_GCP_PROJECT=<project id>
#   bash support/infra/deploy.sh
set -euo pipefail

: "${TIDY_GCP_PROJECT:?set TIDY_GCP_PROJECT}"
REGION="${TIDY_REGION:-us-west1}"
P="$TIDY_GCP_PROJECT"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SHA="$(git -C "$ROOT" rev-parse --short HEAD)"
IMAGE="$REGION-docker.pkg.dev/$P/tidy/tidy-app:$SHA"

gcloud builds submit "$ROOT/support" --project="$P" --region="$REGION" --tag="$IMAGE"

gcloud run deploy tidy-app --project="$P" --region="$REGION" --image="$IMAGE" \
  --service-account="tidy-app@$P.iam.gserviceaccount.com" \
  --no-allow-unauthenticated --ingress=all \
  --max-instances=2 --concurrency=20 --cpu=1 --memory=512Mi \
  --set-env-vars="TIDY_TARGET=gcp-dev,TIDY_GCP_PROJECT=$P,GIT_SHA=$SHA"

URL="$(gcloud run services describe tidy-app --project="$P" --region="$REGION" --format='value(status.url)')"
TOKEN="$(gcloud auth print-identity-token)"
echo "== /health";  curl -sf -H "Authorization: Bearer $TOKEN" "$URL/health"; echo
echo "== /ready";   curl -s  -H "Authorization: Bearer $TOKEN" "$URL/ready"; echo
echo "== unauthenticated call must be refused (expect 403)"
curl -s -o /dev/null -w "%{http_code}\n" "$URL/health"
