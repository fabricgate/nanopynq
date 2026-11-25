FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# The simulator CI's Sim job uses: Icarus Verilog 14 from oss-cad-suite (Ubuntu's apt 12.0 cannot elaborate
# ddr3_calib.sv). Keep the release the same as in .github/workflows/ci.yaml. About 700 MB to download.
ARG OSS_CAD_SUITE_RELEASE=2026-11-15
ARG OSS_CAD_SUITE_DATE=20261115
RUN case "$(dpkg --print-architecture)" in amd64) arch=x64 ;; arm64) arch=arm64 ;; *) exit 1 ;; esac \
    && curl -fsSL "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_CAD_SUITE_RELEASE}/oss-cad-suite-linux-${arch}-${OSS_CAD_SUITE_DATE}.tgz" \
    | tar -xz -C /opt
# Last on PATH: the suite carries its own python3, which must not stand in for the system one.
ENV PATH="${PATH}:/opt/oss-cad-suite/bin"

# uv installs the Python that pyproject.toml asks for, then the project (uv.lock).
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/
