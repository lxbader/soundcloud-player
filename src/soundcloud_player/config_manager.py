import os
import sys
from pathlib import Path
from typing import Any

import yaml


class ConfigManager:
    def __init__(self, reset: bool):
        self.reset = reset
        if sys.platform == "darwin":
            data_root = Path.home() / "Library"
        elif sys.platform == "win32":
            data_root = os.getenv("LOCALAPPDATA")
        else:
            data_root = os.getenv("XDG_DATA_HOME") or (Path.home() / ".local/share")
        data_dir = Path(data_root) / "scplay"  # type: ignore
        data_dir.mkdir(exist_ok=True, parents=True)
        self.cfg_file = data_dir / "config.yaml"
        if not self.cfg_file.exists():
            self.create()
        self.settings = self.load()

    def create(self):
        print(f"Creating config file at '{self.cfg_file}'...")
        self.cfg_file.touch()

    def load(self) -> dict[str, Any]:
        with open(self.cfg_file, "r") as f:
            content = yaml.load(f, yaml.SafeLoader)
        return content or {}

    def get(self, key: str, prompt: str) -> str:
        if key in self.settings:
            if not self.reset:
                return self.settings[key]
            resp = input(
                f"Parameter '{key}' is already populated with value"
                f" '{self.settings[key]}', do you want to overwrite it? Only 'yes' is"
                " accepted [no]"
            )
            if resp != "yes":
                print(f"Leaving '{key}' untouched")
                return self.settings[key]
        self.settings[key] = input(prompt + " ")
        self.write()
        return self.settings[key]

    def write(self):
        with open(self.cfg_file, "w") as f:
            yaml.dump(self.settings, f)

    def get_oauth_token(self) -> str:
        return self.get(
            "oauth-token",
            "Please enter your SoundCloud oauth token. You can find it in your"
            " browser's session storage:",
        )

    def get_local_lib(self) -> Path:
        param = "local-lib"
        prompt = "Please provide the location of your local SoundCloud library:"
        local_lib = Path(self.get(param, prompt))
        while not local_lib.exists():
            print(
                f"Directory '{local_lib}' does not exist, please ensure it is created"
            )
            self.settings.pop(param)
            local_lib = Path(self.get(param, prompt))
        return local_lib

    def get_classification_config(self) -> Path:
        param = "classification-cfg"
        prompt = (
            "Please provide the location of your library classification config yml:"
        )
        class_cfg = Path(self.get(param, prompt))
        while not class_cfg.exists():
            print(f"File '{class_cfg}' does not exist")
            self.settings.pop(param)
            class_cfg = Path(self.get(param, prompt))
        return class_cfg
