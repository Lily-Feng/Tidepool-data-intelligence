#!/usr/bin/env bash
# One-time GCP setup for T1D-Advisor on the Always Free tier. Run by the owner
# from a Mac with gcloud. Identifiers come from the environment and are never
# committed.
#
#   export T1D_GCP_PROJECT=<new project id>
#   export T1D_BILLING_ACCOUNT=<billing account id>
#   bash t1d-advisor/infra/bootstrap.sh
#
# Free-tier rules this script follows (check https://cloud.google.com/free):
#   - one e2-micro VM per billing account, only in us-west1/us-central1/us-east1
#   - boot disk must be pd-standard (pd-balanced is NOT free), <= 30 GB
#   - Secret Manager: <= 6 active secret versions; destroy old ones on rotation
#   - budgets alert but do NOT stop spend
# No inbound ports are opened to the internet: SSH only via IAP.
set -euo pipefail

: "${T1D_GCP_PROJECT:?set T1D_GCP_PROJECT}"
: "${T1D_BILLING_ACCOUNT:?set T1D_BILLING_ACCOUNT}"
REGION="${T1D_REGION:-us-west1}"
ZONE="${T1D_ZONE:-${REGION}-b}"
VM="${T1D_VM:-t1d-advisor}"
P="$T1D_GCP_PROJECT"
SA_NAME=t1d-advisor-vm
SA="$SA_NAME@$P.iam.gserviceaccount.com"
IAP_RANGE=35.235.240.0/20

case "$REGION" in
  us-west1|us-central1|us-east1) ;;
  *) echo "REGION $REGION is not an Always Free e2-micro region"; exit 1 ;;
esac

echo "== project and billing"
gcloud projects describe "$P" >/dev/null 2>&1 || gcloud projects create "$P" --name="t1d-advisor"
gcloud billing projects link "$P" --billing-account="$T1D_BILLING_ACCOUNT"

echo "== budget: alerts at \$0.05, \$0.50 and \$1 (alerts do not stop spend)"
gcloud services enable billingbudgets.googleapis.com --project="$P"
if ! gcloud billing budgets list --billing-account="$T1D_BILLING_ACCOUNT" --billing-project="$P" \
     --format="value(displayName)" | grep -qx "t1d-advisor"; then
  gcloud billing budgets create --billing-account="$T1D_BILLING_ACCOUNT" --billing-project="$P" \
    --display-name="t1d-advisor" --budget-amount=1USD \
    --filter-projects="projects/$P" \
    --threshold-rule=percent=0.05 --threshold-rule=percent=0.5 --threshold-rule=percent=1.0
fi

echo "== APIs"
gcloud services enable compute.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com iap.googleapis.com oslogin.googleapis.com --project="$P"

echo "== runtime identity (no keys)"
gcloud iam service-accounts describe "$SA" --project="$P" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --project="$P" --display-name="T1D-Advisor VM runtime"

echo "== secrets (values typed at a hidden prompt, never echoed)"
ensure_secret() {
  gcloud secrets describe "$1" --project="$P" >/dev/null 2>&1 || \
    gcloud secrets create "$1" --project="$P" --replication-policy=user-managed --locations="$REGION"
  gcloud secrets add-iam-policy-binding "$1" --project="$P" \
    --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" >/dev/null
}
has_version() {
  [ -n "$(gcloud secrets versions list "$1" --project="$P" --filter=state=enabled \
           --format='value(name)' --limit=1)" ]
}

ensure_secret slack-credentials
if ! has_version slack-credentials; then
  read -rsp "Prod app Bot User OAuth Token (xoxb-...): " BOT; echo
  read -rsp "Prod app App-Level Token (xapp-...): " APPTOK; echo
  case "$BOT" in xoxb-*) ;; *) echo "bot token must start with xoxb-"; exit 1 ;; esac
  case "$APPTOK" in xapp-*) ;; *) echo "app token must start with xapp-"; exit 1 ;; esac
  printf '{"SLACK_BOT_TOKEN":"%s","SLACK_APP_TOKEN":"%s"}' "$BOT" "$APPTOK" | \
    gcloud secrets versions add slack-credentials --project="$P" --data-file=-
  unset BOT APPTOK
fi

ensure_secret gemini-api-key
if ! has_version gemini-api-key; then
  read -rsp "Gemini API key: " GK; echo
  printf '%s' "$GK" | gcloud secrets versions add gemini-api-key --project="$P" --data-file=-
  unset GK
fi

echo "== firewall: no SSH/RDP from the internet, SSH only via IAP"
for rule in default-allow-ssh default-allow-rdp; do
  if gcloud compute firewall-rules describe "$rule" --project="$P" >/dev/null 2>&1; then
    gcloud compute firewall-rules delete "$rule" --project="$P" --quiet
  fi
done
gcloud compute firewall-rules describe allow-iap-ssh --project="$P" >/dev/null 2>&1 || \
  gcloud compute firewall-rules create allow-iap-ssh --project="$P" --network=default \
    --direction=INGRESS --action=allow --rules=tcp:22 --source-ranges="$IAP_RANGE" \
    --target-tags=t1d-advisor

echo "== e2-micro VM (Always Free shape)"
gcloud compute instances describe "$VM" --zone="$ZONE" --project="$P" >/dev/null 2>&1 || \
  gcloud compute instances create "$VM" --project="$P" --zone="$ZONE" \
    --machine-type=e2-micro \
    --image-family=debian-12 --image-project=debian-cloud \
    --boot-disk-type=pd-standard --boot-disk-size=30GB \
    --service-account="$SA" --scopes=cloud-platform \
    --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
    --metadata=enable-oslogin=TRUE \
    --tags=t1d-advisor

echo "Done. Next: bash t1d-advisor/infra/deploy.sh"
