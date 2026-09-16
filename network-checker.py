from kubernetes import client, config

config.load_incluster_config()
v1 = client.CoreV1Api()

NAMESPACE = ""

def get_infos_of_pods():
    v1.list_namespaced_pod(namespace=NAMESPACE)