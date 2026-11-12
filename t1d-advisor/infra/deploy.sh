#!/usr/bin/env bash
# Ship the current t1d-advisor/ code to the VM over an IAP tunnel and restart
# the service. Only code is shipped: no .env, .slack/, data/, tests or
# node_modules. Run from a Mac with gcloud after bootstrap.sh.
#
#   export T1D_GCP_PROJECT=<project id>
#   bash t1d-advisor/infra/deploy.sh
set -euo pipefail

: "${T1D_GCP_PROJECT:?set T1D_GCP_PROJECT}"
REGION="${T1D_REGION:-us-west1}"
ZONE="${T1D_ZONE:-${REGION}-b}"
VM="${T1D_VM:-t1d-advisor}"
P="$T1D_GCP_PROJECT"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
RELEASE="t1d-advisor-$(date +%Y%m%d%H%M%S)"

echo "== package release"
COPYFILE_DISABLE=1 tar -C "$ROOT" -czf "$WORK/$RELEASE.tgz" \
  --exclude='./node_modules' --exclude='./.env*' --exclude='./.slack' \
  --exclude='./data' --exclude='./logs' --exclude='./tests' --exclude='./.claude' \
  --exclude='.DS_Store' \
  .
tar -tzf "$WORK/$RELEASE.tgz" | grep -E '(^|/)(\.env|apps\.dev\.json|installations)' && {
  echo "refusing to ship: secret-bearing path in release"; exit 1; } || true

GC=(--project="$P" --zone="$ZONE" --tunnel-through-iap)

echo "== upload"
gcloud compute scp "${GC[@]}" "$WORK/$RELEASE.tgz" "$VM:/tmp/$RELEASE.tgz"

echo "== install and restart"
gcloud compute ssh "$VM" "${GC[@]}" --command="set -e
  sudo rm -rf /tmp/$RELEASE && sudo mkdir -p /tmp/$RELEASE
  sudo tar -xzf /tmp/$RELEASE.tgz -C /tmp/$RELEASE
  sudo bash /tmp/$RELEASE/infra/vm/install.sh /tmp/$RELEASE
  sudo rm -rf /tmp/$RELEASE /tmp/$RELEASE.tgz"

echo "Done. Logs: gcloud compute ssh $VM --project=\$T1D_GCP_PROJECT --zone=$ZONE --tunnel-through-iap --command='sudo journalctl -u t1d-advisor -f'"
