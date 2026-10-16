import time
from random import shuffle
from typing import Generator, Literal

import vlc
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widget import Widget
from textual.widgets import Header, Static

from soundcloud_player.background import Background, Starfield
from soundcloud_player.soundcloud_client import SoundCloudClient, Track
from soundcloud_player.visualisation import print_braille_multiline, update_viz

SRC_LITERAL = Literal["likes", "feed"]
NAV_WIDTH = 40
N_ITEMS = 9
YELLOW = "#FFD700"
BLUE = "#0F3460"
BRIGHT_BLUE = "#2563EB"


class PlayerView(Widget):
    def __init__(self, player, **kwargs) -> None:
        super().__init__(**kwargs)
        self.player = player
        self.background: Background = Starfield()

    def on_resize(self) -> None:
        w, h = self.size.width, self.size.height
        if w and h:
            self.background.resize(w, h)

    def _build_content_lines(self) -> list[Text]:
        lines: list[str] = [""]

        # Playlist
        start = max(self.player.playlist_idx[self.player.src] - N_ITEMS // 2, 0)
        for i in range(start, start + N_ITEMS):
            if i < 0 or i >= len(self.player.playlist[self.player.src]):
                lines.append("")
                continue
            track = self.player.playlist[self.player.src][i]
            title_str = f"[{YELLOW}]{i + 1}[/{YELLOW}] {fmt_track(track)}"
            if i == self.player.playlist_idx[self.player.src]:
                title_str = f"[bold]{title_str}[/bold]"
            else:
                title_str = f"[dim]{title_str}[/dim]"
            if (
                self.player.sc_client.liked_track_ids
                and track.id in self.player.sc_client.liked_track_ids
            ):
                title_str = title_str + f" [{BRIGHT_BLUE}](Liked)[/{BRIGHT_BLUE}]"
            lines.append(title_str)
        lines.append("")

        # Visualisation
        lines.append(
            f"[bold {BRIGHT_BLUE}]"
            + print_braille_multiline(self.player.viz)
            + f"[/bold {BRIGHT_BLUE}]"
        )
        lines.append("")

        # Time
        current, total = self.player.get_time_ms()
        max_blocks = NAV_WIDTH - 1
        prog_blocks = round(current / total * max_blocks) if total else 0
        prog_line = "[bold]" + fmt_time(current) + "[/bold] [dim]"
        prog_line += "─" * prog_blocks + "█" + "─" * (max_blocks - prog_blocks)
        prog_line += "[/dim] [bold]" + fmt_time(total) + "[/bold]"
        lines.append(prog_line)
        lines.append("")

        # Volume
        lines.append(f"🔈  {self.player.volume}% 🔊")
        lines.append("")

        # Convert to Text lines
        content: list[Text] = [Text.from_markup(raw) for raw in lines]
        return content

    def update_view(self) -> None:
        self.player.update_viz()
        self.refresh()

    def render(self) -> Text:
        w, h = self.size.width, self.size.height
        if not w or not h:
            return Text("")
        return self.background.render(self._build_content_lines(), w, h)


KEYS = [
    ("spc", "Play/Pause"),
    ("←/→", "Prev/Next"),
    ("↓/↑", "Volume"),
    (",/.", "Fine Seek"),
    ("1-9", "Relative Seek"),
    ("s", "Shuffle"),
    ("a", "A-Z"),
    ("t", "Likes/Feed"),
    ("q", "Quit"),
]


class Player(App):
    ENABLE_COMMAND_PALETTE = False
    CSS = f"""
    Header {{
        background: {BLUE};
    }}
    #keybindings {{
        dock: bottom;
        height: 1;
        text-align: center;
        background: {BLUE};
    }}
    #playlist {{
        width: 100%;
        height: 1fr;
        background: black;
    }}
    """
    BINDINGS = [
        ("space", "toggle_play"),
        ("s", "shuffle"),
        ("a", "alphabetic_sort"),
        ("t", "toggle_playlist"),
        ("left", "previous_track"),
        ("right", "next_track"),
        ("down", "volume_down"),
        ("up", "volume_up"),
        ("comma", "seek_backward"),
        (".", "seek_forward"),
        ("1", "seek_10"),
        ("2", "seek_20"),
        ("3", "seek_30"),
        ("4", "seek_40"),
        ("5", "seek_50"),
        ("6", "seek_60"),
        ("7", "seek_70"),
        ("8", "seek_80"),
        ("9", "seek_90"),
        ("q", "quit"),
    ]

    def __init__(self, sc_client: SoundCloudClient, min_track_length_sec: int) -> None:
        super().__init__()
        self.theme = "textual-dark"

        # Soundcloud setup
        self.sc_client = sc_client
        self.playlist_gen: dict[SRC_LITERAL, Generator[Track]] = {
            "likes": self.sc_client.get_liked_tracks(),
            "feed": self.sc_client.get_feed(min_track_length_sec=min_track_length_sec),
        }
        self.playlist: dict[SRC_LITERAL, list[Track]] = {"likes": [], "feed": []}
        self.playlist_idx: dict[SRC_LITERAL, int] = {"likes": 0, "feed": 0}

        # Set initial state. Only the run_vlc thread talks to VLC, as VLC calls can
        # block for a long time (e.g. while dropping a stalled stream), so the UI sets
        # what it wants here and reads back the position VLC last reported.
        self.src: SRC_LITERAL = "feed"  # which playlist to show/play
        self.is_playing = True  # whether the player is currently playing or paused
        self.volume = 70
        self.seek_request_ms: int | None = None  # seek not yet passed on to VLC
        self.loaded_track_id: int | None = None  # track currently loaded into VLC
        self.time_ms = 0  # playback position, also where to resume a dead stream
        self.seek_shown_until = 0.0  # VLC reports stale times briefly after seeking
        self.viz: list[float] | None = None  # current visualisation state
        self.update_viz(reset=True)

        # VLC setup
        self.vlc_instance = vlc.Instance(
            "--intf dummy --no-video --reset-plugins-cache --reset-config "
            "--network-caching=3000 --file-caching=3000 --live-caching=3000"
        )
        self.vlc_instance.log_unset()
        self.vlc_player = self.vlc_instance.media_player_new()
        self.vlc_active = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        keys = " ".join(f"[{YELLOW}]" + i + f"[/{YELLOW}] " + j for i, j in KEYS)
        yield Static(keys, id="keybindings")
        with Container():
            yield PlayerView(self, id="playlist")

    def on_mount(self) -> None:
        self.switch_playlist(self.src)
        self.update_display()
        self.set_interval(0.05, self.update_display)
        self.run_vlc()

    def on_unmount(self) -> None:
        self.vlc_active = False

    def update_display(self) -> None:
        self.query_one(PlayerView).update_view()

    @work(exclusive=True, thread=True)
    def run_vlc(self) -> None:
        while self.vlc_active:
            try:
                self.sync_vlc()
            except Exception as e:
                self.call_from_thread(self.notify, str(e), severity="error")
                time.sleep(1)
            time.sleep(0.2)

    def sync_vlc(self) -> None:
        """Bring VLC in line with what the UI asked for and read back its position.

        VLC is the source of truth for the playback position; this only passes on
        requests, loads tracks and recovers streams that stopped.
        """
        if not self.playlist[self.src]:
            # No tracks loaded yet (e.g. a network failure during load)
            return
        track = self.playlist[self.src][self.playlist_idx[self.src]]
        if track.id != self.loaded_track_id:
            self.load_track(track.id, start_ms=0)

        if self.vlc_player.audio_get_volume() != self.volume:
            self.vlc_player.audio_set_volume(self.volume)

        state = self.vlc_player.get_state()
        if state in (vlc.State.Ended, vlc.State.Error):
            if track.duration_secs * 1000 - self.time_ms < 5000:
                self.call_from_thread(
                    self.change_track, new_idx=self.playlist_idx[self.src] + 1
                )
            else:
                # The stream died mid-track, e.g. its links expired during a long
                # pause. Reload it with a fresh link from where it stopped.
                self.sc_client.streamable_links.pop(track.id, None)
                self.load_track(track.id, start_ms=self.time_ms)
            return

        if self.is_playing and state in (
            vlc.State.NothingSpecial,
            vlc.State.Stopped,
            vlc.State.Paused,
        ):
            self.vlc_player.play()
        elif not self.is_playing and state == vlc.State.Playing:
            self.vlc_player.pause()

        if state in (vlc.State.Playing, vlc.State.Paused):
            if (seek_ms := self.seek_request_ms) is not None:
                self.seek_request_ms = None
                self.vlc_player.set_time(seek_ms)
                # Right after a seek, VLC briefly reports the start of the HLS chunk
                self.seek_shown_until = time.time() + 1
            elif time.time() > self.seek_shown_until:
                # VLC reports 0 while a stream is opening, so keep the old position
                if (time_ms := self.vlc_player.get_time()) > 0:
                    self.time_ms = time_ms

    def load_track(self, track_id: int, start_ms: int) -> None:
        url, _ = self.sc_client.get_streamable_link(track_id)
        media = self.vlc_instance.media_new(url)
        # HLS streams start at the beginning of the chunk containing this time
        media.add_option(f"start-time={start_ms // 1000}")
        self.vlc_player.set_media(media)
        self.loaded_track_id = track_id

    def switch_playlist(self, source: SRC_LITERAL) -> None:
        self.src = source
        if not self.playlist[source]:
            self.expand_current_playlist(count=N_ITEMS)
        self.change_track(self.playlist_idx[self.src])
        self.is_playing = True

    def expand_current_playlist(self, count: int) -> None:
        new_items = [
            track
            for track in [next(self.playlist_gen[self.src], None) for i in range(count)]
            if track is not None
        ]
        self.playlist[self.src].extend(new_items)

    def change_track(self, new_idx: int) -> None:
        if (missing := new_idx + N_ITEMS - len(self.playlist[self.src])) > 0:
            self.expand_current_playlist(count=missing)
        playlist = self.playlist[self.src]
        if not playlist:
            # No playlist available, just don't do anything
            return
        # Do not go past the end of the playlist, if it has an end for some reason
        self.playlist_idx[self.src] = max(0, min(new_idx, len(playlist) - 1))
        self.loaded_track_id = None  # (re)load even if the index didn't change
        self.time_ms = 0
        self.seek_request_ms = None
        self.update_viz(reset=True)
        self.update_display()
        self.sub_title = (
            f"Now Playing: {fmt_track(playlist[self.playlist_idx[self.src]])}"
        )

    def play(self) -> None:
        self.is_playing = True

    def pause(self) -> None:
        self.is_playing = False

    def seek_to_ms(self, target_ms: int) -> None:
        _, total = self.get_time_ms()
        self.time_ms = self.seek_request_ms = max(0, min(target_ms, total))

    def seek_to_fraction(self, fraction: float) -> None:
        _, total = self.get_time_ms()
        self.seek_to_ms(int(fraction * total))

    def seek_relative(self, delta_s: int) -> None:
        current, _ = self.get_time_ms()
        self.seek_to_ms(current + delta_s * 1000)

    def get_time_ms(self) -> tuple[int, int]:
        if not self.playlist[self.src]:
            return 0, 0
        track = self.playlist[self.src][self.playlist_idx[self.src]]
        return self.time_ms, int(track.duration_secs * 1000)

    def update_viz(self, reset: bool = False):
        if reset or not self.viz:
            self.viz = [0.0] * NAV_WIDTH * 2
            return
        if not self.is_playing:
            return
        self.viz = update_viz(self.viz)
        return

    def action_toggle_play(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def action_shuffle(self) -> None:
        if self.src == "likes":
            return  # TODO
        start = self.playlist[self.src][self.playlist_idx[self.src]]
        rest = (
            self.playlist[self.src][: self.playlist_idx[self.src]]
            + self.playlist[self.src][self.playlist_idx[self.src] + 1 :]
        )
        shuffle(rest)
        self.playlist[self.src] = [start] + rest
        self.playlist_idx[self.src] = 0

    def action_alphabetic_sort(self) -> None:
        current_track = self.playlist[self.src][self.playlist_idx[self.src]]
        self.playlist[self.src].sort(key=lambda tr: fmt_track(tr))
        for i, track in enumerate(self.playlist[self.src]):
            if track.id == current_track.id:
                self.playlist_idx[self.src] = i
                break

    def action_toggle_playlist(self) -> None:
        self.switch_playlist("likes" if self.src == "feed" else "feed")

    def action_next_track(self) -> None:
        self.change_track(self.playlist_idx[self.src] + 1)

    def action_previous_track(self) -> None:
        self.change_track(self.playlist_idx[self.src] - 1)

    def action_volume_down(self) -> None:
        self.volume = max(0, self.volume - 5)

    def action_volume_up(self) -> None:
        self.volume = min(100, self.volume + 5)

    def action_seek_backward(self) -> None:
        self.seek_relative(delta_s=-10)

    def action_seek_forward(self) -> None:
        self.seek_relative(delta_s=10)

    def action_seek_10(self) -> None:
        self.seek_to_fraction(0.1)

    def action_seek_20(self) -> None:
        self.seek_to_fraction(0.2)

    def action_seek_30(self) -> None:
        self.seek_to_fraction(0.3)

    def action_seek_40(self) -> None:
        self.seek_to_fraction(0.4)

    def action_seek_50(self) -> None:
        self.seek_to_fraction(0.5)

    def action_seek_60(self) -> None:
        self.seek_to_fraction(0.6)

    def action_seek_70(self) -> None:
        self.seek_to_fraction(0.7)

    def action_seek_80(self) -> None:
        self.seek_to_fraction(0.8)

    def action_seek_90(self) -> None:
        self.seek_to_fraction(0.9)


def fmt_time(msec: int) -> str:
    sec = msec // 1000
    hours = sec // 3600
    mins = sec % 3600 // 60
    secs = sec % 60
    return (f"{hours:02d}:" if hours else "   ") + f"{mins:02d}:{secs:02d}"


def fmt_track(track: Track) -> str:
    return f"{track.artist} - {track.title}"
