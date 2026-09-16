from kubernetes import client, config

config.load_incluster_config()
v1 = client.CoreV1Api()




def coredns_check:
