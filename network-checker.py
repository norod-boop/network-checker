import os
import socket
from dataclasses import dataclass

from kubernetes import client, config

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

    return pods

def core_dns_check(pod: Pod):
    metrics_to_file = (
        f'network-checker{{test="core_dns_check", '
        f'node_name="{pod.node_name}", name="{pod.name}"}}'
    )
    # next-up: implementing Socket to look up the DOMAIN



def main():
    namespace = os.environ["NAMESPACE_NAME"]
    get_pod_info(namespace=namespace)
