from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from observeweaver.config import load_config, validate_config
from observeweaver.render import DOCKER_IMAGE_LOCKS, DOCKER_IMAGE_TAGS, render
from observeweaver.secrets import generate_secret_values, write_secret_file

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def load_example(self, name: str) -> dict:
        return load_config(ROOT / "config" / "examples" / name)

    def test_standalone_example_is_valid(self) -> None:
        result = validate_config(self.load_example("standalone.yml"))
        self.assertEqual([], result.errors)
        self.assertTrue(result.warnings)

    def test_cluster_example_is_valid(self) -> None:
        result = validate_config(self.load_example("cluster.yml"))
        self.assertEqual([], result.errors)

    def test_windows_native_example_is_valid(self) -> None:
        result = validate_config(self.load_example("windows-native.yml"))
        self.assertEqual([], result.errors)

    def test_raw_standalone_example_is_valid(self) -> None:
        result = validate_config(self.load_example("raw-standalone.yml"))
        self.assertEqual([], result.errors)

    def test_k3s_standalone_example_is_valid(self) -> None:
        result = validate_config(self.load_example("k3s-standalone.yml"))
        self.assertEqual([], result.errors)

    def test_docker_cluster_example_is_valid(self) -> None:
        result = validate_config(self.load_example("docker-cluster.yml"))
        self.assertEqual([], result.errors)
        self.assertTrue(
            any(
                "plaintext, unauthenticated east-west" in warning
                for warning in result.warnings
            )
        )

    def test_cluster_requires_three_nodes(self) -> None:
        config = self.load_example("cluster.yml")
        config["nodes"] = config["nodes"][:2]
        result = validate_config(config)
        self.assertTrue(any("at least three" in error for error in result.errors))

    def test_graylog_native_windows_is_rejected(self) -> None:
        config = self.load_example("windows-native.yml")
        config["components"]["graylog"]["enabled"] = True
        result = validate_config(config)
        self.assertTrue(any("no supported native Windows" in error for error in result.errors))

    def test_zabbix_uses_the_lts_pin(self) -> None:
        config = self.load_example("standalone.yml")
        config["components"]["zabbix"]["version"] = "7.4.1"
        result = validate_config(config)
        self.assertTrue(any("tested pinset (7.0.28)" in error for error in result.errors))

    def test_zabbix_ha_requires_an_external_database(self) -> None:
        config = self.load_example("cluster.yml")
        config["dependencies"]["zabbixPostgresql"]["external"] = False
        result = validate_config(config)
        self.assertTrue(any("Zabbix HA requires" in error for error in result.errors))

    def test_raw_zabbix_requires_an_external_database(self) -> None:
        config = self.load_example("raw-standalone.yml")
        config["dependencies"]["zabbixPostgresql"]["external"] = False
        result = validate_config(config)
        self.assertTrue(any("Native Zabbix uses" in error for error in result.errors))

    def test_new_linux_platform_versions_are_accepted(self) -> None:
        for distribution, version in (
            ("ubuntu", "26.04"),
            ("rocky", "10"),
            ("almalinux", "10"),
            ("rhel", "10"),
        ):
            with self.subTest(distribution=distribution):
                config = self.load_example("raw-standalone.yml")
                config["platform"]["distribution"] = distribution
                config["platform"]["version"] = version
                config["dependencies"]["mongodb"]["external"] = True
                result = validate_config(config)
                self.assertEqual([], result.errors)

    def test_raw_graylog_on_newer_linux_releases_requires_external_mongodb(self) -> None:
        for distribution, version in (
            ("ubuntu", "26.04"),
            ("rocky", "10"),
            ("almalinux", "10"),
            ("rhel", "10"),
        ):
            with self.subTest(distribution=distribution):
                config = self.load_example("raw-standalone.yml")
                config["platform"]["distribution"] = distribution
                config["platform"]["version"] = version
                result = validate_config(config)
                self.assertTrue(
                    any(
                        "requires dependencies.mongodb.external=true" in error
                        for error in result.errors
                    )
                )

    def test_latest_tag_is_rejected(self) -> None:
        config = self.load_example("standalone.yml")
        config["components"]["grafana"]["version"] = "latest"
        result = validate_config(config)
        self.assertTrue(any("'latest'" in error for error in result.errors))

    def test_duplicate_nodes_are_rejected(self) -> None:
        config = self.load_example("cluster.yml")
        duplicate = copy.deepcopy(config["nodes"][0])
        config["nodes"][1] = duplicate
        result = validate_config(config)
        self.assertTrue(any("duplicate node name" in error for error in result.errors))
        self.assertTrue(any("duplicate address" in error for error in result.errors))

    def test_invalid_replicas_are_rejected_without_crashing(self) -> None:
        config = self.load_example("raw-cluster.yml")
        config["components"]["prometheus"]["replicas"] = "three"
        result = validate_config(config)
        self.assertTrue(
            any("replicas: must be a positive integer" in error for error in result.errors)
        )

        config["components"]["prometheus"]["replicas"] = 0
        result = validate_config(config)
        self.assertTrue(
            any("replicas: must be a positive integer" in error for error in result.errors)
        )

    def test_unsafe_render_names_are_rejected(self) -> None:
        config = self.load_example("standalone.yml")
        config["metadata"]["environment"] = "../../escape"
        config["nodes"][0]["name"] = "../node"
        result = validate_config(config)
        self.assertTrue(any("safe name" in error for error in result.errors))
        self.assertTrue(any("DNS label" in error for error in result.errors))

    def test_domain_must_not_be_an_ip_address(self) -> None:
        config = self.load_example("standalone.yml")
        config["network"]["domain"] = "192.0.2.50"
        result = validate_config(config)
        self.assertTrue(any("valid DNS name" in error for error in result.errors))

    def test_graylog_requires_opensearch(self) -> None:
        config = self.load_example("raw-cluster.yml")
        config["components"]["opensearch"]["enabled"] = False
        result = validate_config(config)
        self.assertTrue(
            any("must be true when Graylog is enabled" in error for error in result.errors)
        )

    def test_native_windows_cluster_is_rejected(self) -> None:
        config = self.load_example("windows-native.yml")
        config["deployment"]["mode"] = "cluster"
        result = validate_config(config)
        self.assertTrue(
            any("Native Windows supports standalone" in error for error in result.errors)
        )

    def test_kubernetes_locked_internal_ports_are_enforced(self) -> None:
        config = self.load_example("cluster.yml")
        config["network"]["ports"]["alertmanagerCluster"] = 19094
        config["network"]["ports"]["mongodb"] = 37017
        result = validate_config(config)
        self.assertTrue(
            any("network.ports.alertmanagerCluster" in error for error in result.errors)
        )
        self.assertTrue(any("network.ports.mongodb" in error for error in result.errors))

    def test_docker_cluster_grafana_requires_external_postgres(self) -> None:
        config = self.load_example("docker-cluster.yml")
        config["components"]["grafana"]["replicas"] = 1
        config["dependencies"]["postgresql"]["external"] = False
        result = validate_config(config)
        self.assertTrue(
            any("Docker cluster Grafana" in error for error in result.errors)
        )

    def test_disabled_grafana_does_not_require_external_postgres(self) -> None:
        for example in ("cluster.yml", "docker-cluster.yml", "raw-cluster.yml"):
            with self.subTest(example=example):
                config = self.load_example(example)
                config["components"]["grafana"]["enabled"] = False
                config["dependencies"]["postgresql"]["external"] = False
                result = validate_config(config)
                self.assertFalse(
                    any("Grafana" in error for error in result.errors),
                    result.errors,
                )

    def test_unknown_configuration_keys_are_rejected(self) -> None:
        config = self.load_example("standalone.yml")
        config["totallyUnknown"] = True
        config["components"]["prometheus"]["enabeld"] = True
        result = validate_config(config)
        self.assertTrue(any("totallyUnknown" in error for error in result.errors))
        self.assertTrue(any("enabeld" in error for error in result.errors))

    def test_node_and_bind_addresses_must_be_ip_literals(self) -> None:
        config = self.load_example("docker-cluster.yml")
        config["nodes"][0]["address"] = "obs-01.example.com"
        config["network"]["bindAddress"] = "bind.example.com"
        result = validate_config(config)
        self.assertTrue(any("nodes[0].address" in error for error in result.errors))
        self.assertTrue(any("network.bindAddress" in error for error in result.errors))

    def test_udp_port_collisions_are_rejected(self) -> None:
        config = self.load_example("docker-cluster.yml")
        config["network"]["ports"]["graylogGelfUdp"] = config["network"]["ports"][
            "alertmanagerCluster"
        ]
        result = validate_config(config)
        self.assertTrue(any("UDP port" in error for error in result.errors))

    def test_raw_standalone_requires_component_roles(self) -> None:
        config = self.load_example("standalone.yml")
        config["deployment"]["engine"] = "raw"
        config["platform"]["execution"] = "native"
        config["nodes"][0]["roles"] = ["control"]
        result = validate_config(config)
        self.assertTrue(any("assigned role" in error for error in result.errors))

    def test_all_examples_parse_as_yaml(self) -> None:
        for path in (ROOT / "config" / "examples").glob("*.yml"):
            with self.subTest(path=path):
                self.assertIsInstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict)

    def test_all_examples_match_json_schema(self) -> None:
        schema = json.loads(
            (
                ROOT / "schema" / "observeweaver-v1alpha1.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for path in (ROOT / "config" / "examples").glob("*.yml"):
            with self.subTest(path=path):
                errors = sorted(
                    validator.iter_errors(
                        yaml.safe_load(path.read_text(encoding="utf-8"))
                    ),
                    key=lambda error: list(error.path),
                )
                self.assertEqual([], errors)


class RenderTests(unittest.TestCase):
    def test_render_creates_secret_free_outputs(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "standalone.yml")
        with tempfile.TemporaryDirectory() as directory:
            created = render(config, directory)
            self.assertEqual(13, len(created))
            combined = "\n".join(path.read_text(encoding="utf-8") for path in created)
            self.assertNotIn("GRAFANA_ADMIN_PASSWORD=", combined)
            self.assertIn("PROMETHEUS_VERSION=3.13.1", combined)
            self.assertIn(
                "COMPOSE_PROFILES=prometheus,alertmanager,grafana,"
                "opentelemetry,zabbix,graylog,opensearch,mongodb",
                combined,
            )

    def test_docker_standalone_renders_zabbix_profile(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "standalone.yml")
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            environment = (
                Path(directory) / "production" / "docker" / ".env.generated"
            ).read_text(encoding="utf-8")
            self.assertIn("ZABBIX_VERSION=7.0.28", environment)
            self.assertIn("ZABBIX_SERVER_PORT=10051", environment)
            self.assertIn("ZABBIX_WEB_PORT=8080", environment)
            self.assertIn(
                "ZABBIX_SERVER_IMAGE="
                "zabbix/zabbix-server-pgsql@sha256:",
                environment,
            )
            self.assertIn("COMPOSE_PROFILES=", environment)
            self.assertIn("zabbix", environment)

    def test_docker_image_locks_are_immutable_and_match_the_lockfile(self) -> None:
        lockfile = yaml.safe_load(
            (ROOT / "versions" / "stable.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(lockfile["containerImages"], DOCKER_IMAGE_LOCKS)
        self.assertEqual(set(DOCKER_IMAGE_TAGS), set(DOCKER_IMAGE_LOCKS))
        self.assertEqual(10, len(DOCKER_IMAGE_LOCKS))
        for name, image in DOCKER_IMAGE_LOCKS.items():
            repository, digest = image.split("@", 1)
            self.assertTrue(repository)
            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(repository, DOCKER_IMAGE_TAGS[name].rsplit(":", 1)[0])

        for compose_name in ("compose.yml", "compose.cluster-node.yml"):
            compose = (
                ROOT / "deployments" / "docker" / compose_name
            ).read_text(encoding="utf-8")
            self.assertNotIn("_VERSION", compose)
            self.assertRegex(compose, r"image: \$\{[A-Z_]+_IMAGE:\?[^}]+}")

    def test_kubernetes_image_post_renderer_is_digest_only_and_fail_closed(self) -> None:
        lockfile = yaml.safe_load(
            (ROOT / "versions" / "kubernetes-images.lock.yml").read_text(
                encoding="utf-8"
            )
        )
        locks = lockfile["chartImages"]
        self.assertEqual(24, len(locks))
        self.assertIn("postgres:17", locks)
        for image in locks.values():
            self.assertRegex(image, r"^[^@]+@sha256:[0-9a-f]{64}$")

        script = ROOT / "scripts" / "pin_kubernetes_images.py"
        known = subprocess.run(
            [sys.executable, str(script)],
            input="        image: \"mongo:8.0.28\"\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, known.returncode, known.stderr)
        self.assertIn(locks["mongo:8.0.28"], known.stdout)

        unknown = subprocess.run(
            [sys.executable, str(script)],
            input="        image: example.invalid/unlocked:1.0\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, unknown.returncode)
        self.assertIn("unpinned Kubernetes chart image", unknown.stderr)

    def test_standalone_render_honors_component_selection(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "standalone.yml")
        config["components"]["alertmanager"]["enabled"] = False
        config["components"]["grafana"]["enabled"] = False
        config["components"]["zabbix"]["enabled"] = False
        config["components"]["graylog"]["enabled"] = False
        config["components"]["opensearch"]["enabled"] = False
        self.assertEqual([], validate_config(config).errors)
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            docker_root = Path(directory) / "production" / "docker"
            environment = (docker_root / ".env.generated").read_text(encoding="utf-8")
            prometheus = (docker_root / "configs" / "prometheus.yml").read_text(
                encoding="utf-8"
            )
            datasources = yaml.safe_load(
                (docker_root / "configs" / "grafana-datasources.yml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("COMPOSE_PROFILES=prometheus,opentelemetry", environment)
            self.assertNotIn("job_name: alertmanager", prometheus)
            self.assertNotIn("job_name: grafana", prometheus)
            self.assertEqual("Prometheus", datasources["datasources"][0]["name"])

        config["components"]["prometheus"]["enabled"] = False
        config["components"]["grafana"]["enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            docker_root = Path(directory) / "production" / "docker"
            datasources = yaml.safe_load(
                (docker_root / "configs" / "grafana-datasources.yml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual([], datasources["datasources"])

    def test_raw_inventory_omits_disabled_components(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "raw-cluster.yml")
        config["components"]["opentelemetry"]["enabled"] = False
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            inventory = (
                Path(directory)
                / "production"
                / "ansible"
                / "inventory.generated.ini"
            ).read_text(encoding="utf-8")
            telemetry_group = inventory.split("[opentelemetry]\n", 1)[1].split(
                "\n[", 1
            )[0]
            self.assertEqual("", telemetry_group)

    def test_raw_group_vars_include_declared_platform(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "raw-cluster.yml")
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            group_vars = yaml.safe_load(
                (
                    Path(directory)
                    / "production"
                    / "ansible"
                    / "group_vars.generated.yml"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(config["platform"], group_vars["observeweaver"]["platform"])

    def test_enterprise_linux_8_raw_is_rejected(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "raw-cluster.yml")
        config["platform"]["version"] = "8"
        result = validate_config(config)
        self.assertTrue(any("Enterprise Linux 8" in error for error in result.errors))

    def test_docker_cluster_brackets_ipv6_endpoints(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "docker-cluster.yml")
        for index, node in enumerate(config["nodes"], 1):
            node["address"] = f"2001:db8::{index}"
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            node_root = (
                Path(directory) / "production" / "docker" / "nodes" / "obs-01"
            )
            environment = (node_root / ".env.generated").read_text(encoding="utf-8")
            prometheus = (node_root / "prometheus.yml").read_text(encoding="utf-8")
            self.assertIn("NODE_ENDPOINT_ADDRESS=[2001:db8::1]", environment)
            self.assertIn("[2001:db8::1]:9090", prometheus)

    def test_docker_cluster_render_creates_per_node_bundles(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "docker-cluster.yml")
        with tempfile.TemporaryDirectory() as directory:
            created = render(config, directory)
            for node in ("obs-01", "obs-02", "obs-03"):
                root = Path(directory) / "production" / "docker" / "nodes" / node
                self.assertTrue((root / ".env.generated").is_file())
                self.assertTrue((root / "compose.override.generated.yml").is_file())
            combined = "\n".join(path.read_text(encoding="utf-8") for path in created)
            self.assertNotIn("actual-password", combined)
            self.assertIn("${MONGODB_ROOT_PASSWORD}", combined)
            self.assertIn("otel-exported-metrics", combined)
            self.assertIn("GRAYLOG_SYSLOG_UDP_PORT=1514", combined)
            self.assertNotIn("ZABBIX_DATABASE_HOST=", combined)
            for node in ("obs-01", "obs-02", "obs-03"):
                environment = (
                    Path(directory)
                    / "production"
                    / "docker"
                    / "nodes"
                    / node
                    / ".env.generated"
                ).read_text(encoding="utf-8")
                self.assertIn("zabbix", environment)
                self.assertNotIn("zabbix-postgresql", environment)

    def test_cluster_graylog_uses_automatic_leader_election(self) -> None:
        raw_template = (
            ROOT
            / "deployments"
            / "raw"
            / "ansible"
            / "roles"
            / "observeweaver"
            / "templates"
            / "graylog-server.conf.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("leader_election_mode = automatic", raw_template)

        compose = yaml.safe_load(
            (
                ROOT / "deployments" / "docker" / "compose.cluster-node.yml"
            ).read_text(encoding="utf-8")
        )
        graylog_environment = compose["services"]["graylog"]["environment"]
        self.assertEqual(
            "automatic",
            graylog_environment["GRAYLOG_LEADER_ELECTION_MODE"],
        )
        self.assertNotIn("GRAYLOG_IS_LEADER", graylog_environment)
        self.assertNotIn(
            "GRAYLOG_ELASTICSEARCH_SSL_VERIFICATION_ENABLED",
            graylog_environment,
        )
        opensearch_environment = compose["services"]["opensearch"]["environment"]
        self.assertEqual("true", opensearch_environment["DISABLE_SECURITY_PLUGIN"])
        self.assertEqual(
            "true",
            opensearch_environment["DISABLE_INSTALL_DEMO_CONFIG"],
        )
        self.assertNotIn(
            "OPENSEARCH_INITIAL_ADMIN_PASSWORD",
            opensearch_environment,
        )

    def test_zabbix_is_covered_by_deployment_verification(self) -> None:
        docker_verifier = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
        deploy_script = (ROOT / "scripts" / "observeweaver.sh").read_text(
            encoding="utf-8"
        )
        raw_verifier = (
            ROOT / "deployments" / "raw" / "ansible" / "playbooks" / "verify.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('"zabbix": "metrics"', docker_verifier)
        self.assertIn("checks[zabbix-web]", docker_verifier)
        self.assertIn("PASS  zabbix-server", docker_verifier)
        self.assertIn("ZABBIX_DATABASE_HOST", deploy_script)
        self.assertIn("Check Zabbix Server listener", raw_verifier)

        config = load_config(ROOT / "config" / "examples" / "docker-cluster.yml")
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            for node in ("obs-01", "obs-02", "obs-03"):
                override = yaml.safe_load(
                    (
                        Path(directory)
                        / "production"
                        / "docker"
                        / "nodes"
                        / node
                        / "compose.override.generated.yml"
                    ).read_text(encoding="utf-8")
                )
                self.assertNotIn(
                    "GRAYLOG_IS_LEADER",
                    override["services"]["graylog"]["environment"],
                )
                self.assertEqual(
                    "http://obs-01:9200,http://obs-02:9200,http://obs-03:9200",
                    override["services"]["graylog"]["environment"][
                        "GRAYLOG_ELASTICSEARCH_HOSTS"
                    ],
                )

    def test_raw_zabbix_uses_the_locked_lts_packages(self) -> None:
        raw_tasks = (
            ROOT
            / "deployments"
            / "raw"
            / "ansible"
            / "roles"
            / "observeweaver"
            / "tasks"
            / "zabbix.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("https://repo.zabbix.com/zabbix/7.0/ubuntu", raw_tasks)
        self.assertNotIn("zabbix/7.0/stable/ubuntu", raw_tasks)
        self.assertIn("observeweaver_zabbix_deb_package_version", raw_tasks)
        self.assertIn("observeweaver_zabbix_rpm_package_version", raw_tasks)
        self.assertIn(
            "zabbix-server-pgsql={{ observeweaver_zabbix_deb_package_version }}",
            raw_tasks,
        )
        self.assertIn(
            "zabbix-server-pgsql-{{ observeweaver_zabbix_rpm_package_version }}",
            raw_tasks,
        )
        self.assertIn("Confirm the pinned Zabbix server version", raw_tasks)

    def test_raw_inventory_honors_component_replica_counts(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "raw-cluster.yml")
        config["components"]["prometheus"]["replicas"] = 2
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            inventory = (
                Path(directory)
                / "production"
                / "ansible"
                / "inventory.generated.ini"
            ).read_text(encoding="utf-8")
            prometheus_group = inventory.split("[prometheus]\n", 1)[1].split(
                "\n[", 1
            )[0]
            self.assertIn("obs-01", prometheus_group)
            self.assertIn("obs-02", prometheus_group)
            self.assertNotIn("obs-03", prometheus_group)

    def test_kubernetes_values_wire_editable_telemetry_ports(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "cluster.yml")
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            values = yaml.safe_load(
                (
                    Path(directory)
                    / "production"
                    / "kubernetes"
                    / "opentelemetry-collector.values.generated.yml"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(8889, values["ports"]["metrics"]["servicePort"])
            self.assertEqual(
                8888, values["ports"]["internal-metrics"]["servicePort"]
            )
            self.assertTrue(values["serviceMonitor"]["enabled"])
            for receiver in ("jaeger", "zipkin"):
                self.assertIsNone(values["config"]["receivers"][receiver])
            for port in (
                "jaeger-compact",
                "jaeger-thrift",
                "jaeger-grpc",
                "zipkin",
            ):
                self.assertFalse(values["ports"][port]["enabled"])
            graylog_values = yaml.safe_load(
                (
                    Path(directory)
                    / "production"
                    / "kubernetes"
                    / "graylog.values.generated.yml"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                "0.0.0.0:9000",
                graylog_values["graylog"]["env"]["GRAYLOG_HTTP_BIND_ADDRESS"],
            )
            self.assertEqual(
                "https://graylog.observability.example.com/",
                graylog_values["graylog"]["config"]["email"]["webInterfaceUrl"],
            )
            self.assertEqual(
                "1",
                graylog_values["graylog"]["env"][
                    "GRAYLOG_ELASTICSEARCH_REPLICAS"
                ],
            )
            self.assertEqual(
                "90",
                graylog_values["graylog"]["env"][
                    "GRAYLOG_ELASTICSEARCH_MAX_NUMBER_OF_INDICES"
                ],
            )
            self.assertEqual(
                "9300",
                graylog_values["datanode"]["env"][
                    "GRAYLOG_DATANODE_OPENSEARCH_TRANSPORT_PORT"
                ],
            )
            self.assertFalse(
                graylog_values["ingress"]["config"]["defaultBackend"]["enabled"]
            )

    def test_kubernetes_zabbix_ha_uses_external_secret_backed_database(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "cluster.yml")
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            values = yaml.safe_load(
                (
                    Path(directory)
                    / "production"
                    / "kubernetes"
                    / "zabbix.values.generated.yml"
                ).read_text(encoding="utf-8")
            )
        self.assertTrue(values["zabbixServer"]["zabbixServerHA"]["enabled"])
        self.assertEqual(3, values["zabbixServer"]["replicaCount"])
        self.assertFalse(values["postgresql"]["enabled"])
        self.assertEqual(
            "observeweaver-secrets", values["postgresAccess"]["existingSecretName"]
        )
        self.assertEqual(
            "ZABBIX_DATABASE_PASSWORD", values["postgresAccess"]["secretPasswordKey"]
        )

    def test_kubernetes_values_honor_monitoring_component_selection(self) -> None:
        config = load_config(ROOT / "config" / "examples" / "cluster.yml")
        config["components"]["prometheus"]["enabled"] = False
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            values = yaml.safe_load(
                (
                    Path(directory)
                    / "production"
                    / "kubernetes"
                    / "kube-prometheus-stack.values.generated.yml"
                ).read_text(encoding="utf-8")
            )
            self.assertFalse(
                values["grafana"]["sidecar"]["datasources"][
                    "defaultDatasourceEnabled"
                ]
            )

        config = load_config(ROOT / "config" / "examples" / "cluster.yml")
        config["components"]["grafana"]["enabled"] = False
        config["dependencies"]["postgresql"]["external"] = False
        self.assertEqual([], validate_config(config).errors)
        with tempfile.TemporaryDirectory() as directory:
            render(config, directory)
            values = yaml.safe_load(
                (
                    Path(directory)
                    / "production"
                    / "kubernetes"
                    / "kube-prometheus-stack.values.generated.yml"
                ).read_text(encoding="utf-8")
            )
            self.assertNotIn("env", values["grafana"])
            self.assertNotIn("envValueFrom", values["grafana"])


class SecretTests(unittest.TestCase):
    def test_secret_generation_has_expected_keys(self) -> None:
        values = generate_secret_values()
        self.assertGreaterEqual(len(values["GRAYLOG_PASSWORD_SECRET"]), 64)
        self.assertEqual(64, len(values["GRAYLOG_ROOT_PASSWORD_SHA2"]))
        self.assertNotEqual(
            values["GRAFANA_ADMIN_PASSWORD"], values["OPENSEARCH_INITIAL_ADMIN_PASSWORD"]
        )
        self.assertEqual("", values["MONGODB_URI"])

    def test_secret_file_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "secrets.env"
            write_secret_file(target)
            with self.assertRaises(FileExistsError):
                write_secret_file(target)


if __name__ == "__main__":
    unittest.main()
