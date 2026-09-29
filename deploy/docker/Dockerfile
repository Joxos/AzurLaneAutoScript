# Alas docker image.
#
#   docker build -f deploy/docker/Dockerfile -t alas:latest .
#   docker run -v ${PWD}:/app/AzurLaneAutoScript -p 22267:22267 --name alas -it --rm alas
#
# Two stages: the Svelte SPA is built with node and copied into the Python
# image, so the container serves the UI too. Before, webapp/dist only existed
# if the host happened to have run `pnpm build` - and dist is gitignored, so a
# fresh checkout produced an API-only image that looked broken.
#
# Use Dockerfile.cn for mainland-China mirrors of apt/pypi.

# ---------- stage 1: frontend ----------
FROM node:24-bookworm-slim AS webapp

WORKDIR /app/webapp
COPY webapp/package.json webapp/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY webapp/ ./
RUN pnpm build

# ---------- stage 2: runtime ----------
FROM python:3.13-slim-bookworm

WORKDIR /app/AzurLaneAutoScript

COPY requirements.txt /tmp/requirements.txt

# Initial download of UiAutomator2 is slow outside of China using appetizer mirror, switch to GitHub
RUN apt update \
 && apt install -y git adb libgomp1 openssh-client \
 && apt install -y build-essential pkg-config \
 && apt install -y libavformat-dev libavcodec-dev libavdevice-dev \
 && apt install -y libavutil-dev libswscale-dev libswresample-dev libavfilter-dev \
 && git config --global --add safe.directory '*' \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && rm -r ~/.cache/pip

COPY . /app/AzurLaneAutoScript
# The built SPA wins over whatever the build context carried.
COPY --from=webapp /app/webapp/dist /app/AzurLaneAutoScript/webapp/dist

# No browser to open inside a container; whoever maps the port serves the UI.
EXPOSE 22267
CMD ["python", "-m", "module.cli", "run", "web", "--no-open", "--host", "0.0.0.0"]
