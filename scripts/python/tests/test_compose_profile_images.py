#!/usr/bin/env python3
"""Every local image a compose profile needs must be built inside that profile.

`volume-init` pinned `image: vibe-squad:runtime` with no build stanza. Under
`--profile runtime` the daemon service happened to build that tag first, so the
gap was invisible; under `--profile tools` nothing built it and compose fell
back to PULLING vibe-squad:runtime from Docker Hub, which does not exist.
Measured with `docker compose --profile tools config --images`: the tools
profile needed two images and built one.

Also pins the Dockerfile claims docs/install/container.md makes about it.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "compose.yaml"
DOCKERFILE = ROOT / "Dockerfile"
LOCAL_PREFIX = "vibe-squad:"


class ComposeProfileImages(unittest.TestCase):
    def setUp(self) -> None:
        self.services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
        self.dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    def _members(self, profile: str) -> dict:
        return {
            name: svc
            for name, svc in self.services.items()
            if profile in svc.get("profiles", [])
        }

    def test_local_images_are_built_within_their_profile(self) -> None:
        profiles = {p for svc in self.services.values() for p in svc.get("profiles", [])}
        self.assertTrue(profiles, "compose.yaml declares no profiles")
        for profile in sorted(profiles):
            members = self._members(profile)
            built = {
                svc["image"]
                for svc in members.values()
                if svc.get("build") and svc.get("image")
            }
            for name, svc in members.items():
                image = svc.get("image", "")
                if not image.startswith(LOCAL_PREFIX):
                    continue
                self.assertIn(
                    image,
                    built,
                    f"profile {profile!r}: service {name!r} needs {image}, which no "
                    f"service in that profile builds — compose would try to pull it",
                )

    def test_build_targets_are_real_dockerfile_stages(self) -> None:
        stages = set(
            re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", self.dockerfile, re.MULTILINE | re.IGNORECASE)
        )
        for name, svc in self.services.items():
            build = svc.get("build")
            if isinstance(build, dict) and build.get("target"):
                self.assertIn(
                    build["target"],
                    stages,
                    f"service {name!r} targets a stage the Dockerfile does not define",
                )

    def test_uv_sync_is_locked_in_every_stage(self) -> None:
        # docs/install/container.md sells the image on "a locked `uv sync`".
        for line in re.findall(r"^RUN uv sync.*$", self.dockerfile, re.MULTILINE):
            self.assertIn("--locked", line, f"unlocked dependency install: {line!r}")

    def test_venv_bin_is_on_path(self) -> None:
        # `bin/test` resolves .venv itself, but CI runs bare `python -m unittest`
        # through the entrypoint, which otherwise lands on the base interpreter.
        paths = re.findall(r'^\s*PATH="([^"]+)"', self.dockerfile, re.MULTILINE)
        self.assertTrue(paths, "Dockerfile sets no PATH")
        for value in paths:
            self.assertIn("/squad/.venv/bin", value.split(":"))


if __name__ == "__main__":
    unittest.main()
