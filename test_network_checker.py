import importlib.util
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "network_checker",
    Path(__file__).with_name("network-checker.py"),
)
assert spec is not None
assert spec.loader is not None
network_checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network_checker)


class NetworkCheckerTests(unittest.TestCase):
    def test_escape_label_value(self):
        self.assertEqual(
            network_checker.escape_label_value('pod\\name"\nline'),
            'pod\\\\name\\"\\nline',
        )

    def test_cluster_ip_check_without_host(self):
        pod = network_checker.Pod("pod-a", "node-a", "10.0.0.1")
        with patch.dict(network_checker.os.environ, {}, clear=True):
            result = network_checker.cluster_ip_check(pod)
        self.assertIn('test="cluster_api_check"', result)
        self.assertTrue(result.endswith(" 0"))

    def test_ping_pod_without_ip(self):
        source = network_checker.Pod("pod-a", "node-a", "10.0.0.1")
        target = network_checker.Pod("pod-b", "node-b", "")
        result = network_checker._ping_pod(source, target)
        self.assertIn('target_pod="pod-b"', result)
        self.assertTrue(result.endswith(" 0"))

    def test_write_metrics_replaces_file(self):
        with tempfile.TemporaryDirectory() as directory:
            setattr(
                network_checker,
                "METRICS_FILE",
                str(Path(directory) / "metrics.prom"),
            )
            network_checker.write_metrics(["metric 1", "metric 2"])
            self.assertEqual(
                Path(network_checker.METRICS_FILE).read_text(encoding="utf-8"),
                "metric 1\nmetric 2\n",
            )

    def test_load_kubernetes_client_uses_incluster_config(self):
        with patch.object(
            network_checker.config,
            "load_incluster_config",
        ) as in_cluster, patch.object(network_checker.client, "CoreV1Api"):
            network_checker.load_kubernetes_client()
        in_cluster.assert_called_once_with()

    def test_health_server_does_not_expose_metrics(self):
        network_checker.ready_event.clear()
        server = network_checker.start_health_server()
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8081/healthz",
                timeout=2,
            ) as response:
                self.assertEqual(response.status, 200)
            with urllib.request.urlopen(
                "http://127.0.0.1:8081/metrics",
                timeout=2,
            ):
                self.fail("The health server unexpectedly exposed metrics")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
