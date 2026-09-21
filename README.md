# Kubernetes Network Checker

This project runs a network connectivity check from a Kubernetes pod. It discovers pods in a target namespace, checks Kubernetes DNS, checks TCP connectivity to the Kubernetes API, and pings each discovered pod IP.

## Current Checks

The checker writes Prometheus-compatible metrics to `/tmp/metrics.prom`:

- `network_checker{test="core_dns_check", ...}` checks resolution of `kubernetes.svc.cluster.local`.
- `network_checker{test="cluster_api_check", ...}` checks TCP connectivity to the Kubernetes API on port `443`.
- `network_checker{test="container_communication_check", ...}` pings each pod IP from the checker pod.

The metric value is `1` for success and `0` for failure. Logs are written to standard output and include discovery, check, write, and shutdown events.

## Configuration

The checker expects to run inside Kubernetes and uses in-cluster authentication. Set the namespace with:

```bash
NAMESPACE_NAME=my-namespace
```

`NAMESPACE_NAME` defaults to `default` in the Docker image. `POD_IP` should contain the checker pod's IP so it can be selected as the source pod.

## Docker

The Alpine-based image installs the Kubernetes Python client and `iputils` for the `ping` command:

```bash
docker build -t k8s-network-checker:test .
docker run --rm \
	-e NAMESPACE_NAME=my-namespace \
	k8s-network-checker:test
```

The container uses an exec-form entrypoint, allowing Docker and Kubernetes to deliver `SIGTERM` to the Python process. The checker handles that signal and exits cleanly.

## GitHub Actions

`.github/workflows/create-namespace.yml` is manually triggered with a `namespace_name` input. It creates that namespace using the Kubernetes configuration stored in the `KUBE_CONFIG_DATA` secret.

The workflow currently does not build or push the Docker image and does not deploy the checker. The namespace input therefore affects namespace creation only until a deployment workflow is added.

## Required Kubernetes Permissions

The checker needs a service account with permission to list pods in the target namespace. A restricted cluster may also require permission to use ICMP raw sockets for the `ping` check.

## TODO

- Add a Kubernetes Deployment or DaemonSet for the checker.
- Create a ServiceAccount and least-privilege Role/RoleBinding for listing pods.
- Pass the workflow's `namespace_name` input into the checker Deployment as `NAMESPACE_NAME`.
- Build and push the image to a container registry, such as GHCR.
- Add image pull configuration for private registries if needed.
- Decide how `/tmp/metrics.prom` will be exposed to Prometheus.
- Add a metrics HTTP endpoint or a shared volume plus a textfile collector.
- Run the checks repeatedly instead of only once per container start.
- Add readiness, liveness, and graceful shutdown configuration.
- Add tests for DNS failures, API failures, missing pod IPs, ping failures, and SIGTERM handling.
- Escape metric label values before writing Prometheus text format.
- Replace the hard-coded Kubernetes DNS name with a configurable value if required.
- Verify the required `NET_RAW` capability under the cluster's Pod Security settings.