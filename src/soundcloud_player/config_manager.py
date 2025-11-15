import os
import sys
from pathlib import Path
from typing import Any

import yaml


class ConfigManager:
    def __init__(self):
        if sys.platform == "darwin":
            data_root = Path.home() / "Library"
        elif sys.platform == "win32":
            data_root = os.getenv("LOCALAPPDATA")
        else:
            raise NotImplementedError("Only Windows and MacOS are supported")
        data_dir = Path(data_root) / "scplay"
        data_dir.mkdir(exist_ok=True, parents=True)
        self.cfg_file = data_dir / "config.yaml"
        if not self.cfg_file.exists():
            self.create()
        self.settings = self.load()
        if "oauth-token" not in self.settings:
            self.set_oauth_token()

    def create(self):
        print(f"Creating config file at '{self.cfg_file}'...")
        self.cfg_file.touch()

    def load(self) -> dict[str, Any]:
        with open(self.cfg_file, "r") as f:
            content = yaml.load(f, yaml.SafeLoader)
        return content or {}

    def update(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.write()

    def write(self):
        with open(self.cfg_file, "w") as f:
            yaml.dump(self.settings, f)

    def set_oauth_token(self) -> None:
        self.update(
            "oauth-token",
            input(
                "Please enter your SoundCloud oauth token. You can find it in your"
                " browser's session storage: "
            ),
        )
