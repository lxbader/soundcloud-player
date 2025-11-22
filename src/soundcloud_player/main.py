import argparse

from soundcloud_player.config_manager import ConfigManager
from soundcloud_player.download import download_likes
from soundcloud_player.player import Player
from soundcloud_player.soundcloud_client import SoundCloudClient


def create_parser():
    parser = argparse.ArgumentParser(
        description="Stream music from your SoundCloud feed or likes"
    )
    parser.add_argument(
        "--reset-config", "-r", help="Reset config", action="store_true"
    )
    subparsers = parser.add_subparsers(required=True)

    parser_start = subparsers.add_parser("start")
    parser_start.add_argument(
        "--min-track-length",
        "-m",
        help="Minimum track length to filter feed on [minutes]",
        default=30,
        type=int,
    )
    parser_start.set_defaults(func=start_player)

    parser_download = subparsers.add_parser("download")
    parser_download.set_defaults(func=download_likes)
    return parser


def start_player(sc_client: SoundCloudClient, args: argparse.Namespace, **kwargs):
    app = Player(sc_client=sc_client, min_track_length_sec=args.min_track_length * 60)
    app.run()


def main():
    args = create_parser().parse_args()
    cfg_mngr = ConfigManager(reset=args.reset_config)
    sc_client = SoundCloudClient(cfg_mngr.get_oauth_token())
    args.func(sc_client=sc_client, args=args, cfg_manager=cfg_mngr)


if __name__ == "__main__":
    main()
