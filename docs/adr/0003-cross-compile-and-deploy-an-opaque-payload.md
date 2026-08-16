# Cross-compile and deploy an opaque payload

Candidates are cross-compiled on the workstation because the RISC-V target has no compilation tools. The configured build command must produce one complete deploy directory that lxloop treats as opaque, then `evaluate.py` transfers it with `rsync` when available or recreates the dedicated remote directory and uses `scp` otherwise; this keeps toolchain and packaging details outside the research loop while preventing stale remote artifacts from contaminating measurements.
