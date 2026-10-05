# Kubernetes Network Checker

This project runs a network connectivity check from a Kubernetes pod. It discovers pods in a target namespace, checks Kubernetes DNS, checks TCP connectivity to the Kubernetes API, and pings each discovered pod IP.

## Current Checks

The checker writes Prometheus-compatible metrics to `/tmp/metrics.prom`:

- `network_checker{test="core_dns_check", ...}` checks resolution of `kubernetes.svc.cluster.local`.
- `network_checker{test="cluster_api_check", ...}` checks TCP connectivity to the Kubernetes API on port `443`.
- `network_checker{test="container_communication_check", ...}` pings each pod IP from the checker pod.

The metric value is `1` for success and `0` for failure. Logs are written to standard output and include discovery, check, write, and shutdown events. Checks repeat every 60 seconds by default.

## Configuration

The checker expects to run inside Kubernetes and uses in-cluster authentication. Set the namespace with:

```bash
NAMESPACE_NAME=my-namespace
```

`NAMESPACE_NAME` defaults to `default` in the Docker image. `POD_IP` should contain the checker pod's IP so it can be selected as the source pod.

Optional environment variables are `CHECK_INTERVAL_SECONDS` and `KUBERNETES_DNS_NAME`. The latter defaults to `kubernetes.svc.cluster.local`.

## Docker

The Alpine-based image installs the Kubernetes Python client and `iputils` for the `ping` command:

```bash
docker build -t k8s-network-checker:test .
docker run --rm \
	-e NAMESPACE_NAME=my-namespace \
	k8s-network-checker:test
```

The container uses an exec-form entrypoint, allowing Docker and Kubernetes to deliver `SIGTERM` to the Python process. The checker handles that signal and exits cleanly.

## Kubernetes Deployment

`k8s/` is a Kustomize application defining the Deployment, ServiceAccount, least-privilege Role/RoleBinding, Service, and metrics sidecar. Set the repository owner and image tag in `k8s/kustomization.yaml`, then apply it with:

```bash
kubectl apply -k k8s/
```

The committed Kustomize namespace is `network-checker`. Change `namespace` in `k8s/kustomization.yaml` and the `destination.namespace` in `argocd/application.yaml` together when using another namespace. The checker receives its actual namespace from the Kubernetes downward API.

The checker and an NGINX sidecar share an `emptyDir` volume. The checker atomically writes `/tmp/metrics.prom`; NGINX serves the same file at `/metrics.prom` on port `8080`, which the Service exposes for Prometheus. The checker health and readiness endpoints use port `8081`.

For a private image, set `imagePullSecrets` in the manifest to an existing registry secret. The deployment adds `NET_RAW` because the ping check needs ICMP raw sockets; clusters enforcing restricted Pod Security must explicitly allow this capability for the namespace or workload.

## GitHub Actions

`.github/workflows/create-namespace.yml` is manually triggered with a `namespace_name` input. It creates that namespace using the Kubernetes configuration stored in the `KUBE_CONFIG_DATA` secret.

The namespace creation workflow is separate from deployment. Argo CD should be used for continuous synchronization.

## Argo CD

For a private GitHub repository, add repository credentials to Argo CD using the Argo CD UI or CLI. Do not commit the token:

```bash
argocd repo add https://github.com/OWNER/k8s-network-checker.git \
	--username YOUR_GITHUB_USERNAME \
	--password YOUR_GITHUB_TOKEN
```

Replace `REPLACE_ME` in `argocd/application.yaml` and `k8s/kustomization.yaml`, commit the changes, and apply the Application from a machine with access to the Argo CD cluster:

```bash
kubectl apply -f argocd/application.yaml
```

The Application uses `CreateNamespace=true`, syncs the `k8s` directory, and enables pruning and self-healing. For a private container image, create an image pull secret in the target namespace and add its name under `spec.template.spec.imagePullSecrets` in `k8s/checker.yaml` (or manage that patch with a Kustomize overlay).

## Required Kubernetes Permissions

The checker needs a service account with permission to list pods in the target namespace. A restricted cluster may also require permission to use ICMP raw sockets for the `ping` check.

## Operational Notes

Metric label values are escaped for Prometheus text format. SIGTERM stops the check loop and shuts down the health server cleanly. Prometheus must be configured to discover the `network-checker` Service, or the annotations can be used with a Prometheus installation that supports annotation-based scraping.