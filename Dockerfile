FROM mlebench-env:latest

ENV NONROOT_USER=nonroot
ENV METHOD=LoongFlow
ENV LOONGFLOW_ENV_NAME=${METHOD}

USER root

RUN apt-get update && apt-get install -y \
    git-lfs \
    && git lfs install --system \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER ${NONROOT_USER}

COPY --chown=${NONROOT_USER}:${NONROOT_USER} requirements_framework.txt /tmp/requirements_framework.txt

RUN micromamba create -y -n "${LOONGFLOW_ENV_NAME}" \
        python=3.11 \
        pip \
        wheel \
        setuptools \
        packaging \
        ninja \
        git \
    && micromamba clean --all --yes

RUN micromamba run -n "${LOONGFLOW_ENV_NAME}" pip install --no-cache-dir -r /tmp/requirements_framework.txt \
    && micromamba clean --all --yes

RUN git clone https://github.com/kibrq/mle-bench.git /tmp/mle-bench \
    && cd /tmp/mle-bench \
    && git lfs pull \
    && micromamba run -n "${LOONGFLOW_ENV_NAME}" pip install --no-cache-dir /tmp/mle-bench \
    && rm -rf /tmp/mle-bench \
    && micromamba clean --all --yes

RUN mkdir -p /home/${NONROOT_USER}/${METHOD}

USER root
