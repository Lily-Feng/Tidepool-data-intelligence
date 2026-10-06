# TideTrack Terraform starter

This starter turns the AWS and Unity Catalog foundation described in
`New-scope.md` and `docs/v1/` into two independently managed Terraform roots.
It does not upload health data, deploy application code, create a Databricks
workspace, or run a pipeline.

## Scope reconciliation

The current documents contain two valid but different milestones:

- `docs/v1/README.md` defines V1 as governed ingestion plus a read-only
  analytics dashboard and explicitly defers agents and Vector Search.
- `New-scope.md` defines V0 as SQL + Vector + Knowledge Graph + Agent.

The infrastructure below implements the shared foundation required by both.
It creates the `knowledge` and `evaluation` schemas so the newer agent scope has
a governed destination, but it does not create a Vector Search index, model
endpoint, or agent until the prerequisite tables and deployment decision exist.

## What Terraform can manage for TideTrack

| Area | Manage now | Manage later |
|---|---|---|
| AWS data boundary | Private S3 buckets, KMS key, versioning, lifecycle, TLS-only policies, bucket-level public-access blocks | Replication, Object Lock after a deletion-policy decision |
| AWS access | Optional collector role and secret container | CI/OIDC roles and a scheduled collector runtime when one is selected |
| Audit and cost | Optional CloudTrail management and S3 object data events | CloudWatch alerts, AWS Config rules, budgets, and Macie after cost and scope review |
| Event ingestion | S3 prefix boundary and IAM permissions | SQS/file events for Auto Loader after the ingestion design is selected |
| Databricks governance | Storage credential, read-only external location/volume, catalog, schemas, and initial grants | Workspace bindings beyond the current workspace, governed tags, table-level app grants |
| Databricks workloads | Provider supports SQL warehouses, jobs, pipelines, Vector Search, serving endpoints, and Apps | Define deployable workloads through Declarative Automation Bundles once code and a Databricks profile are chosen |
| Agent layer | Governed `knowledge` and `evaluation` schemas | Vector endpoint/index, UC tool functions, serving endpoint, agent permissions, evaluation monitors |

Terraform should not manage raw CGM objects, frequently changing medical
documents, Delta table contents, secret values, or one-off query results. Those
belong to the collector, Lakeflow/DABs, and a secret-management workflow.

## Layout and order

```text
infra/terraform/
  aws/          # Run first: S3, KMS, IAM, optional CloudTrail/secret
  databricks/   # Run second: IAM trust plus Unity Catalog objects
```

Keep separate state for these roots. The AWS boundary must remain recoverable
even if Databricks authentication or metastore changes fail.

## Prerequisites

Install Terraform 1.10 or newer and authenticate using short-lived AWS
credentials. On macOS:

```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform

aws configure sso --profile tidetrack-dev
aws sso login --profile tidetrack-dev
export AWS_PROFILE=tidetrack-dev
aws sts get-caller-identity
```

Do not put AWS keys, Databricks tokens, Tidepool tokens, or real data in any
Terraform file.

## 1. Try the AWS plan

```bash
cd infra/terraform/aws
cp terraform.tfvars.example terraform.tfvars
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out=tidetrack.tfplan
```

Edit `terraform.tfvars` before planning. The example defaults keep CloudTrail,
the account-wide S3 public-access block, the collector role, and the Secrets
Manager container disabled. The plan still includes two private KMS-encrypted
buckets and therefore creates AWS cost if applied.

Review the plan for the exact AWS account ID, region, bucket names, IAM actions,
and any destroy/replace action. Apply only the saved plan you reviewed:

```bash
terraform apply tidetrack.tfplan
terraform output
```

Before real private data is uploaded, enable CloudTrail data events and decide
whether account-wide S3 Block Public Access is safe for the entire account.
Account-wide blocking can affect unrelated website buckets, so the template
does not enable it automatically.

## 2. Configure Unity Catalog

This step requires a paid/trial Databricks workspace attached to a Unity
Catalog metastore and a profile whose identity can create storage credentials,
external locations, catalogs, schemas, volumes, and grants.

```bash
databricks auth profiles
databricks auth login --host https://YOUR-WORKSPACE.cloud.databricks.com \
  --profile tidetrack-private

cd ../databricks
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform validate
terraform plan -out=tidetrack-databricks.tfplan
```

Copy `private_bucket_name` and `data_kms_key_arn` from the AWS root's outputs.
Set `databricks_profile` to the profile you explicitly selected. For a first
personal trial, the optional pipeline and app principals can remain `null`.
For shared or production use, supply service-principal application IDs and a
group owner before applying.

The Databricks root performs the required credential bootstrap in one graph:

1. Create the Unity Catalog storage credential without early validation.
2. Read the credential's generated external ID.
3. Create a self-assuming AWS IAM role with that external ID.
4. Validate the role when creating the read-only external location.
5. Create the catalog, schemas, and raw external volume.

Apply only after the plan shows the intended workspace and metastore:

```bash
terraform apply tidetrack-databricks.tfplan
terraform output
```

## Remote state before real data

The starter begins with local state so it is easy to inspect. Before using real
data, create a dedicated versioned state bucket in a separate bootstrap root or
use HCP Terraform. Then copy `backend.tf.example` to `backend.tf`, fill in a
unique state key, and migrate:

```bash
terraform init -migrate-state
```

Enable S3 lock-file state locking and restrict the state bucket because state
can contain sensitive resource metadata. Do not reuse the TideTrack data bucket
as the state bucket.

## Day-2 operations

For every change:

```bash
terraform fmt -check -recursive
terraform init -lockfile=readonly
terraform validate
terraform plan -out=change.tfplan
terraform apply change.tfplan
```

Also:

- Commit `.tf` files and `.terraform.lock.hcl`; never commit state, plan files,
  credentials, `.tfvars`, or health data.
- Run a scheduled `terraform plan -detailed-exitcode` to detect drift.
- Investigate console changes with `terraform plan -refresh-only`; do not
  automatically accept unexpected drift.
- Upgrade providers deliberately with `terraform init -upgrade`, then inspect a
  full plan in a non-production environment.
- Import existing resources rather than attempting to create duplicates.
- Test anonymous S3 access, collector read/delete denial, Databricks raw read,
  and app denial from Bronze/Silver after each permission change.
- Review KMS, S3 storage, CloudTrail data-event, Databricks warehouse, and model
  costs after the first week.

The S3 buckets and KMS key use `prevent_destroy`. Cleanup therefore requires an
intentional code change and confirmation that no protected data, retained
versions, or dependent Unity Catalog object remains. `force_destroy` is not
enabled.

## Authoritative references

- [Terraform AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3)
- [Amazon S3 security practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
- [CloudTrail S3 data events](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html)
- [Databricks S3 external locations](https://docs.databricks.com/aws/en/connect/unity-catalog/cloud-storage/s3/)
- [Databricks Terraform provider](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
