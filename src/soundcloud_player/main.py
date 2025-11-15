import argparse

from soundcloud_player.config_manager import ConfigManager
from soundcloud_player.player import Player
from soundcloud_player.soundcloud_client import SoundCloudClient


def create_parser():
    parser = argparse.ArgumentParser(
        description="Stream music from your SoundCloud feed or likes"
    )
    parser.add_argument(
        "--min-track-length",
        "-m",
        help="Minimum track length to filter feed on [minutes]",
        default=30,
        type=int,
    )
    parser.add_argument(
        "--reset-config", "-r", help="Reset config", action="store_true"
    )
    return parser


def main():
    args = create_parser().parse_args()
    cfg = ConfigManager()
    if args.reset_config:
        cfg.set_oauth_token()
    client = SoundCloudClient(cfg.settings["oauth-token"])
    app = Player(sc_client=client, min_track_length_sec=args.min_track_length * 60)
    app.run()


if __name__ == "__main__":
    main()
