#!/usr/bin/env python3
"""Evaluate one committed llama.cpp candidate on a remote RISC-V target."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Sequence


ALLOWED_PREFIX = "ggml/src/ggml-cpu/"
REMOTE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class Metric:
    mean: float
    stddev: float
    samples: tuple[float, ...]


@dataclass(frozen=True)
class Settings:
    llama_dir: Path
    upstream_ref: str
    target: str
    remote_dir: str
    build_cmd: str
    deploy_dir: Path
    compiler_version_cmd: str
    test_cmd: str
    bench_cmd: str
    log_dir: Path
    timeouts: dict[str, float]


class EvaluationFailure(Exception):
    def __init__(self, status: str, reason: str, exit_code: int) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.exit_code = exit_code


class Evaluator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.commit = "unknown"
        self.run_log_dir: Path | None = None

    def evaluate(self) -> tuple[Metric, Metric]:
        self.guard_subject_checkout()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        try:
            self.settings.log_dir.mkdir(parents=True, exist_ok=True)
            self.run_log_dir = Path(
                tempfile.mkdtemp(
                    prefix=f"{timestamp}_{self.commit}_",
                    dir=self.settings.log_dir,
                )
            )
        except OSError as error:
            raise EvaluationFailure(
                "log_failed", f"could not create evaluation log directory: {error}", 2
            ) from error

        self.record_build_metadata()
        self.run_local_command(
            self.settings.build_cmd,
            phase="build",
            timeout=self.timeout("build"),
            failure_status="build_failed",
            exit_code=4,
        )
        self.validate_deploy_dir()
        self.deploy()
        self.run_remote_command(
            self.settings.test_cmd,
            phase="test",
            timeout=self.timeout("test"),
            failure_status="test_failed",
            exit_code=6,
        )
        benchmark = self.run_remote_command(
            self.settings.bench_cmd,
            phase="bench",
            timeout=self.timeout("bench"),
            failure_status="bench_failed",
            exit_code=7,
        )
        return parse_benchmark(benchmark.stdout)

    def guard_subject_checkout(self) -> None:
        directory = self.settings.llama_dir
        if not directory.is_dir():
            raise EvaluationFailure("config_error", f"LLAMA_DIR is not a directory: {directory}", 2)

        try:
            branch = self.git("branch", "--show-current").stdout.strip()
            self.commit = self.git("rev-parse", "--short", "HEAD").stdout.strip()
            resolved_upstream = self.git(
                "rev-parse", "--verify", f"{self.settings.upstream_ref}^{{commit}}"
            ).stdout.strip()
            git_dir = self.resolve_git_path(self.git("rev-parse", "--git-dir").stdout.strip())
            common_dir = self.resolve_git_path(
                self.git("rev-parse", "--git-common-dir").stdout.strip()
            )
        except subprocess.CalledProcessError as error:
            raise EvaluationFailure(
                "git_error", "subject checkout or upstream reference is invalid", 3
            ) from error

        if not branch.startswith("autoresearch/"):
            raise EvaluationFailure(
                "wrong_branch", "subject checkout must be on an autoresearch/* branch", 3
            )
        if self.settings.upstream_ref.lower() != resolved_upstream.lower():
            raise EvaluationFailure(
                "config_error",
                "UPSTREAM_REF must be the full immutable commit ID for the run baseline",
                2,
            )
        if git_dir == common_dir:
            raise EvaluationFailure(
                "not_dedicated_worktree",
                "subject checkout must be a linked Git worktree",
                3,
            )
        ancestry = subprocess.run(
            [
                "git",
                "-C",
                str(self.settings.llama_dir),
                "merge-base",
                "--is-ancestor",
                self.settings.upstream_ref,
                "HEAD",
            ],
            capture_output=True,
            text=True,
        )
        if ancestry.returncode == 1:
            raise EvaluationFailure(
                "wrong_baseline",
                "research branch does not descend from UPSTREAM_REF",
                3,
            )
        if ancestry.returncode != 0:
            raise EvaluationFailure(
                "git_error", "could not compare HEAD with UPSTREAM_REF", 3
            )

        changed = self.changed_paths()
        outside = sorted(path for path in changed if not path.startswith(ALLOWED_PREFIX))
        if outside:
            raise EvaluationFailure(
                "boundary_violation",
                "candidate changes outside ggml-cpu: " + ", ".join(outside),
                3,
            )

        if self.git("status", "--porcelain", "--untracked-files=normal").stdout.strip():
            raise EvaluationFailure(
                "dirty_worktree", "candidate must be committed before evaluation", 3
            )

    def changed_paths(self) -> set[str]:
        committed = self.git(
            "diff",
            "--name-only",
            "--no-renames",
            f"{self.settings.upstream_ref}...HEAD",
        ).stdout.splitlines()
        working = self.git(
            "diff", "--name-only", "--no-renames", "HEAD"
        ).stdout.splitlines()
        untracked = self.git(
            "ls-files", "--others", "--exclude-standard"
        ).stdout.splitlines()
        return {path for path in (*committed, *working, *untracked) if path}

    def deploy(self) -> None:
        validate_remote_dir(self.settings.remote_dir)
        if shutil.which("rsync") and self.remote_has_rsync():
            self.prepare_remote_dir(recreate=False)
            source = f"{self.settings.deploy_dir}{os.sep}"
            destination = f"{self.settings.target}:{self.settings.remote_dir}/"
            self.run_external_with_retry(
                ["rsync", "-az", "--delete", source, destination],
                phase="sync",
                timeout=self.timeout("sync"),
                failure_status="sync_failed",
                exit_code=5,
                exhausted_reason="rsync transfer failed twice",
            )
            return

        self.prepare_remote_dir(recreate=True)
        source = f"{self.settings.deploy_dir}{os.sep}."
        destination = f"{self.settings.target}:{self.settings.remote_dir}/"
        self.run_external_with_retry(
            ["scp", "-r", source, destination],
            phase="sync",
            timeout=self.timeout("sync"),
            failure_status="sync_failed",
            exit_code=5,
            exhausted_reason="SCP transfer failed twice",
        )

    def run_external_with_retry(
        self,
        args: Sequence[str],
        *,
        phase: str,
        timeout: float,
        failure_status: str,
        exit_code: int,
        exhausted_reason: str,
        allowed_returncodes: set[int] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        successful = allowed_returncodes or {0}
        last_reason = "unknown failure"
        for attempt in (1, 2):
            try:
                result = self.run_external(
                    args,
                    phase=phase if attempt == 1 else f"{phase}-retry",
                    timeout=timeout,
                    failure_status=failure_status,
                    exit_code=exit_code,
                    allowed_returncodes=successful | {255},
                )
            except EvaluationFailure as error:
                last_reason = error.reason
                continue
            if result.returncode in successful:
                return result
            last_reason = f"{phase} exited with status {result.returncode}"
        raise EvaluationFailure(
            failure_status,
            f"{exhausted_reason}: {last_reason}",
            exit_code,
        )

    def remote_has_rsync(self) -> bool:
        args = ["ssh", self.settings.target, "command -v rsync >/dev/null 2>&1"]
        result = self.run_external_with_retry(
            args,
            phase="rsync-probe",
            timeout=self.timeout("sync"),
            failure_status="infrastructure_failed",
            exit_code=5,
            exhausted_reason="could not check target rsync availability",
            allowed_returncodes={0, 1},
        )
        return result.returncode == 0

    def prepare_remote_dir(self, *, recreate: bool) -> None:
        remote = shlex.quote(self.settings.remote_dir)
        if recreate:
            command = f"rm -rf -- {remote} && mkdir -p -- {remote}"
        else:
            command = f"mkdir -p -- {remote}"
        args = ["ssh", self.settings.target, command]
        self.run_external_with_retry(
            args,
            phase="sync-prepare",
            timeout=self.timeout("sync"),
            failure_status="infrastructure_failed",
            exit_code=5,
            exhausted_reason="could not prepare the remote directory",
        )

    def run_remote_command(
        self,
        command: str,
        *,
        phase: str,
        timeout: float,
        failure_status: str,
        exit_code: int,
    ) -> subprocess.CompletedProcess[str]:
        remote = shlex.quote(self.settings.remote_dir)
        args = ["ssh", self.settings.target, f"cd {remote} && {command}"]
        last_reason = f"SSH exited with status 255 while running {phase}"
        for attempt in (1, 2):
            try:
                result = self.run_external(
                    args,
                    phase=phase if attempt == 1 else f"{phase}-retry",
                    timeout=timeout,
                    failure_status=failure_status,
                    exit_code=exit_code,
                    allowed_returncodes={0, 255},
                )
            except EvaluationFailure as error:
                if isinstance(error.__cause__, OSError):
                    last_reason = error.reason
                    continue
                raise
            if result.returncode == 0:
                return result
        raise EvaluationFailure(
            "infrastructure_failed",
            f"SSH failed twice while running {phase}: {last_reason}",
            5,
        )

    def run_local_command(
        self,
        command: str,
        *,
        phase: str,
        timeout: float,
        failure_status: str,
        exit_code: int,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_external(
            ["/bin/sh", "-c", command],
            phase=phase,
            timeout=timeout,
            failure_status=failure_status,
            exit_code=exit_code,
            cwd=self.settings.llama_dir,
        )

    def run_external(
        self,
        args: Sequence[str],
        *,
        phase: str,
        timeout: float,
        failure_status: str,
        exit_code: int,
        cwd: Path | None = None,
        allowed_returncodes: set[int] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        allowed = allowed_returncodes or {0}
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                start_new_session=True,
            )
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            terminate_process_group(process)
            stdout, stderr = process.communicate()
            self.write_phase_log(phase, args, stdout, stderr, "timeout")
            raise EvaluationFailure(
                f"{phase}_timeout", f"{phase} exceeded {timeout:g} seconds", exit_code
            ) from error
        except OSError as error:
            self.write_phase_log(phase, args, "", str(error), "launch_failed")
            raise EvaluationFailure(failure_status, f"{phase} could not start: {error}", exit_code) from error

        self.write_phase_log(
            phase,
            args,
            stdout,
            stderr,
            f"exit {process.returncode}",
        )
        if process.returncode not in allowed:
            raise EvaluationFailure(
                failure_status,
                f"{phase} exited with status {process.returncode}",
                exit_code,
            )
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)

    def validate_deploy_dir(self) -> None:
        directory = self.settings.deploy_dir
        if not directory.is_dir() or not any(directory.iterdir()):
            raise EvaluationFailure(
                "build_failed",
                f"build did not produce a non-empty deploy directory: {directory}",
                4,
            )

    def record_build_metadata(self) -> None:
        lines = [f"build_command: {self.settings.build_cmd}\n"]
        command = self.settings.compiler_version_cmd
        if command:
            try:
                result = subprocess.run(
                    ["/bin/sh", "-c", command],
                    cwd=self.settings.llama_dir,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=self.timeout("build"),
                )
                lines.extend(
                    [
                        f"compiler_version_exit: {result.returncode}\n",
                        result.stdout,
                        result.stderr,
                    ]
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                lines.append(f"compiler_version_error: {error}\n")
        self.log_path("metadata").write_text("".join(lines))

    def write_phase_log(
        self,
        phase: str,
        args: Sequence[str],
        stdout: str,
        stderr: str,
        result: str,
    ) -> None:
        if self.run_log_dir is None:
            return
        body = [
            f"command: {shlex.join(args)}\n",
            f"result: {result}\n",
            "--- stdout ---\n",
            stdout,
            "\n--- stderr ---\n",
            stderr,
        ]
        self.log_path(phase).write_text("".join(body))

    def log_path(self, phase: str) -> Path:
        assert self.run_log_dir is not None
        return self.run_log_dir / f"{phase}.log"

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.settings.llama_dir), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def resolve_git_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.settings.llama_dir / path
        return path.resolve()

    def timeout(self, phase: str) -> float:
        return self.settings.timeouts[phase]


def load_settings(tool_dir: Path) -> Settings:
    config_path = tool_dir / "config.py"
    if not config_path.is_file():
        raise EvaluationFailure(
            "config_error", "config.py is missing; copy config.example.py first", 2
        )

    spec = importlib.util.spec_from_file_location("lxloop_config", config_path)
    if spec is None or spec.loader is None:
        raise EvaluationFailure("config_error", "config.py could not be loaded", 2)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise EvaluationFailure("config_error", f"config.py failed to load: {error}", 2) from error

    try:
        llama_dir = expanded_path(module, "LLAMA_DIR")
        deploy_dir = expanded_path(module, "DEPLOY_DIR", relative_to=llama_dir)
        log_dir = expanded_path(module, "LOG_DIR", relative_to=tool_dir)
        remote_dir = str(required(module, "REMOTE_DIR"))
        validate_remote_dir(remote_dir)
        timeouts_value = required(module, "TIMEOUTS")
        timeouts = {
            phase: float(timeouts_value[phase])
            for phase in ("build", "sync", "test", "bench")
        }
        if any(value <= 0 for value in timeouts.values()):
            raise ValueError("timeouts must be positive")
        return Settings(
            llama_dir=llama_dir,
            upstream_ref=str(required(module, "UPSTREAM_REF")),
            target=str(required(module, "TARGET")),
            remote_dir=remote_dir,
            build_cmd=str(required(module, "BUILD_CMD")),
            deploy_dir=deploy_dir,
            compiler_version_cmd=str(getattr(module, "COMPILER_VERSION_CMD", "")),
            test_cmd=str(required(module, "TEST_CMD")),
            bench_cmd=str(required(module, "BENCH_CMD")),
            log_dir=log_dir,
            timeouts=timeouts,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationFailure("config_error", f"invalid config.py: {error}", 2) from error


def required(module: ModuleType, name: str) -> object:
    if not hasattr(module, name):
        raise KeyError(f"missing {name}")
    value = getattr(module, name)
    if value is None or value == "":
        raise ValueError(f"{name} must not be empty")
    return value


def expanded_path(
    module: ModuleType, name: str, *, relative_to: Path | None = None
) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(required(module, name)))))
    if not path.is_absolute() and relative_to is not None:
        path = relative_to / path
    return path.resolve()


def validate_remote_dir(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or not REMOTE_PATH_PATTERN.fullmatch(value)
        or not path.is_absolute()
        or path == PurePosixPath("/")
        or ".." in path.parts
        or len(path.parts) < 3
    ):
        raise EvaluationFailure(
            "config_error",
            "REMOTE_DIR must be a safe absolute directory at least two levels below /",
            2,
        )


def parse_benchmark(output: str) -> tuple[Metric, Metric]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise EvaluationFailure("bench_parse_failed", f"invalid benchmark JSON: {error}", 8) from error
    if not isinstance(payload, list):
        raise EvaluationFailure("bench_parse_failed", "benchmark JSON must be a list", 8)

    prefill_rows = [
        row
        for row in payload
        if isinstance(row, dict)
        and positive_int(row.get("n_prompt"))
        and not positive_int(row.get("n_gen"))
    ]
    decode_rows = [
        row
        for row in payload
        if isinstance(row, dict)
        and positive_int(row.get("n_gen"))
        and not positive_int(row.get("n_prompt"))
    ]
    if len(prefill_rows) != 1 or len(decode_rows) != 1:
        raise EvaluationFailure(
            "bench_parse_failed",
            "benchmark JSON must contain exactly one prefill row and one decode row",
            8,
        )
    return metric_from_row(prefill_rows[0]), metric_from_row(decode_rows[0])


def metric_from_row(row: dict[object, object]) -> Metric:
    try:
        mean = float(row["avg_ts"])
        stddev = float(row["stddev_ts"])
        samples_value = row["samples_ts"]
        if not isinstance(samples_value, list) or not samples_value:
            raise ValueError("samples_ts must be a non-empty list")
        samples = tuple(float(value) for value in samples_value)
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationFailure(
            "bench_parse_failed", f"invalid benchmark metric: {error}", 8
        ) from error
    if (
        not math.isfinite(mean)
        or mean <= 0
        or not math.isfinite(stddev)
        or stddev < 0
        or any(not math.isfinite(sample) or sample <= 0 for sample in samples)
    ):
        raise EvaluationFailure(
            "bench_parse_failed", "benchmark metrics must be finite and positive", 8
        )
    return Metric(mean=mean, stddev=stddev, samples=samples)


def positive_int(value: object) -> bool:
    return isinstance(value, (int, float)) and value > 0


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def print_summary(
    *,
    status: str,
    commit: str,
    log_dir: Path | None,
    reason: str | None = None,
    prefill: Metric | None = None,
    decode: Metric | None = None,
) -> None:
    print("---")
    print(f"status: {status}")
    print(f"commit: {commit}")
    if prefill is None:
        print("prefill_tps: n/a")
    else:
        print(
            f"prefill_tps: {prefill.mean:.3f} ± {prefill.stddev:.3f} "
            f"(n={len(prefill.samples)})"
        )
    if decode is None:
        print("decode_tps: n/a")
    else:
        print(
            f"decode_tps: {decode.mean:.3f} ± {decode.stddev:.3f} "
            f"(n={len(decode.samples)})"
        )
    print(f"log: {log_dir if log_dir is not None else 'n/a'}")
    if reason:
        print(f"reason: {reason}")


def main() -> int:
    tool_dir = Path(__file__).resolve().parent
    evaluator: Evaluator | None = None
    try:
        settings = load_settings(tool_dir)
        evaluator = Evaluator(settings)
        prefill, decode = evaluator.evaluate()
    except EvaluationFailure as error:
        print_summary(
            status=error.status,
            commit=evaluator.commit if evaluator else "unknown",
            log_dir=evaluator.run_log_dir if evaluator else None,
            reason=error.reason,
        )
        return error.exit_code

    print_summary(
        status="ok",
        commit=evaluator.commit,
        log_dir=evaluator.run_log_dir,
        prefill=prefill,
        decode=decode,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
