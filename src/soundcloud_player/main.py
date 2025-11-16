import argparse
import re

from soundcloud_player.config_manager import ConfigManager
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


def download_likes(
    sc_client: SoundCloudClient, args: argparse.Namespace, cfg_manager: ConfigManager
):
    dst_path = cfg_manager.get_local_lib()
    all_mp3s = list(dst_path.rglob("*.mp3"))
    all_track_ids = []
    for file in all_mp3s:
        matches = re.findall(r"_([0-9]+)\.mp3", str(file.name))
        if matches:
            all_track_ids.append(int(matches[0]))
    for track in sc_client.get_liked_tracks():
        if track.id not in all_track_ids:
            output = sc_client.download_track(track_id=track.id, dst_path=dst_path)
            print("Successfully downloaded " + output.name)
    print("All liked tracks downloaded")


def main():
    args = create_parser().parse_args()
    cfg_mngr = ConfigManager(reset=args.reset_config)
    sc_client = SoundCloudClient(cfg_mngr.get_oauth_token())
    args.func(sc_client=sc_client, args=args, cfg_manager=cfg_mngr)


if __name__ == "__main__":
    main()
