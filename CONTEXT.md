# lxloop

lxloop is a human-directed research tool that empirically searches for inference-performance improvements in a separately checked-out `llama.cpp` repository.

## Language

**Research run**:
An extended sequence of experiments pursuing one engineer-defined research direction from one known baseline.
_Avoid_: Job, campaign, autonomous optimization task

**Research direction**:
The focused optimization problem and constraints supplied by an engineer for one research run.
_Avoid_: Global objective, agent-selected target

**Permanent research rules**:
The stable instructions governing every research run, including scope, evaluation, Git, and recovery behavior.
_Avoid_: Configuration, workflow definition

**Experiment**:
One hypothesis-driven change followed by correctness and performance evaluation on the target hardware.
_Avoid_: Run, trial suite

**Candidate**:
The committed `ggml-cpu` change evaluated by an experiment.
_Avoid_: Patch, build

**Baseline**:
The last known-good candidate against which the next candidate is evaluated. A kept candidate becomes the next baseline.
_Avoid_: Upstream branch, original implementation

**Keep**:
The decision that a correct candidate improves the configured performance objective enough to become the next baseline.
_Avoid_: Pass, merge

**Reject**:
The decision that a candidate must not advance the baseline because it is incorrect, broken, or insufficiently faster.
_Avoid_: Failure, revert

**Subject checkout**:
The dedicated `llama.cpp` Git worktree whose `ggml/src/ggml-cpu/` subtree is modified during research.
_Avoid_: lxloop repository, engineer's working checkout

**Evaluator**:
The fixed local program that guards the edit boundary, cross-compiles a candidate, deploys it, invokes remote correctness and benchmark commands, and reports a stable result.
_Avoid_: Orchestrator, workflow engine, agent

**Deploy directory**:
The complete workstation-produced payload transferred to the target for correctness and benchmark execution.
_Avoid_: Build tree, source checkout

**Target**:
The proprietary RISC-V machine on which candidate correctness and inference performance are measured.
_Avoid_: Build server, worker
