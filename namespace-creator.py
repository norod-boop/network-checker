import os

from kubernetes import dynamic, config
from kubernetes.client import api_client


def main():
    client = dynamic.DynamicClient(
        api_client.ApiClient(config.load_kube_config())
    )

    namespace_api = client.resources.get(
        api_version="v1",
        kind="Namespace"
    )

    name = os.environ["NAMESPACE_NAME"]

    namespace_api.create(
        body={
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": name
            }
        }
    )


if __name__ == "__main__":
    main()