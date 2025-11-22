import argparse
import re
import shutil
import subprocess
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from soundcloud_player.config_manager import ConfigManager
from soundcloud_player.soundcloud_client import SoundCloudClient, Track


def sanitise_string(s: str) -> str:
    return re.sub(r"\W+", "_", unicodedata.normalize("NFC", str.lower(s))).strip("_")


def download_track(
    track: Track, sc_client: SoundCloudClient, dst_path: Path, progress: Progress
) -> Path:
    url = sc_client.get_streamable_link(track_id=track.id)
    title = sanitise_string(track.title)
    artist = sanitise_string(track.artist)
    artist = "" if artist in title else artist + "_"
    filename = artist + title + "_" + str(track.id) + ".mp3"
    output_path = dst_path / filename

    task = progress.add_task(filename, total=track.duration_secs)
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir).joinpath("scdl-download.mp3").absolute()
        with subprocess.Popen(
            [
                "ffmpeg",
                "-i",
                url,
                "-c",
                "copy",
                str(temp_path),
                "-loglevel",
                "error",
                "-progress",
                "-",
            ],
            universal_newlines=True,
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as p:
            for line in p.stdout or []:
                if "out_time=" not in line:
                    continue
                h, m, s = line.removeprefix("out_time=").split(".")[0].split(":")
                progress.update(task, completed=int(h) * 3600 + int(m) * 60 + int(s))
        dst_path.mkdir(exist_ok=True)
        shutil.move(temp_path, output_path)
    return output_path


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
    with Progress(
        TextColumn("[white]{task.description}[/white]"),
        BarColumn(),
        TaskProgressColumn(text_format="[white]{task.percentage:>3.0f}%[/white]"),
        TimeElapsedColumn(),
    ) as progress:
        dl_func = partial(
            download_track, sc_client=sc_client, dst_path=dst_path, progress=progress
        )
        with ThreadPoolExecutor(max_workers=5) as executor:
            for track in sc_client.get_liked_tracks():
                if track.id not in all_track_ids:
                    executor.submit(dl_func, track)
    print("All liked tracks downloaded")
