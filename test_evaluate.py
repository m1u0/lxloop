from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parent
EVALUATOR = ROOT / "evaluate.py"


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


class EvaluatorCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.subject = self.root / "subject"
        self.worktree = self.root / "candidate"
        self.tool = self.root / "tool"
        self.fake_bin = self.root / "bin"
        self.deploy_dir = self.root / "deploy"
        self.logs_dir = self.root / "logs"
        self.command_log = self.root / "commands.log"

        self.subject.mkdir()
        run("git", "init", "-b", "main", cwd=self.subject)
        run("git", "config", "user.name", "lxloop test", cwd=self.subject)
        run("git", "config", "user.email", "lxloop@example.invalid", cwd=self.subject)
        source_dir = self.subject / "ggml" / "src" / "ggml-cpu"
        source_dir.mkdir(parents=True)
        (source_dir / "kernel.c").write_text("int kernel(void) { return 1; }\n")
        (self.subject / "README.md").write_text("baseline\n")
        run("git", "add", ".", cwd=self.subject)
        run("git", "commit", "-m", "baseline", cwd=self.subject)
        self.baseline_commit = run(
            "git", "rev-parse", "HEAD", cwd=self.subject
        ).stdout.strip()
        run(
            "git",
            "worktree",
            "add",
            "-b",
            "autoresearch/test",
            str(self.worktree),
            cwd=self.subject,
        )

        self.tool.mkdir()
        if EVALUATOR.exists():
            shutil.copy(EVALUATOR, self.tool / "evaluate.py")
        self.fake_bin.mkdir()
        self._write_fake_commands()
        self._write_build_command()
        self._write_config()

        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.fake_bin}{os.pathsep}{self.env['PATH']}"
        self.env["LXLOOP_COMMAND_LOG"] = str(self.command_log)
        self.env["LXLOOP_REMOTE_HAS_RSYNC"] = "1"
        self.env["LXLOOP_RSYNC_PROBE_RC"] = ""
        self.env["LXLOOP_RSYNC_PROBE_SLEEP"] = "0"
        self.env["LXLOOP_BUILD_RC"] = "0"
        self.env["LXLOOP_BUILD_SLEEP"] = "0"
        self.env["LXLOOP_TEST_RC"] = "0"
        self.env["LXLOOP_TEST_TRANSPORT_RC"] = "0"
        self.env["LXLOOP_BENCH_RC"] = "0"
        self.env["LXLOOP_BENCH_SLEEP"] = "0"
        self.env["LXLOOP_RSYNC_RC"] = "0"
        self.env["LXLOOP_SCP_RC"] = "0"
        self.env["LXLOOP_SSH_RC"] = "0"
        self.env["LXLOOP_DELETE_SSH_AFTER_PREP"] = "0"
        self.env["LXLOOP_DELETE_SSH_AFTER_TEST"] = "0"
        self.env["LXLOOP_BENCH_JSON"] = json.dumps(
            [
                {
                    "n_prompt": 512,
                    "n_gen": 0,
                    "avg_ts": 142.31,
                    "stddev_ts": 1.85,
                    "samples_ts": [140.1, 142.2, 143.0, 142.8, 143.45],
                },
                {
                    "n_prompt": 0,
                    "n_gen": 128,
                    "avg_ts": 9.874,
                    "stddev_ts": 0.041,
                    "samples_ts": [9.82, 9.86, 9.88, 9.90, 9.91],
                },
            ]
        )

    def _write_fake_commands(self) -> None:
        command = self.fake_bin / "fake-command"
        command.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                from pathlib import Path
                import re
                import sys

                name = Path(sys.argv[0]).name
                args = sys.argv[1:]
                with open(os.environ["LXLOOP_COMMAND_LOG"], "a") as log:
                    log.write(name + "|" + " ".join(args) + "\\n")

                if name == "ssh":
                    remote_command = args[-1]
                    if "command -v rsync" in remote_command:
                        import time
                        time.sleep(float(os.environ["LXLOOP_RSYNC_PROBE_SLEEP"]))
                        configured = os.environ["LXLOOP_RSYNC_PROBE_RC"]
                        if configured:
                            raise SystemExit(int(configured))
                        raise SystemExit(0 if os.environ["LXLOOP_REMOTE_HAS_RSYNC"] == "1" else 1)
                    if "run-tests" in remote_command:
                        transport_rc = int(os.environ["LXLOOP_TEST_TRANSPORT_RC"])
                        if transport_rc:
                            raise SystemExit(transport_rc)
                        sentinel = re.search(r"__LXLOOP_REMOTE_EXIT_[0-9a-f]+__:", remote_command)
                        assert sentinel is not None
                        print("correctness output")
                        print(sentinel.group() + os.environ["LXLOOP_TEST_RC"], file=sys.stderr)
                        if os.environ["LXLOOP_DELETE_SSH_AFTER_TEST"] == "1":
                            Path(sys.argv[0]).unlink()
                        raise SystemExit(0)
                    if "run-bench" in remote_command:
                        sentinel = re.search(r"__LXLOOP_REMOTE_EXIT_[0-9a-f]+__:", remote_command)
                        assert sentinel is not None
                        import time
                        time.sleep(float(os.environ["LXLOOP_BENCH_SLEEP"]))
                        print(os.environ["LXLOOP_BENCH_JSON"])
                        print(sentinel.group() + os.environ["LXLOOP_BENCH_RC"], file=sys.stderr)
                        raise SystemExit(0)
                    if os.environ["LXLOOP_DELETE_SSH_AFTER_PREP"] == "1":
                        Path(sys.argv[0]).unlink()
                    raise SystemExit(int(os.environ["LXLOOP_SSH_RC"]))

                if name == "rsync":
                    raise SystemExit(int(os.environ["LXLOOP_RSYNC_RC"]))
                if name == "scp":
                    raise SystemExit(int(os.environ["LXLOOP_SCP_RC"]))
                raise SystemExit(2)
                """
            )
        )
        command.chmod(0o755)
        for name in ("ssh", "rsync", "scp"):
            (self.fake_bin / name).symlink_to(command)

    def _write_build_command(self) -> None:
        build = self.root / "build.py"
        build.write_text(
            textwrap.dedent(
                """\
                from pathlib import Path
                import os
                import sys
                import time

                with open(os.environ["LXLOOP_COMMAND_LOG"], "a") as log:
                    log.write("build|candidate\\n")
                time.sleep(float(os.environ.get("LXLOOP_BUILD_SLEEP", "0")))
                marker = os.environ.get("LXLOOP_CHILD_MARKER")
                if marker:
                    import subprocess
                    subprocess.Popen([
                        sys.executable,
                        "-c",
                        "import pathlib,time; time.sleep(0.2); pathlib.Path(" + repr(marker) + ").write_text('survived')",
                    ])
                    time.sleep(1)
                if int(os.environ.get("LXLOOP_BUILD_RC", "0")):
                    print("compiler error", file=sys.stderr)
                    raise SystemExit(int(os.environ["LXLOOP_BUILD_RC"]))
                deploy_dir = Path(sys.argv[1])
                deploy_dir.mkdir(parents=True, exist_ok=True)
                (deploy_dir / "llama-bench").write_text("binary")
                """
            )
        )
        self.build_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(build))} {shlex.quote(str(self.deploy_dir))}"

    def _write_config(
        self, *, omit: tuple[str, ...] = (), **overrides: object
    ) -> None:
        values: dict[str, object] = {
            "LLAMA_DIR": str(self.worktree),
            "UPSTREAM_REF": self.baseline_commit,
            "TARGET": "riscv-board",
            "REMOTE_DIR": "/srv/lxloop/candidate",
            "BUILD_CMD": self.build_command,
            "DEPLOY_DIR": str(self.deploy_dir),
            "COMPILER_VERSION_CMD": shlex.quote(sys.executable)
            + " -c "
            + shlex.quote("print('test compiler 1.0')"),
            "TEST_CMD": "run-tests",
            "BENCH_CMD": "run-bench",
            "LOG_DIR": str(self.logs_dir),
            "TIMEOUTS": {"build": 10, "sync": 10, "test": 10, "bench": 10},
        }
        values.update(overrides)
        for key in omit:
            values.pop(key)
        lines = [f"{key} = {value!r}" for key, value in values.items()]
        (self.tool / "config.py").write_text("\n".join(lines) + "\n")

    def evaluate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.tool / "evaluate.py")],
            cwd=self.tool,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def command_lines(self) -> list[str]:
        return self.command_log.read_text().splitlines()

    def restrict_path_to_fake_bin(self) -> None:
        (self.fake_bin / "python3").symlink_to(sys.executable)
        git = shutil.which("git")
        assert git is not None
        (self.fake_bin / "git").symlink_to(git)
        self.env["PATH"] = str(self.fake_bin)

    def test_valid_candidate_is_built_deployed_tested_and_benchmarked(self) -> None:
        result = self.evaluate()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status: ok", result.stdout)
        self.assertIn("prefill_tps: 142.310 ± 1.850 (n=5)", result.stdout)
        self.assertIn("decode_tps: 9.874 ± 0.041 (n=5)", result.stdout)
        self.assertRegex(result.stdout, r"commit: [0-9a-f]+")
        self.assertIn("log:", result.stdout)

        commands = self.command_lines()
        self.assertEqual(commands[0], "build|candidate")
        self.assertIn("ssh|riscv-board command -v rsync", commands[1])
        self.assertTrue(commands[2].startswith("ssh|riscv-board mkdir -p"))
        self.assertTrue(commands[3].startswith("rsync|-az --delete"))
        self.assertIn("cd /srv/lxloop/candidate && /bin/sh -c run-tests", commands[4])
        self.assertIn("cd /srv/lxloop/candidate && /bin/sh -c run-bench", commands[5])

    def test_deploy_payload_contains_only_build_outputs(self) -> None:
        result = self.evaluate()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [path.name for path in self.deploy_dir.iterdir()], ["llama-bench"]
        )

    def test_committed_ggml_cpu_candidate_is_evaluated(self) -> None:
        kernel = self.worktree / "ggml" / "src" / "ggml-cpu" / "kernel.c"
        kernel.write_text("int kernel(void) { return 2; }\n")
        run("git", "add", str(kernel), cwd=self.worktree)
        run("git", "commit", "-m", "candidate", cwd=self.worktree)
        commit = run("git", "rev-parse", "--short", "HEAD", cwd=self.worktree).stdout.strip()

        result = self.evaluate()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"commit: {commit}", result.stdout)

    def test_compiler_version_is_captured_in_metadata_log(self) -> None:
        snippet = 'print("riscv compiler 1.0")'
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(snippet)}"
        self._write_config(COMPILER_VERSION_CMD=command)

        result = self.evaluate()

        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = next(self.logs_dir.glob("*/metadata.log")).read_text()
        self.assertIn("riscv compiler 1.0", metadata)

    def test_compiler_version_command_is_required(self) -> None:
        self._write_config(omit=("COMPILER_VERSION_CMD",))

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: config_error", result.stdout)
        self.assertIn("missing COMPILER_VERSION_CMD", result.stdout)

    def test_empty_compiler_identity_is_rejected(self) -> None:
        self._write_config(COMPILER_VERSION_CMD="true")

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: config_error", result.stdout)
        self.assertIn("produced no output", result.stdout)

    def test_transfer_failure_is_retried_once_before_stopping(self) -> None:
        self.env["LXLOOP_RSYNC_RC"] = "23"

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: sync_failed", result.stdout)
        commands = self.command_lines()
        self.assertEqual(sum(line.startswith("rsync|") for line in commands), 2)
        self.assertFalse(any("run-tests" in line for line in commands))

    def test_remote_prepare_ssh_failure_is_retried_then_stops(self) -> None:
        self.env["LXLOOP_SSH_RC"] = "255"

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: infrastructure_failed", result.stdout)
        prepare_commands = [line for line in self.command_lines() if "mkdir -p" in line]
        self.assertEqual(len(prepare_commands), 2)

    def test_rsync_probe_ssh_failure_is_retried_then_stops(self) -> None:
        self.env["LXLOOP_RSYNC_PROBE_RC"] = "255"

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: infrastructure_failed", result.stdout)
        self.assertEqual(len(list(self.logs_dir.glob("*/rsync-probe*.log"))), 2)

    def test_rsync_probe_timeout_is_retried_then_stops(self) -> None:
        self.env["LXLOOP_RSYNC_PROBE_SLEEP"] = "0.2"
        self._write_config(
            TIMEOUTS={"build": 10, "sync": 0.05, "test": 10, "bench": 10}
        )

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: infrastructure_failed", result.stdout)
        self.assertEqual(len(list(self.logs_dir.glob("*/rsync-probe*.log"))), 2)

    def test_missing_ssh_executable_is_retried_then_stops(self) -> None:
        (self.fake_bin / "ssh").unlink()
        self.restrict_path_to_fake_bin()

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: infrastructure_failed", result.stdout)
        self.assertEqual(len(list(self.logs_dir.glob("*/rsync-probe*.log"))), 2)

    def test_ssh_launch_failure_before_correctness_is_retried(self) -> None:
        self.env["LXLOOP_DELETE_SSH_AFTER_PREP"] = "1"
        self.restrict_path_to_fake_bin()

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: infrastructure_failed", result.stdout)
        self.assertEqual(len(list(self.logs_dir.glob("*/test*.log"))), 2)
        self.assertFalse(any("run-bench" in line for line in self.command_lines()))

    def test_ssh_launch_failure_before_benchmark_is_retried(self) -> None:
        self.env["LXLOOP_DELETE_SSH_AFTER_TEST"] = "1"
        self.restrict_path_to_fake_bin()

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: infrastructure_failed", result.stdout)
        self.assertEqual(len(list(self.logs_dir.glob("*/bench*.log"))), 2)

    def test_committed_change_outside_ggml_cpu_is_rejected_before_build(self) -> None:
        (self.worktree / "README.md").write_text("out of scope\n")
        run("git", "add", "README.md", cwd=self.worktree)
        run("git", "commit", "-m", "out of scope", cwd=self.worktree)

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: boundary_violation", result.stdout)
        commit = run("git", "rev-parse", "--short", "HEAD", cwd=self.worktree).stdout.strip()
        self.assertIn(f"commit: {commit}", result.stdout)
        self.assertIn("README.md", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_untracked_change_outside_ggml_cpu_is_a_boundary_violation(self) -> None:
        (self.worktree / "notes.txt").write_text("out of scope\n")

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: boundary_violation", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_tracked_uncommitted_change_outside_ggml_cpu_is_rejected(self) -> None:
        (self.worktree / "README.md").write_text("changed\n")

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: boundary_violation", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_rename_from_outside_into_ggml_cpu_is_rejected(self) -> None:
        destination = "ggml/src/ggml-cpu/renamed-readme.md"
        run("git", "mv", "README.md", destination, cwd=self.worktree)
        run("git", "commit", "-m", "rename across boundary", cwd=self.worktree)

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: boundary_violation", result.stdout)
        self.assertIn("README.md", result.stdout)

    def test_type_change_outside_ggml_cpu_is_rejected(self) -> None:
        readme = self.worktree / "README.md"
        readme.unlink()
        readme.symlink_to("ggml/src/ggml-cpu/kernel.c")
        run("git", "add", "README.md", cwd=self.worktree)
        run("git", "commit", "-m", "type change outside boundary", cwd=self.worktree)

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: boundary_violation", result.stdout)
        self.assertIn("README.md", result.stdout)

    def test_uncommitted_change_inside_ggml_cpu_is_rejected_as_dirty(self) -> None:
        kernel = self.worktree / "ggml" / "src" / "ggml-cpu" / "kernel.c"
        kernel.write_text("int kernel(void) { return 2; }\n")

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: dirty_worktree", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_scp_fallback_uploads_deploy_directory_contents(self) -> None:
        (self.fake_bin / "rsync").unlink()
        self.restrict_path_to_fake_bin()

        result = self.evaluate()

        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.command_lines()
        self.assertFalse(any(line.startswith("rsync|") for line in commands))
        prepare = next(line for line in commands if "rm -rf" in line)
        self.assertIn("rm -rf -- /srv/lxloop/candidate", prepare)
        self.assertIn("mkdir -p -- /srv/lxloop/candidate", prepare)
        scp = next(line for line in commands if line.startswith("scp|"))
        self.assertIn(f"-r {self.deploy_dir.resolve()}/.", scp)
        self.assertIn("riscv-board:/srv/lxloop/candidate/", scp)

    def test_scp_is_used_when_target_does_not_have_rsync(self) -> None:
        self.env["LXLOOP_REMOTE_HAS_RSYNC"] = "0"

        result = self.evaluate()

        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.command_lines()
        self.assertTrue(any("command -v rsync" in line for line in commands))
        self.assertTrue(any(line.startswith("scp|") for line in commands))
        self.assertFalse(any(line.startswith("rsync|") for line in commands))

    def test_unsafe_remote_directory_is_rejected_before_remote_commands(self) -> None:
        self._write_config(REMOTE_DIR="/")

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: config_error", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_build_failure_stops_before_deployment(self) -> None:
        self.env["LXLOOP_BUILD_RC"] = "1"

        result = self.evaluate()

        self.assertEqual(result.returncode, 4)
        self.assertIn("status: build_failed", result.stdout)
        self.assertNotIn("compiler error", result.stdout)
        self.assertEqual(self.command_lines(), ["build|candidate"])
        build_log = next(self.logs_dir.glob("*/build.log")).read_text()
        self.assertIn("compiler error", build_log)

    def test_correctness_failure_skips_benchmark(self) -> None:
        self.env["LXLOOP_TEST_RC"] = "1"

        result = self.evaluate()

        self.assertEqual(result.returncode, 6)
        self.assertIn("status: test_failed", result.stdout)
        commands = self.command_lines()
        self.assertTrue(any("run-tests" in line for line in commands))
        self.assertFalse(any("run-bench" in line for line in commands))

    def test_ssh_infrastructure_failure_is_retried_then_stops(self) -> None:
        self.env["LXLOOP_TEST_TRANSPORT_RC"] = "255"

        result = self.evaluate()

        self.assertEqual(result.returncode, 5)
        self.assertIn("status: infrastructure_failed", result.stdout)
        commands = self.command_lines()
        self.assertEqual(sum("run-tests" in line for line in commands), 2)
        self.assertFalse(any("run-bench" in line for line in commands))

    def test_correctness_exit_255_is_a_test_failure_not_an_ssh_failure(self) -> None:
        self.env["LXLOOP_TEST_RC"] = "255"

        result = self.evaluate()

        self.assertEqual(result.returncode, 6)
        self.assertIn("status: test_failed", result.stdout)
        commands = self.command_lines()
        self.assertEqual(sum("run-tests" in line for line in commands), 1)
        self.assertFalse(any("run-bench" in line for line in commands))

    def test_malformed_benchmark_output_is_reported(self) -> None:
        self.env["LXLOOP_BENCH_JSON"] = "not json"

        result = self.evaluate()

        self.assertEqual(result.returncode, 8)
        self.assertIn("status: bench_parse_failed", result.stdout)
        bench_log = next(self.logs_dir.glob("*/bench.log")).read_text()
        self.assertIn("not json", bench_log)

    def test_benchmark_crash_is_reported(self) -> None:
        self.env["LXLOOP_BENCH_RC"] = "132"

        result = self.evaluate()

        self.assertEqual(result.returncode, 7)
        self.assertIn("status: illegal_instruction", result.stdout)

    def test_benchmark_signal_crash_is_distinct_from_ordinary_failure(self) -> None:
        self.env["LXLOOP_BENCH_RC"] = "139"

        result = self.evaluate()

        self.assertEqual(result.returncode, 7)
        self.assertIn("status: bench_crashed", result.stdout)

    def test_missing_prefill_metric_is_reported(self) -> None:
        self.env["LXLOOP_BENCH_JSON"] = json.dumps(
            [
                {
                    "n_prompt": 0,
                    "n_gen": 128,
                    "avg_ts": 9.874,
                    "stddev_ts": 0.041,
                    "samples_ts": [9.82, 9.91],
                }
            ]
        )

        result = self.evaluate()

        self.assertEqual(result.returncode, 8)
        self.assertIn("status: bench_parse_failed", result.stdout)

    def test_build_timeout_is_reported_and_logged(self) -> None:
        self.env["LXLOOP_BUILD_SLEEP"] = "0.5"
        self._write_config(
            TIMEOUTS={"build": 0.05, "sync": 10, "test": 10, "bench": 10}
        )

        result = self.evaluate()

        self.assertEqual(result.returncode, 4)
        self.assertIn("status: build_timeout", result.stdout)
        build_log = next(self.logs_dir.glob("*/build.log")).read_text()
        self.assertIn("result: timeout", build_log)

    def test_build_timeout_terminates_descendant_processes(self) -> None:
        marker = self.root / "child-survived"
        self.env["LXLOOP_CHILD_MARKER"] = str(marker)
        self._write_config(
            TIMEOUTS={"build": 0.05, "sync": 10, "test": 10, "bench": 10}
        )

        result = self.evaluate()
        time.sleep(0.4)

        self.assertEqual(result.returncode, 4)
        self.assertIn("status: build_timeout", result.stdout)
        self.assertFalse(marker.exists())

    def test_benchmark_timeout_is_reported(self) -> None:
        self.env["LXLOOP_BENCH_SLEEP"] = "0.5"
        self._write_config(
            TIMEOUTS={"build": 10, "sync": 10, "test": 10, "bench": 0.05}
        )

        result = self.evaluate()

        self.assertEqual(result.returncode, 7)
        self.assertIn("status: bench_timeout", result.stdout)

    def test_wrong_branch_is_rejected(self) -> None:
        run("git", "switch", "-c", "feature/not-research", cwd=self.worktree)

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: wrong_branch", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_main_checkout_is_rejected_even_with_research_branch_name(self) -> None:
        run("git", "switch", "-c", "autoresearch/not-a-worktree", cwd=self.subject)
        self._write_config(LLAMA_DIR=str(self.subject))

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: not_dedicated_worktree", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_missing_upstream_reference_is_reported_as_git_error(self) -> None:
        self._write_config(UPSTREAM_REF="missing-baseline")

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: git_error", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_research_branch_must_descend_from_configured_baseline(self) -> None:
        (self.subject / "README.md").write_text("new baseline\n")
        run("git", "add", "README.md", cwd=self.subject)
        run("git", "commit", "-m", "advance configured baseline", cwd=self.subject)
        new_baseline = run("git", "rev-parse", "HEAD", cwd=self.subject).stdout.strip()
        self._write_config(UPSTREAM_REF=new_baseline)

        result = self.evaluate()

        self.assertEqual(result.returncode, 3)
        self.assertIn("status: wrong_baseline", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_movable_upstream_reference_is_rejected(self) -> None:
        self._write_config(UPSTREAM_REF="main")

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: config_error", result.stdout)
        self.assertIn("full immutable commit", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_missing_configuration_is_reported(self) -> None:
        (self.tool / "config.py").unlink()

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: config_error", result.stdout)
        self.assertIn("copy config.example.py", result.stdout)

    def test_missing_required_configuration_value_is_reported(self) -> None:
        self._write_config(omit=("TEST_CMD",))

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: config_error", result.stdout)
        self.assertIn("missing TEST_CMD", result.stdout)

    def test_nonpositive_timeout_is_rejected(self) -> None:
        self._write_config(
            TIMEOUTS={"build": 0, "sync": 10, "test": 10, "bench": 10}
        )

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: config_error", result.stdout)
        self.assertIn("timeouts must be positive", result.stdout)

    def test_build_command_runs_from_subject_checkout(self) -> None:
        observed_cwd = self.root / "build-cwd"
        build = self.root / "cwd-build.py"
        build.write_text(
            textwrap.dedent(
                f"""\
                from pathlib import Path
                Path({str(observed_cwd)!r}).write_text(str(Path.cwd()))
                deploy = Path({str(self.deploy_dir)!r})
                deploy.mkdir(parents=True)
                (deploy / "llama-bench").write_text("binary")
                """
            )
        )
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(build))}"
        self._write_config(BUILD_CMD=command)

        result = self.evaluate()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(observed_cwd.read_text()), self.worktree.resolve())

    def test_unusable_log_directory_still_returns_a_stable_summary(self) -> None:
        blocked = self.root / "blocked-logs"
        blocked.write_text("not a directory")
        self._write_config(LOG_DIR=str(blocked))

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: log_failed", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_metadata_log_write_failure_returns_a_stable_summary(self) -> None:
        snippet = (
            "from pathlib import Path; "
            f"p=next(Path({str(self.logs_dir)!r}).iterdir())/'metadata.log'; "
            "p.mkdir(); print('test compiler 1.0')"
        )
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(snippet)}"
        self._write_config(COMPILER_VERSION_CMD=command)

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: log_failed", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_phase_log_write_failure_returns_a_stable_summary(self) -> None:
        snippet = (
            "from pathlib import Path; "
            f"logs=next(Path({str(self.logs_dir)!r}).iterdir()); "
            "(logs/'build.log').mkdir(); "
            f"deploy=Path({str(self.deploy_dir)!r}); "
            "deploy.mkdir(parents=True, exist_ok=True); "
            "(deploy/'llama-bench').write_text('binary')"
        )
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(snippet)}"
        self._write_config(BUILD_CMD=command)

        result = self.evaluate()

        self.assertEqual(result.returncode, 2)
        self.assertIn("status: log_failed", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_unsafe_remote_directory_forms_are_rejected(self) -> None:
        for remote_dir in ("", "relative/path", "/tmp", "/srv/lx loop", "/srv/../tmp"):
            with self.subTest(remote_dir=remote_dir):
                self._write_config(REMOTE_DIR=remote_dir)
                result = self.evaluate()
                self.assertEqual(result.returncode, 2)
                self.assertIn("status: config_error", result.stdout)

    def test_missing_decode_metric_is_reported(self) -> None:
        self.env["LXLOOP_BENCH_JSON"] = json.dumps(
            [
                {
                    "n_prompt": 512,
                    "n_gen": 0,
                    "avg_ts": 142.31,
                    "stddev_ts": 1.85,
                    "samples_ts": [140.1, 142.2],
                }
            ]
        )

        result = self.evaluate()

        self.assertEqual(result.returncode, 8)
        self.assertIn("status: bench_parse_failed", result.stdout)

    def test_empty_deploy_directory_is_a_build_failure(self) -> None:
        self._write_config(BUILD_CMD="true", DEPLOY_DIR=str(self.root / "empty"))

        result = self.evaluate()

        self.assertEqual(result.returncode, 4)
        self.assertIn("status: build_failed", result.stdout)
        self.assertIn("non-empty deploy directory", result.stdout)
        self.assertFalse(self.command_log.exists())

    def test_stale_deploy_payload_is_removed_before_build(self) -> None:
        stale_binary = self.deploy_dir / "llama-bench"
        snippet = (
            "from pathlib import Path; "
            f"p=Path({str(stale_binary)!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            "p.write_text('partial stale binary'); "
            "raise SystemExit(1)"
        )
        failing_build = f"{shlex.quote(sys.executable)} -c {shlex.quote(snippet)}"
        self._write_config(BUILD_CMD=failing_build)
        first_result = self.evaluate()
        self.assertEqual(first_result.returncode, 4)
        self.assertTrue(stale_binary.exists())

        self._write_config(BUILD_CMD="true")

        result = self.evaluate()

        self.assertEqual(result.returncode, 4)
        self.assertIn("status: build_failed", result.stdout)
        self.assertFalse(stale_binary.exists())


if __name__ == "__main__":
    unittest.main()
