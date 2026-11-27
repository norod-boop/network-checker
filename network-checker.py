import logging
import os
import signal
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass

from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

METRICS_FILE = "/tmp/metrics.prom"
DEFAULT_DOMAIN = "kubernetes.svc.cluster.local"
DEFAULT_CHECK_INTERVAL = 60
HEALTH_PORT = 8081
shutdown_event = threading.Event()
ready_event = threading.Event()
v1 = None

@dataclass
class Pod:
    name: str
    node_name: str
    ip: str


def escape_label_value(value: str | None) -> str:
    """Escape a value for a Prometheus text-format label."""
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def metric(labels: dict[str, str]) -> str:
    rendered = ", ".join(
        f'{name}="{escape_label_value(value)}"'
        for name, value in labels.items()
    )
    return f"network_checker{{{rendered}}}"


def get_pod_info(namespace: str) -> list[Pod]:
    logger.info("Discovering pods in namespace %s", namespace)
    pods = []
    current_pod_ip = os.environ.get("POD_IP")
    if v1 is None:
        raise RuntimeError("Kubernetes client is not initialized")
    ret = v1.list_namespaced_pod(namespace)

    for pod in ret.items:
        pod_info = Pod(
            name=pod.metadata.name,
            node_name=pod.spec.node_name or "",
            ip=pod.status.pod_ip or "",
        )

        if pod.status.pod_ip == current_pod_ip:
            pods.insert(0, pod_info)
        else:
            pods.append(pod_info)

    logger.info("Discovered %d pods", len(pods))
    return pods

def core_dns_check(pod: Pod) -> str:
    metric_name = metric(
        {"test": "core_dns_check", "node_name": pod.node_name, "name": pod.name}
    )
    domain = os.environ.get("KUBERNETES_DNS_NAME", DEFAULT_DOMAIN)
    try:
        ret = socket.gethostbyname(domain)
        reachable = ret != ""
        logger.info("DNS check for %s resolved %s to %s", pod.name, domain, ret)
    except socket.gaierror:
        reachable = False
        logger.warning("DNS check for %s failed to resolve %s", pod.name, domain)

    return f"{metric_name} {int(reachable)}"

def cluster_ip_check(pod: Pod) -> str:
    metric_name = metric(
        {"test": "cluster_api_check", "node_name": pod.node_name, "name": pod.name}
    )
    host = os.environ.get("KUBERNETES_SERVICE_HOST")
    if not host:
        logger.warning("KUBERNETES_SERVICE_HOST is not set")
        return f"{metric_name} 0"

    try:
        with socket.create_connection((host, 443), timeout=3.0):
            logger.info("Cluster API check for %s succeeded", pod.name)
            return f"{metric_name} 1"
    except OSError:
        logger.warning("Cluster API check for %s failed", pod.name)
        return f"{metric_name} 0"

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
    metric_name = metric(
        {
            "test": "container_communication_check",
            "host_pod": source_pod.name,
            "target_pod": target_pod.name,
            "target_ip": target_pod.ip,
        }
    )

    if not target_pod.ip:
        logger.warning("Pod %s has no IP; ping failed", target_pod.name)
        return f"{metric_name} 0"

    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", target_pod.ip],
            capture_output=True,
            check=False,
        )
    except OSError:
        logger.exception("Unable to start ping for pod %s", target_pod.name)
        return f"{metric_name} 0"

    reachable = result.returncode == 0
    logger.info("Ping from %s to %s (%s): %s", source_pod.name, target_pod.name, target_pod.ip, reachable)
    return f"{metric_name} {int(reachable)}"


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
    temporary_file = f"{METRICS_FILE}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as metrics_file:
        metrics_file.write("\n".join(metrics))
        if metrics:
            metrics_file.write("\n")
    os.replace(temporary_file, METRICS_FILE)
    logger.info("Metrics written successfully")


def handle_shutdown(signum, frame) -> None:
    logger.info("Received signal %s; shutting down", signum)
    shutdown_event.set()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz" or (
            self.path == "/readyz" and ready_event.is_set()
        ):
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(503 if self.path == "/readyz" else 404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_check(namespace: str) -> None:
    try:
        pod_list = get_pod_info(namespace=namespace)
        write_metrics(collect_metrics(pod_list))
        ready_event.set()
    except Exception:
        logger.exception("Network check failed")


def load_kubernetes_client() -> None:
    global v1
    config.load_incluster_config()
    v1 = client.CoreV1Api()


def main():
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    logger.info("Starting network checker")
    namespace = os.environ.get("NAMESPACE_NAME", "default")
    try:
        interval = max(
            1,
            int(os.environ.get("CHECK_INTERVAL_SECONDS", DEFAULT_CHECK_INTERVAL)),
        )
    except ValueError:
        logger.warning(
            "Invalid CHECK_INTERVAL_SECONDS value; using %d seconds",
            DEFAULT_CHECK_INTERVAL,
        )
        interval = DEFAULT_CHECK_INTERVAL
    load_kubernetes_client()
    server = start_health_server()
    try:
        while not shutdown_event.is_set():
            run_check(namespace)
            shutdown_event.wait(interval)
    finally:
        server.shutdown()
        server.server_close()
        logger.info("Network checker finished")


if __name__ == "__main__":
    main()


