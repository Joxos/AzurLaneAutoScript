"""Static checks on the docker packaging (no docker daemon needed).

The image cannot be built on this machine (no docker), so these checks catch
the mistakes that would only show up as a failed build: a COPY of a path the
.dockerignore excludes, an entry point that no longer exists, or a context
that does not contain what the Dockerfile copies.

Run: .venv\\Scripts\\python.exe dev_tools/verify_docker_packaging.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [ROOT / "deploy" / "docker" / "Dockerfile", ROOT / "deploy" / "docker" / "Dockerfile.cn"]
IGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "docker-compose.yml"


def ignored_paths() -> list[str]:
    out: list[str] = []
    for line in IGNORE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def main() -> int:
    errors: list[str] = []
    ignores = ignored_paths()

    for dockerfile in DOCKERFILES:
        if not dockerfile.is_file():
            errors.append(f"missing {dockerfile.relative_to(ROOT)}")
            continue
        text = dockerfile.read_text(encoding="utf-8")
        copies = re.findall(r"^COPY\s+(?:--from=\S+\s+)?(\S+)\s+(\S+)", text, re.M)
        for src, _dst in copies:
            if src.startswith("--from") or "$" in src or src.startswith("/"):
                continue  # copied from an earlier stage (absolute = inside the image)
            if any(src.rstrip("/") == pat.rstrip("/") for pat in ignores):
                errors.append(f"{dockerfile.name}: COPY {src} is excluded by .dockerignore")
            elif not (ROOT / src).exists():
                errors.append(f"{dockerfile.name}: COPY {src} does not exist in the repo")
        if "webapp/dist" not in text:
            errors.append(f"{dockerfile.name}: the built SPA is not copied into the image")
        if '"--no-open"' not in text:
            errors.append(f"{dockerfile.name}: CMD should pass --no-open (no browser in a container)")

    compose = COMPOSE.read_text(encoding="utf-8")
    if not re.search(r"context:\s*\.\s*$", compose, re.M):
        errors.append("docker-compose.yml: the build context must be the repository root ('.')")
    if "deploy/docker/Dockerfile" not in compose:
        errors.append("docker-compose.yml: dockerfile path is wrong")

    for error in errors:
        print(f"  {error}")
    if errors:
        print(f"DOCKER PACKAGING: {len(errors)} problem(s)")
        return 1
    print("DOCKER PACKAGING: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
