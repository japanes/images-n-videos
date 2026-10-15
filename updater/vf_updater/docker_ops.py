"""Thin wrapper over the docker CLI (docker.sock is mounted into the container)."""

from __future__ import annotations

import json
import os
import subprocess

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


class DockerError(Exception):
    pass


def _tail(text: str, limit: int = 2000) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


class Docker:
    def __init__(self, binary: str = "docker"):
        self.binary = binary

    def run(self, args, timeout=600, env=None, check=True) -> subprocess.CompletedProcess:
        full_env = None
        if env is not None:
            full_env = dict(os.environ)
            full_env.update(env)
        try:
            proc = subprocess.run(
                [self.binary, *args], capture_output=True, text=True, timeout=timeout,
                env=full_env, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise DockerError(f"docker {' '.join(args[:2])} timed out after {timeout}s") from None
        except OSError as exc:
            raise DockerError(f"cannot run docker: {exc}") from None
        if check and proc.returncode != 0:
            raise DockerError(_tail(proc.stderr or proc.stdout) or f"docker exited {proc.returncode}")
        return proc

    # images
    def image_exists(self, ref: str) -> bool:
        return self.run(["image", "inspect", "--format", "{{.Id}}", ref], timeout=60,
                        check=False).returncode == 0

    def image_id(self, ref: str):
        proc = self.run(["image", "inspect", "--format", "{{.Id}}", ref], timeout=60, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def pull(self, ref: str, timeout=3600):
        self.run(["pull", "--quiet", ref], timeout=timeout)

    def tag(self, src: str, dst: str):
        self.run(["tag", src, dst], timeout=60)

    def read_file_from_image(self, image: str, path: str) -> str:
        proc = self.run(["run", "--rm", "--no-healthcheck", "--network", "none", "--entrypoint",
                         "cat", image, path],
                        timeout=120)
        return proc.stdout

    # containers
    def project_containers(self, project: str) -> list:
        """Containers of a compose project: [{id, name, service, state, image}]."""
        fmt = (
            '{"id":"{{.ID}}","name":"{{.Names}}","state":"{{.State}}",'
            '"image":"{{.Image}}","service":"{{.Label "' + COMPOSE_SERVICE_LABEL + '"}}"}'
        )
        proc = self.run(
            ["ps", "-a", "--no-trunc", "--filter", f"label={COMPOSE_PROJECT_LABEL}={project}",
             "--format", fmt],
            timeout=60,
        )
        items = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except ValueError:
                    continue
        return items

    def container_state(self, name: str):
        """'running', 'exited', ... or None when there is no such container."""
        proc = self.run(["container", "inspect", "--format", "{{.State.Status}}", name],
                        timeout=60, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def container_image_id(self, name: str):
        proc = self.run(["container", "inspect", "--format", "{{.Image}}", name], timeout=60,
                        check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def remove_container(self, name: str):
        self.run(["rm", "-f", name], timeout=120, check=False)

    def stop_containers(self, ids, timeout_s: int = 30):
        ids = [i for i in ids if i]
        if ids:
            self.run(["stop", "-t", str(timeout_s), *ids], timeout=timeout_s + 120)

    def run_detached(self, image: str, args, name: str, network: str, volume: str,
                     env: dict, socket: str = "/var/run/docker.sock"):
        cmd = ["run", "-d", "--rm", "--no-healthcheck", "--name", name, "--network", network,
               "-v", f"{socket}:/var/run/docker.sock", "-v", f"{volume}:/data"]
        for key, value in sorted(env.items()):
            cmd += ["-e", f"{key}={value}"]
        cmd += [image, *args]
        return self.run(cmd, timeout=300).stdout.strip()

    # compose
    def compose_up(self, project: str, compose_file: str, env: dict, timeout=3600):
        self.run(["compose", "-p", project, "-f", compose_file, "up", "-d", "--remove-orphans"],
                 timeout=timeout, env=env)

    def compose_config(self, project: str, compose_file: str, env: dict):
        self.run(["compose", "-p", project, "-f", compose_file, "config", "--quiet"],
                 timeout=120, env=env)
