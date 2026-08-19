# LXLoop

[English](README.md) | 中文

> **说明：** LXLoop 的灵感来自 Andrej Karpathy 的 [autoresearch](https://github.com/karpathy/autoresearch)。

LXLoop 是一个小型、由人主导的研究工具，用于发现 `llama.cpp` 中 CPU 推理性能的改进机会。

你选择一个聚焦的研究方向。随后，具备 Shell 操作能力的 coding agent 会在专用的 `llama.cpp` worktree 中运行一系列实验：每次测试一个优化假设，并在真实的 RISC-V 硬件上测量每个候选方案。

## 工作原理

```text
用户确定研究方向
              ↓
Agent 提出并提交一项更改
              ↓
LXLoop 构建并部署它
              ↓
目标设备运行正确性测试和 llama-bench
              ↓
Agent 保留或丢弃候选方案
              ↓
从当前最佳基线重新开始
```

coding agent 编排整个研究循环。Git 记录候选状态和成功的历史记录，`evaluate.py` 则提供从已提交源代码到目标设备测量结果的固定路径。

每次实验只修改 `ggml/src/ggml-cpu/`。agent 会在评估前提交候选方案，评估器会以机制化方式拒绝脏 worktree 或越过此边界的更改。候选方案必须先通过已配置的正确性命令，才能进行 benchmark。

工作站保存所有源代码和 Git 状态，负责交叉编译候选方案、部署它们并存储结果。RISC-V 目标设备只运行已部署的正确性和 benchmark 命令；它不需要编译器、Python 或互联网访问。

## 要求

你需要：

- 一个本地 `llama.cpp` 仓库；
- 一个在 `lxloop/*` 分支上的专用 linked worktree；
- 可用的 RISC-V 交叉工具链和 sysroot；
- 到目标设备的 SSH 和 SCP 访问权限；
- 已配置的正确性命令和 `llama-bench` 命令；
- Python 3；
- 具备 Shell 操作能力的 coding agent。

`rsync` 是可选的。目标设备应专用于该研究运行，以免其他负载影响测量结果。

## 快速开始

### 1. 创建专用 worktree

选择一个 baseline，将其解析为完整 commit ID，并在独立 worktree 中创建 `lxloop/*` 分支：

```bash
cd /path/to/llama.cpp

git worktree add \
  -b lxloop/my-research-run \
  /path/to/llama.cpp-lxloop \
  <full-baseline-commit-id>
```

不要使用日常开发 checkout。该 worktree 必须以干净状态开始，并且从已配置的 baseline 派生。

### 2. 配置 LXLoop

复制示例配置：

```bash
cp config.example.py config.py
```

编辑 `config.py`，填写：

- 专用 worktree 的路径和完整 baseline commit ID；
- SSH 目标设备和远程部署目录；
- 交叉编译命令及其生成的部署目录；
- 用于识别交叉编译器的命令；
- 远程正确性和 benchmark 命令；
- 适合各阶段的 timeout。

构建命令必须生成一个完整的部署目录，其中包含目标设备所需的每个二进制文件和运行时库。

> **警告：** 部署期间会替换 `REMOTE_DIR`。请使用专用目录，且其中不包含需要保留的数据。

### 3. 定义研究方向

编辑 `task.md`，写明你希望 agent 调查的具体问题。包括主要指标、允许的取舍、实现约束，以及与该工作相关的任何硬件或环境信息。

请保持方向有界。LXLoop 旨在解决由工程师选定的问题，而不是自行选择优化目标。

`config.py` 和 `task.md` 都保留在本地并由 Git 忽略，因此可以包含机器特定或私有的运行上下文。

### 4. 从未修改的 baseline 开始

要求你的 coding agent 阅读 `program.md` 中的永久研究规则以及 `task.md` 中的当前方向：

```text
Read program.md and task.md completely. Set up a new research run, run and
record the untouched baseline, then stop so I can review it before continuing.
```

首次评估也是对 worktree、交叉工具链、部署 payload、目标运行时、正确性命令和 benchmark 命令的端到端 smoke test。在允许实验循环无人值守运行之前，请先审阅它。

## 评估结果

可从 LXLoop 仓库运行评估器：

```bash
python3 evaluate.py
```

成功评估会生成简洁的摘要：

```text
---
status: ok
commit: b4e2f1a
prefill_tps: 142.310 ± 1.850 (n=10)
decode_tps: 9.874 ± 0.041 (n=10)
log: logs/20260817T031412Z_b4e2f1a
```

已配置的正确性命令具有决定性：只有当该命令成功时，候选方案才会进行 benchmark。benchmark 同时报告 prefill 和 decode 吞吐量，并由 agent 根据 `task.md` 中的研究方向和 `program.md` 中的永久规则判断结果。

保留的候选方案会成为下一个 baseline，并留在该分支的 Git 历史中。被拒绝的候选方案会在 agent 返回最后一次保留的 commit 前被记录。

agent 在 `results.tsv` 中维护精简的实验台账，而完整的构建、部署、正确性和 benchmark 输出存储在 `logs/` 下。Git 仍然是成功改进的权威记录。
