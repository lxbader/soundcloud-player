import argparse
import os
import sys
from pathlib import Path

import yaml

from soundcloud_player.player import Player
from soundcloud_player.soundcloud_client import SoundCloudClient


def create_parser():
    parser = argparse.ArgumentParser(description="Stream music from URLs")
    # parser.add_argument(
    #     "username", help="SoundCloud username whose liked tracks to play"
    # )
    return parser


class ConfigManager:
    def __init__(self):
        if sys.platform == "darwin":
            data_root = "~/Library/Application Support"
        elif sys.platform == "win32":
            data_root = os.getenv("LOCALAPPDATA")
        else:
            raise NotImplementedError("Only Windows and MacOS are supported")
        data_dir = Path(data_root) / "scplay"
        data_dir.mkdir(exist_ok=True)
        self.cfg_file = data_dir / "config.yaml"
        if not self.cfg_file.exists():
            self.create()
        self.settings = self.load()
        self.maybe_add_oauth_token()
        self.write()

    def create(self):
        print(f"Creating config file at '{self.cfg_file}'...")
        self.cfg_file.touch()

    def load(self) -> dict:
        with open(self.cfg_file, "r") as f:
            content = yaml.load(f, yaml.SafeLoader)
        return content or {}

    def maybe_add_oauth_token(self) -> dict:
        if "oauth-token" not in self.settings:
            self.settings["oauth-token"] = input(
                "Please enter your SoundCloud oauth token: "
            )

    def write(self):
        with open(self.cfg_file, "w") as f:
            yaml.dump(self.settings, f)


def main():
    args = create_parser().parse_args()
    cfg = ConfigManager()
    client = SoundCloudClient(cfg.settings["oauth-token"])
    app = Player(sc_client=client)
    app.run()


if __name__ == "__main__":
    main()
