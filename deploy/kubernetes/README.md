# Kubernetes deployment manifests

These manifests are templates. They are not applied automatically. Review,
populate secrets via a secret manager, then apply in the order below.

## Secrets policy — read this first

**Do not commit `secret.yaml` with real values. Do not `kubectl apply -f
secret.yaml` with real credentials in the file on a workstation.**

The included `secret.yaml` contains placeholder values only (see the comment
header in that file). Source real credentials from one of:

* **sealed-secrets** (Bitnami): encrypt the secret with the cluster's
  controller key, commit the sealed manifest, decrypt only at apply time.
* **external-secrets-operator**: store credentials in AWS Secrets Manager,
  GCP Secret Manager, HashiCorp Vault, or Azure Key Vault and use an
  `ExternalSecret` resource (the bottom of `secret.yaml` shows an example).
* **Cloud-managed pod identity**: AWS IRSA, GCP Workload Identity, or Azure
  Workload Identity for AWS / GCS / Azure access — no Kubernetes Secret
  required.

If you must commit a secret manifest at all (e.g. for cluster bootstrap),
use sealed-secrets so the committed file is ciphertext.

## Apply order

```bash
kubectl apply -f namespace.yaml
kubectl apply -f networkpolicy.yaml      # Phase 3: default-deny baseline
kubectl apply -f configmap.yaml
# kubectl apply -f secret.yaml           # use sealed-secrets / external-secrets in production
kubectl apply -f pvc.yaml
kubectl apply -f service.yaml
kubectl apply -f deployment.yaml
```

## NetworkPolicy notes

`networkpolicy.yaml` ships an opinionated default-deny baseline. You will
likely need to adjust:

* The Confluent Cloud egress CIDRs (placeholder is `0.0.0.0/0`). Replace
  with your region's CIDR list from
  [Confluent Cloud network overview](https://docs.confluent.io/cloud/current/networking/network-overview.html).
* The ingress controller namespace label
  (`kubernetes.io/metadata.name: ingress-nginx`).
* The in-cluster Postgres pod selector
  (`app.kubernetes.io/name: postgresql`).

Without `networkpolicy.yaml` applied, a compromised pod in this namespace can
reach any other pod and any public IP.

## Production checklist

- [ ] etcd encryption-at-rest is enabled on the cluster (verify with
      `kubectl get apiserver -o yaml`).
- [ ] `secret.yaml` is replaced by a sealed-secret or `ExternalSecret`.
- [ ] `networkpolicy.yaml` has Confluent Cloud CIDRs filled in.
- [ ] An admission policy (Kyverno, Gatekeeper, or PodSecurity) blocks
      Pods that mount Docker sockets or run as UID 0.
- [ ] The container image referenced in `deployment.yaml` is pinned by
      digest (not `:latest`).
- [ ] Resource requests / limits in `deployment.yaml` match the workload.
