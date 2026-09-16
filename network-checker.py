import os
from kubernetes import client, config

config.load_incluster_config()
v1 = client.CoreV1Api()

def get_pod_info(namespace: str) -> list:
    pods = []
    current_pod_ip = os.environ.get("POD_IP")
    ret = v1.list_namespaced_pod(namespace)

    for pod in ret.items:
        if pod.status.pod_ip == current_pod_ip:
            continue

        pods.append({
            "name": pod.metadata.name,
            "node_name": pod.spec.node_name,
            "ip": pod.status.pod_ip,
        })

    return pods



def main():
    namespace = os.environ["NAMESPACE_NAME"]
    get_pod_info(namespace=namespace)
