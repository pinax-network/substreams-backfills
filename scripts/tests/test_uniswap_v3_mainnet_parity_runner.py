from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
RUNNER = REPOSITORY / "scripts/run-uniswap-v3-mainnet-chain-config-parity.sh"
WORKFLOW = REPOSITORY / ".github/workflows/ci.yaml"
REVISION = "a" * 40
ACK = "run-fixed-mainnet-range-12369621-12370674"
SUBSTREAMS_VERSION = "substreams version 1.20.3 (Commit cc555bd, Commit Date 2026-07-31T14:30:54Z)"


class MainnetParityRunnerContractTest(unittest.TestCase):
    def invoke(self, artifact: Path, overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
        environment = {
            "PATH": os.environ["PATH"],
            "SOURCE_REVISION": REVISION,
            "SUBSTREAMS_ENDPOINT": "mainnet.example.test:443",
            "SUBSTREAMS_API_TOKEN": "test-token-never-printed",
            "ETHEREUM_RPC_URL": "https://rpc.example.test/secret-token",
            "ETHEREUM_RPC_LABEL": "public-test-rpc",
            **overrides,
        }
        return subprocess.run(
            ["/bin/bash", str(RUNNER), str(artifact)],
            cwd=REPOSITORY,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_explicit_live_ack_is_required_before_any_artifact_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "evidence"
            result = self.invoke(artifact, {})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("UNISWAP_V3_MAINNET_PARITY_LIVE_ACK", result.stderr)
            self.assertNotIn("test-token-never-printed", result.stderr)
            self.assertFalse(artifact.exists())

    def test_endpoint_must_not_contain_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "evidence"
            result = self.invoke(
                artifact,
                {
                    "UNISWAP_V3_MAINNET_PARITY_LIVE_ACK": ACK,
                    "SUBSTREAMS_ENDPOINT": "https://user:password@mainnet.example.test:443",
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("credential-free DNS host:numeric-port", result.stderr)
            self.assertNotIn("password", result.stderr)
            self.assertFalse(artifact.exists())

    def test_existing_artifact_directory_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "evidence"
            artifact.mkdir()
            marker = artifact / "keep"
            marker.write_text("unchanged")
            result = self.invoke(
                artifact,
                {"UNISWAP_V3_MAINNET_PARITY_LIVE_ACK": ACK},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)
            self.assertEqual(marker.read_text(), "unchanged")

    def test_rpc_public_label_is_required_without_deriving_or_echoing_secret_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "evidence"
            result = self.invoke(
                artifact,
                {
                    "UNISWAP_V3_MAINNET_PARITY_LIVE_ACK": ACK,
                    "ETHEREUM_RPC_URL": "https://tenant-secret.example/private",
                    "ETHEREUM_RPC_LABEL": "https://tenant-secret.example",
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("explicit short public label", result.stderr)
            self.assertNotIn("tenant-secret", result.stderr)
            self.assertFalse(artifact.exists())

    def test_outer_cleanup_failure_removes_successful_child_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            shims = temporary_path / "shims"
            shims.mkdir()

            def executable(name: str, source: str) -> None:
                path = shims / name
                path.write_text(source, encoding="utf-8")
                path.chmod(0o700)

            executable(
                "git",
                """#!/bin/sh
if [ "$1" = "-C" ]; then shift 2; fi
if [ "$1" = "cat-file" ]; then exit 0; fi
if [ "$1" = "worktree" ] && [ "$2" = "add" ]; then mkdir -p "$4"; exit 0; fi
if [ "$1" = "worktree" ] && [ "$2" = "remove" ]; then exit 1; fi
exit 1
""",
            )
            executable(
                "bash",
                """#!/bin/sh
for argument do artifact=$argument; done
mkdir "$artifact"
printf '%s\n' fixture > "$artifact/parity-certificate.json"
exit 0
""",
            )
            executable(
                "go",
                """#!/bin/sh
if [ "$1" = "version" ]; then
    printf '%s\n' 'go version go1.26.5 linux/amd64'
    exit 0
fi
exit 1
""",
            )
            executable(
                "substreams",
                f"""#!/bin/sh
if [ "$1" = "--version" ]; then
    printf '%s\\n' '{SUBSTREAMS_VERSION}'
    exit 0
fi
exit 1
""",
            )
            executable("cargo", "#!/bin/sh\nexit 1\n")
            executable("rustc", "#!/bin/sh\nexit 1\n")

            artifact = temporary_path / "evidence"
            result = self.invoke(
                artifact,
                {
                    "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}",
                    "TMPDIR": str(temporary_path),
                    "UNISWAP_V3_MAINNET_PARITY_LIVE_ACK": ACK,
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("could not remove exact-revision worktree", result.stderr)
            self.assertFalse(artifact.exists())

    def test_contract_uses_two_complete_v3_streams_full_rpc_snapshots_and_secret_scan(self) -> None:
        source = RUNNER.read_text()
        self.assertNotIn("set -x", source)
        self.assertIn('capture_invocation baseline "$baseline_spkg"', source)
        self.assertIn('capture_invocation candidate "$mainnet_spkg"', source)
        self.assertEqual(source.count("capture_invocation baseline"), 1)
        self.assertEqual(source.count("capture_invocation candidate"), 1)
        self.assertIn('capture_rpc_snapshot before "$rpc_before"', source)
        self.assertIn('capture_rpc_snapshot after "$rpc_after"', source)
        self.assertIn("for first in range(START, STOP, BATCH)", source)
        self.assertIn("supplied secret detected in staged artifact", source)
        self.assertIn('python3 - "$runtime_dir" "$capture_dir"', source)
        self.assertIn('os.link(source, destination, follow_symlinks=False)', source)
        self.assertLess(
            source.index("supplied secret detected in staged artifact"),
            source.index('"$capture_client" "$artifact_dir/uniswap-v3-parity-client" 0500'),
        )
        self.assertNotIn("ethereum_rpc_origin", source)
        self.assertIn('SUBSTREAMS_API_TOKEN="$substreams_api_token"', source)
        self.assertIn('ETHEREUM_RPC_URL="$ethereum_rpc_url"', source)

    def test_runner_and_ci_require_exact_cli_and_go_versions(self) -> None:
        runner = RUNNER.read_text()
        workflow = WORKFLOW.read_text()
        self.assertIn(f'substreams_version_expected="{SUBSTREAMS_VERSION}"', runner)
        self.assertIn('[[ $(substreams --version) == "$substreams_version_expected" ]]', runner)
        self.assertIn(f'test "$(substreams --version)" = "{SUBSTREAMS_VERSION}"', workflow)
        self.assertIn("go_version_pattern='^go version go1\\.26\\.5 (darwin|linux)/(amd64|arm64)$'", runner)
        self.assertIn('go-version: "1.26.5"', workflow)
        self.assertNotIn('version 1.20.3"*', runner)
        self.assertNotIn('version 1.20.3"*', workflow)


if __name__ == "__main__":
    unittest.main()
