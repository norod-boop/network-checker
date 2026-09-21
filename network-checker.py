import logging
import os
import signal
import socket
import subprocess
from dataclasses import dataclass

from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

config.load_incluster_config()
v1 = client.CoreV1Api()

METRICS_FILE = "/tmp/metrics.prom"
DOMAIN = "kubernetes.svc.cluster.local"

@dataclass
class Pod:
    name: str
    node_name: str
    ip: str


def get_pod_info(namespace: str) -> list[Pod]:
    logger.info("Discovering pods in namespace %s", namespace)
    pods = []
    current_pod_ip = os.environ.get("POD_IP")
    ret = v1.list_namespaced_pod(namespace)

    for pod in ret.items:
        pod_info = Pod(
            name=pod.metadata.name,
            node_name=pod.spec.node_name,
            ip=pod.status.pod_ip,
        )

        if pod.status.pod_ip == current_pod_ip:
            pods.insert(0, pod_info)
        else:
            pods.append(pod_info)

    logger.info("Discovered %d pods", len(pods))
    return pods

def core_dns_check(pod: Pod) -> str:
    metric = (
        f'network_checker{{test="core_dns_check", '
        f'node_name="{pod.node_name}", name="{pod.name}"}}'
    )
    try:
        ret = socket.gethostbyname(DOMAIN)
        reachable = ret != ""
        logger.info("DNS check for %s resolved %s to %s", pod.name, DOMAIN, ret)
    except socket.gaierror:
        reachable = False
        logger.warning("DNS check for %s failed to resolve %s", pod.name, DOMAIN)

    return f"{metric} {int(reachable)}"

def cluster_ip_check(pod: Pod) -> str:
    metric = (
        f'network_checker{{test="cluster_api_check", '
        f'node_name="{pod.node_name}", name="{pod.name}"}}'
    )
    host = os.environ.get("KUBERNETES_SERVICE_HOST")
    if not host:
        logger.warning("KUBERNETES_SERVICE_HOST is not set")
        return f"{metric} 0"

    try:
        with socket.create_connection((host, 443), timeout=3.0):
            logger.info("Cluster API check for %s succeeded", pod.name)
            return f"{metric} 1"
    except OSError:
        logger.warning("Cluster API check for %s failed", pod.name)
        return f"{metric} 0"

def container_communication_check(pod_list: list[Pod]) -> list[str]:
    if not pod_list:
        logger.warning("No pods available for container communication checks")
        return []

    host_pod = pod_list[0]
    logger.info("Pinging %d pods from host pod %s", len(pod_list), host_pod.name)
    metrics = []
    for target_pod in pod_list:
        metrics.append(_ping_pod(host_pod, target_pod))

    return metrics


def _ping_pod(source_pod: Pod, target_pod: Pod) -> str:
    metric = (
        f'network_checker{{test="container_communication_check", '
        f'host_pod="{source_pod.name}", target_pod="{target_pod.name}", '
        f'target_ip="{target_pod.ip}"}}'
    )

    if not target_pod.ip:
        logger.warning("Pod %s has no IP; ping failed", target_pod.name)
        return f"{metric} 0"

    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", target_pod.ip],
            capture_output=True,
            check=False,
        )
    except OSError:
        logger.exception("Unable to start ping for pod %s", target_pod.name)
        return f"{metric} 0"

    reachable = result.returncode == 0
    logger.info("Ping from %s to %s (%s): %s", source_pod.name, target_pod.name, target_pod.ip, reachable)
    return f"{metric} {int(reachable)}"


def collect_metrics(pod_list: list[Pod]) -> list[str]:
    logger.info("Collecting DNS and cluster API metrics")
    metrics = []
    for pod in pod_list:
        metrics.append(core_dns_check(pod))
        metrics.append(cluster_ip_check(pod))

    metrics.extend(container_communication_check(pod_list))
    logger.info("Collected %d metrics", len(metrics))
    return metrics


def write_metrics(metrics: list[str]) -> None:
    logger.info("Writing %d metrics to %s", len(metrics), METRICS_FILE)
    with open(METRICS_FILE, "w", encoding="utf-8") as metrics_file:
        metrics_file.write("\n".join(metrics))
        if metrics:
            metrics_file.write("\n")
    logger.info("Metrics written successfully")


def handle_shutdown(signum, frame) -> None:
    logger.info("Received signal %s; shutting down", signum)
    raise SystemExit(0)


def main():
    signal.signal(signal.SIGTERM, handle_shutdown)
    logger.info("Starting network checker")
    namespace = os.environ["NAMESPACE_NAME"]
    pod_list = get_pod_info(namespace=namespace)
    metrics = collect_metrics(pod_list)
    write_metrics(metrics)
    logger.info("Network checker finished")


if __name__ == "__main__":
    main()


