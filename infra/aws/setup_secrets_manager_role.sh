#!/usr/bin/env bash
# setup_secrets_manager_role.sh — one-time IAM setup so the EC2 host
# running AuditLens can read auditlens/* secrets from AWS Secrets
# Manager without baking in AWS_ACCESS_KEY_ID.
#
# Creates (idempotent):
#   1. IAM policy  AuditLensSecretsManagerPolicy  (GetSecretValue + Describe
#      on arn:aws:secretsmanager:*:*:secret:auditlens/*)
#   2. IAM role    AuditLensEC2Role               (trust: ec2.amazonaws.com)
#   3. Instance profile AuditLensEC2Profile
#
# Does NOT attach the profile to your running EC2 — prints the command
# at the end. The operator runs that step explicitly after sanity-
# checking the instance ID.
#
# Usage:
#   bash infra/aws/setup_secrets_manager_role.sh
#
# Env (optional):
#   AWS_PROFILE   AWS CLI profile name           default: confluent
#   AWS_REGION    AWS region for the policy ARN  default: ap-southeast-1
#   EC2_INSTANCE_ID  if set, the script also prints the exact
#                    associate-iam-instance-profile command for that ID.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-confluent}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
POLICY_NAME="AuditLensSecretsManagerPolicy"
ROLE_NAME="AuditLensEC2Role"
INSTANCE_PROFILE="AuditLensEC2Profile"

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

command -v aws >/dev/null 2>&1 || fail "AWS CLI not installed"

ACCOUNT_ID=$(aws sts get-caller-identity \
  --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null) \
  || fail "aws sts get-caller-identity failed — is the profile '${AWS_PROFILE}' configured?"

log "Account: ${ACCOUNT_ID}  Profile: ${AWS_PROFILE}  Region: ${AWS_REGION}"

# ---- 1. policy ------------------------------------------------------
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:auditlens/*"
    }
  ]
}
EOF
)

if aws iam get-policy --policy-arn "${POLICY_ARN}" --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
  log "policy ${POLICY_NAME} already exists — updating default version"
  aws iam create-policy-version \
    --policy-arn "${POLICY_ARN}" \
    --policy-document "${POLICY_DOC}" \
    --set-as-default \
    --profile "${AWS_PROFILE}" \
    >/dev/null
  # AWS limits to 5 non-default versions — prune oldest.
  versions=$(aws iam list-policy-versions --policy-arn "${POLICY_ARN}" --profile "${AWS_PROFILE}" \
    --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text)
  for vid in ${versions}; do
    aws iam delete-policy-version --policy-arn "${POLICY_ARN}" \
      --version-id "${vid}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 || true
    break
  done
else
  log "creating policy ${POLICY_NAME}"
  aws iam create-policy \
    --policy-name "${POLICY_NAME}" \
    --policy-document "${POLICY_DOC}" \
    --profile "${AWS_PROFILE}" \
    >/dev/null
fi

# ---- 2. role --------------------------------------------------------
TRUST_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)

if aws iam get-role --role-name "${ROLE_NAME}" --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
  log "role ${ROLE_NAME} already exists — leaving trust policy unchanged"
else
  log "creating role ${ROLE_NAME}"
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_DOC}" \
    --description "AuditLens read-only access to auditlens/* Secrets Manager secrets" \
    --profile "${AWS_PROFILE}" \
    >/dev/null
fi

log "attaching policy ${POLICY_NAME} to role ${ROLE_NAME}"
aws iam attach-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-arn "${POLICY_ARN}" \
  --profile "${AWS_PROFILE}" \
  >/dev/null || true

# ---- 3. instance profile -------------------------------------------
if aws iam get-instance-profile --instance-profile-name "${INSTANCE_PROFILE}" \
    --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
  log "instance profile ${INSTANCE_PROFILE} already exists"
else
  log "creating instance profile ${INSTANCE_PROFILE}"
  aws iam create-instance-profile \
    --instance-profile-name "${INSTANCE_PROFILE}" \
    --profile "${AWS_PROFILE}" \
    >/dev/null
fi

# add-role-to-instance-profile is idempotent enough for a one-time setup;
# we ignore "LimitExceeded" / "EntityAlreadyExists" errors.
log "binding role ${ROLE_NAME} to instance profile ${INSTANCE_PROFILE}"
aws iam add-role-to-instance-profile \
  --instance-profile-name "${INSTANCE_PROFILE}" \
  --role-name "${ROLE_NAME}" \
  --profile "${AWS_PROFILE}" \
  >/dev/null 2>&1 || true

# ---- final --------------------------------------------------------
cat <<EOM

✅ IAM setup complete.

Next step — attach the instance profile to your running EC2:

  aws ec2 associate-iam-instance-profile \\
    --instance-id <YOUR_EC2_INSTANCE_ID> \\
    --iam-instance-profile Name=${INSTANCE_PROFILE} \\
    --profile ${AWS_PROFILE} \\
    --region ${AWS_REGION}

EOM

if [ -n "${EC2_INSTANCE_ID:-}" ]; then
  cat <<EOM
You set EC2_INSTANCE_ID=${EC2_INSTANCE_ID}. To attach immediately:

  aws ec2 associate-iam-instance-profile \\
    --instance-id ${EC2_INSTANCE_ID} \\
    --iam-instance-profile Name=${INSTANCE_PROFILE} \\
    --profile ${AWS_PROFILE} \\
    --region ${AWS_REGION}

EOM
fi
