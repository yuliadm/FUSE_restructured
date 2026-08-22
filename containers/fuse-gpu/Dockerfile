# syntax=docker/dockerfile:1.7

# One CUDA 12.4 / torch 2.5.1 runtime for VGGT-Omega, Hunyuan3D-2.1 shape,
# and Kaolin alignment. All three already agreed on this torch/CUDA pair
# except the old VGGT container; VGGT-Omega removes that constraint.
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel

ARG DEBIAN_FRONTEND=noninteractive
ARG USER_ID=1000
ARG GROUP_ID=1000
ARG VGGT_OMEGA_REF=main
ARG LIGHTGLUE_REF=2f23ca2ea9638cecad7f7220795210fc6b8353c3
ARG HUNYUAN_REF=82920d643c0dc2f7bfd7255f45f62d386edfe60c
ARG KAOLIN_VERSION=0.18.0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    CUDA_HOME=/usr/local/cuda \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH} \
    HOME=/home/fuse \
    HF_HOME=/workspace/.cache/huggingface \
    HF_HUB_CACHE=/workspace/.cache/huggingface/hub \
    TORCH_HOME=/workspace/.cache/torch \
    U2NET_HOME=/workspace/.cache/rembg \
    XDG_CACHE_HOME=/workspace/.cache/xdg \
    MPLCONFIGDIR=/workspace/.cache/matplotlib \
    JUPYTER_CONFIG_DIR=/workspace/.cache/jupyter \
    IPYTHONDIR=/workspace/.cache/ipython \
    PYTHONPATH=/opt/vggt-omega:/opt/Hunyuan3D-2.1/hy3dshape:/workspace \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Union of the vggt / hunyuan / kaolin apt lists.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        ffmpeg \
        git \
        libegl1 \
        libgl1 \
        libglib2.0-0 \
        libglu1-mesa \
        libgomp1 \
        libsm6 \
        libx11-6 \
        libxext6 \
        libxrender1 \
        ninja-build \
        wget \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv --system-site-packages "${VIRTUAL_ENV}" \
    && python -m pip install --upgrade \
        "pip==25.1.1" \
        "setuptools==75.8.0" \
        "wheel==0.45.1"

# --- VGGT-Omega -------------------------------------------------------
RUN git clone https://github.com/facebookresearch/vggt-omega.git /opt/vggt-omega \
    && git -C /opt/vggt-omega checkout --detach "${VGGT_OMEGA_REF}"
WORKDIR /opt/vggt-omega
# TODO: inspect requirements.txt after the Step 3 smoke test and strip/adjust
# any torch/torchvision line so it doesn't fight the base image's pinned
# 2.5.1 build. `grep -vi '^torch' requirements.txt` is a reasonable first cut.
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir -e .

# Bundle-adjustment extras carried over from the old vggt container (kept in
# case a later stage wants demo_colmap.py-style refinement).
RUN python -m pip install --no-cache-dir \
        hydra-core \
        omegaconf \
        pyceres==2.3 \
        pycolmap==3.10.0 \
        pydantic==2.10.6 \
        scipy \
        "lightglue @ git+https://github.com/jytime/LightGlue.git@${LIGHTGLUE_REF}"

# --- Hunyuan3D-2.1 shape ------------------------------------------------
COPY requirements-hunyuan-shape.txt /tmp/requirements-hunyuan-shape.txt
RUN python -m pip install --no-cache-dir --prefer-binary -r /tmp/requirements-hunyuan-shape.txt

RUN git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git /opt/Hunyuan3D-2.1 \
    && git -C /opt/Hunyuan3D-2.1 checkout --detach "${HUNYUAN_REF}"

# --- Kaolin --------------------------------------------------------------
RUN python -m pip install --no-cache-dir --prefer-binary \
        "kaolin==${KAOLIN_VERSION}" \
        -f "https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu124.html"

# --- Shared / notebook layer ---------------------------------------------
COPY requirements-shared.txt /tmp/requirements-shared.txt
RUN python -m pip install --no-cache-dir --prefer-binary -r /tmp/requirements-shared.txt

# Fail the build, not a teammate's notebook, if anything is unimportable
# or the resolver silently picked an incompatible version.
RUN python -m pip check \
    && python -c "\
from importlib.metadata import version; \
import kaolin, open3d, torch, torchvision, trimesh; \
from vggt_omega.models import VGGTOmega; \
from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline; \
from hy3dshape.rembg import BackgroundRemover; \
assert torch.__version__.startswith('2.5.1'); \
assert torchvision.__version__.startswith('0.20.1'); \
assert torch.version.cuda == '12.4'; \
assert version('kaolin') == '${KAOLIN_VERSION}'; \
print('FUSE GPU (VGGT-Omega + Hunyuan + Kaolin) installation OK')" \
    && python -m jupyterlab --version

RUN groupadd --gid "${GROUP_ID}" fuse \
    && useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --create-home --shell /bin/bash fuse \
    && mkdir -p /workspace/data /workspace/notebooks /workspace/.cache \
    && chown -R fuse:fuse /workspace /home/fuse

USER fuse
WORKDIR /workspace

EXPOSE 8890

CMD ["/bin/bash"]