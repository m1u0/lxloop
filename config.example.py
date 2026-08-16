"""Copy this file to config.py and replace every example value."""

# Dedicated linked llama.cpp worktree used only for this research run.
LLAMA_DIR = "/path/to/llama.cpp-autoresearch"
# Resolve the desired company branch or tag once, then paste its full commit ID.
# A movable branch name is rejected so an overnight run cannot change baselines.
UPSTREAM_REF = "0123456789abcdef0123456789abcdef01234567"

# SSH host alias. Put identity, user, and port details in ~/.ssh/config.
TARGET = "riscv-lab"
# This directory is exclusively owned by lxloop. It is replaced during deployment.
REMOTE_DIR = "/data/lxloop/candidate"

# Run from LLAMA_DIR on the workstation. It must cross-compile and stage one
# complete payload containing llama-bench, correctness-test binaries, and all
# target runtime libraries they require.
BUILD_CMD = """
cmake -S . -B build-riscv \
  -DCMAKE_TOOLCHAIN_FILE=/path/to/riscv-toolchain.cmake \
  -DCMAKE_BUILD_TYPE=Release &&
cmake --build build-riscv --parallel &&
cmake --install build-riscv --prefix "$PWD/build-riscv/lxloop-deploy"
""".strip()

# Absolute, or relative to LLAMA_DIR. evaluate.py transfers its contents opaquely.
DEPLOY_DIR = "build-riscv/lxloop-deploy"

# Required; output is captured in each evaluation's metadata log.
COMPILER_VERSION_CMD = "riscv64-unknown-linux-gnu-g++ --version"

# Run on the target with REMOTE_DIR as the working directory.
# Adjust paths to match the payload produced by BUILD_CMD.
TEST_CMD = "./bin/test-backend-ops -b CPU"
BENCH_CMD = (
    "./bin/llama-bench "
    "-m /data/models/model.gguf "
    "-p 512 -n 128 -t 64 -b 512 -r 5 -o json"
)

# Absolute, or relative to the lxloop repository.
LOG_DIR = "logs"

TIMEOUTS = {
    "build": 1800,
    "sync": 300,
    "test": 900,
    "bench": 1800,
}
