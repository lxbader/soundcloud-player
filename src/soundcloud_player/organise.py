import argparse
from dataclasses import dataclass
from pathlib import Path

import yaml
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from rich import print
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from thefuzz import fuzz  # type: ignore
from unidecode import unidecode

from soundcloud_player.config_manager import ConfigManager
from soundcloud_player.soundcloud_client import SoundCloudClient

SIM_LIMIT = 90
COLOURS = ["#D35400", "#E67E22", "#F39C12", "#F1C40F", "#2ECC71"]


@dataclass
class TrackGroup:
    album: str
    phrases: list[str]


@dataclass
class MatchResult:
    phrase: str | None
    similarity: float
    album: str

    def coloured_similarity(self) -> str:
        diff = max(0.0, self.similarity - SIM_LIMIT)
        max_diff = 100 - SIM_LIMIT
        colour = COLOURS[int((diff * (len(COLOURS) - 1) / max_diff) // 1)]
        return f"[{colour}]{self.similarity}[/{colour}]"


def find_best_match(track: Path, all_configs: list[TrackGroup]) -> MatchResult:
    filename = "_" + unidecode(track.name).lower() + "_"
    all_matches = [
        MatchResult(
            phrase=p,
            similarity=fuzz.partial_ratio("_" + p.replace(" ", "_") + "_", filename),
            album=cfg.album,
        )
        for cfg in all_configs
        for p in cfg.phrases
    ]
    all_matches = sorted(all_matches, key=lambda match: match.similarity, reverse=True)
    best_match = all_matches[0]
    if best_match.similarity < SIM_LIMIT:
        return MatchResult(phrase=None, similarity=0, album="Unsorted")
    return best_match


def organise_library(
    sc_client: SoundCloudClient, args: argparse.Namespace, cfg_manager: ConfigManager
):
    lib_path = cfg_manager.get_local_lib()
    cfg_path = cfg_manager.get_classification_config()

    # Load config
    with open(cfg_path, "r") as cfg:
        all_configs = [
            TrackGroup(**item) for item in yaml.load_all(cfg, yaml.SafeLoader)
        ]

    # Find album for all tracks
    results: dict[Path, MatchResult] = {
        track: find_best_match(track, all_configs) for track in lib_path.rglob("*.mp3")
    }

    # Edit mp3 tags
    prefix = args.prefix or ""
    with Progress(
        TextColumn("[white]{task.description}[/white]"),
        BarColumn(),
        TaskProgressColumn(text_format="[white]{task.percentage:>3.0f}%[/white]"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Applying mp3 tags", total=len(results))
        for file, match in results.items():
            mp3file = MP3(file, ID3=EasyID3)
            mp3file["title"] = file.stem
            mp3file["album"] = prefix + match.album
            mp3file.save()
            progress.update(task, advance=1)

    # Reorganise folders
    for old, match in results.items():
        (lib_path / match.album).mkdir(exist_ok=True)
        old.rename(lib_path / match.album / old.name)
    for p in lib_path.iterdir():
        if p.is_dir() and not list(p.iterdir()):
            p.rmdir()
            print(f"Removed {p}")

    # Display match results
    table = Table(title="Matched Tracks")
    table.add_column("Album", no_wrap=True)
    table.add_column("Matched Phrase", style="blue")
    table.add_column("Similarity")
    table.add_column("Filename")
    rows = [
        (match.album, match.phrase, match.coloured_similarity(), track.name)
        for track, match in results.items()
        if match.similarity
    ]
    for row in sorted(rows):
        table.add_row(*row)
    console = Console()
    console.print(table)

    # Display unsorted items
    unsorted = [track.name for track, match in results.items() if not match.similarity]
    if unsorted:
        n_disp = min(len(unsorted), 20)
        print(f"\nFirst {n_disp} of {len(unsorted)} unsorted tracks:")
        print("\n".join(unsorted[:n_disp]))
