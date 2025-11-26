import time
from random import shuffle
from typing import Generator, Literal

import vlc
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Static

from soundcloud_player.soundcloud_client import SoundCloudClient, Track
from soundcloud_player.visualisation import print_braille_multiline, update_viz

SRC_LITERAL = Literal["likes", "feed"]
NAV_WIDTH = 40
N_ITEMS = 9


class PlayerView(Static):
    def __init__(self, player, **kwargs) -> None:
        super().__init__(**kwargs)
        self.player = player
        self.styles.height = "auto"
        self.styles.margin = 1
        self.styles.text_align = "center"

    def update_view(self) -> None:
        content = []

        # Playlist
        playlist = []
        start = max(self.player.playlist_idx[self.player.src] - N_ITEMS // 2, 0)
        for i in range(start, start + N_ITEMS):
            if i < 0 or i >= len(self.player.playlist[self.player.src]):
                playlist.append("")
                continue
            track = self.player.playlist[self.player.src][i]
            title_str = f"[orange]{i + 1}[/orange] {fmt_track(track)}"
            if i == self.player.playlist_idx[self.player.src]:
                title_str = f"[bold]{title_str}[/bold]"
            else:
                title_str = f"[dim]{title_str}[/dim]"
            if self.player.liked_track_ids and track.id in self.player.liked_track_ids:
                title_str = title_str + " [blue](Liked)[/blue]"
            playlist.append(title_str)
        content.append("\n".join(playlist))

        # Visualisation
        self.player.update_viz()
        content.append(print_braille_multiline(self.player.viz))

        # Time
        current, total = self.player.get_time()
        max_blocks = NAV_WIDTH - 1  # knob takes 1 char
        prog_blocks = round(current / total * max_blocks) if total else 0
        prog_line = "[bold]" + fmt_time(current) + "[/bold] [dim]"
        prog_line += "─" * prog_blocks + "█" + "─" * (max_blocks - prog_blocks)
        prog_line += "[/dim] [bold]" + fmt_time(total) + "[/bold]"
        content.append(prog_line)

        # Volume
        content.append(f"🔈 {self.player.vlc_player.audio_get_volume()}% 🔊")

        self.update("\n\n".join(content))


class Player(App):
    BINDINGS = [
        ("space", "toggle_play", "Play/Pause"),
        ("r", "refresh_track", "Refresh"),
        ("s", "shuffle", "Shuffle"),
        ("a", "alphabetic_sort", "A-Z Sort"),
        ("t", "toggle_playlist", "Toggle Likes/Feed"),
        # ("l", "toggle_track_like", "Like/Unlike Track"),
        ("left", "previous_track", "Previous"),
        ("right", "next_track", "Next"),
        ("down", "volume_down", "Vol Down"),
        ("up", "volume_up", "Vol Up"),
        ("q", "quit", "Quit"),
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
        self.liked_track_ids = self.sc_client.get_liked_track_ids()

        # Set initial state
        self.src: SRC_LITERAL = "feed"
        self.current_start_time_s = 0
        self.is_active = False
        self.viz: list[float] | None = None
        self.update_viz(reset=True)

        # VLC setup
        self.vlc_instance = vlc.Instance(
            "--intf dummy --no-video --reset-plugins-cache --reset-config "
            "--network-caching=3000 --file-caching=3000 --live-caching=3000"
        )
        self.vlc_instance.log_unset()
        self.vlc_player = self.vlc_instance.media_player_new()
        self.vlc_player.audio_set_volume(70)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container() as container:
            container.styles.background = "black"
            yield PlayerView(self, id="playlist")
        yield Footer()

    def on_mount(self) -> None:
        self.switch_playlist(self.src)
        self.update_display()
        self.set_interval(0.05, self.update_display)

    def on_unmount(self) -> None:
        self.is_active = False

    def update_display(self) -> None:
        self.query_one(PlayerView).update_view()

    @work(exclusive=True, thread=True)
    def watch_vlc(self) -> None:
        # Watch VLC player closely, it tends to die every once in a while so we cannot
        # trust it to get itself unstuck and/or provide track change events
        while self.is_active:
            current, total = self.get_time()
            if total and not self.vlc_player.is_playing():
                if current / total > 0.999:
                    self.call_from_thread(
                        self.change_track, new_idx=self.playlist_idx[self.src] + 1
                    )
                else:
                    self.call_from_thread(self.refresh_track)
            time.sleep(0.2)

    def switch_playlist(self, source: SRC_LITERAL) -> None:
        self.src = source
        if not self.playlist[source]:
            self.expand_current_playlist(count=N_ITEMS)
        self.change_track(self.playlist_idx[self.src])

    def expand_current_playlist(self, count: int) -> None:
        new_items = [
            track
            for track in [next(self.playlist_gen[self.src], None) for i in range(count)]
            if track is not None
        ]
        self.playlist[self.src].extend(new_items)

    def change_track(self, new_idx: int, start_time_s: int = 0) -> None:
        self.pause()
        self.playlist_idx[self.src] = new_idx
        if (missing := new_idx + N_ITEMS - len(self.playlist[self.src])) > 0:
            self.expand_current_playlist(count=missing)
        url = self.sc_client.get_streamable_link(
            self.playlist[self.src][self.playlist_idx[self.src]].id
        )
        media = self.vlc_instance.media_new(url)
        self.current_start_time_s = start_time_s
        media.add_option(f"start-time={start_time_s}")
        self.vlc_player.set_media(media)
        self.update_viz(reset=True)
        self.update_display()
        self.sub_title = (
            "Now Playing:"
            f" {fmt_track(self.playlist[self.src][self.playlist_idx[self.src]])}"
        )
        self.play()

    def refresh_track(self) -> None:
        track_time = int(self.vlc_player.get_time() / 1000)
        self.change_track(
            self.playlist_idx[self.src],
            start_time_s=track_time + self.current_start_time_s,
        )

    def play(self) -> None:
        if self.is_active:
            return
        self.vlc_player.play()
        self.is_active = True
        self.watch_vlc()

    def pause(self) -> None:
        if not self.is_active:
            return
        self.is_active = False
        self.vlc_player.pause()

    def get_time(self) -> tuple[int, int]:
        current = (self.vlc_player.get_time() or 0) + self.current_start_time_s * 1000
        total = self.vlc_player.get_length() or 0
        return current, total

    def update_viz(self, reset: bool = False):
        if reset or not self.viz:
            self.viz = [0.0] * NAV_WIDTH * 2
            return
        if not self.is_active:
            return
        self.viz = update_viz(self.viz)
        return

    def action_toggle_play(self) -> None:
        if self.is_active:
            self.pause()
        else:
            self.play()

    def action_refresh_track(self) -> None:
        self.refresh_track()

    def action_shuffle(self) -> None:
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

    # def action_toggle_track_like(self) -> None:
    #     track_id = self.playlist[self.source][self.playlist_idx[self.source]].id
    #     if not self.liked_track_ids:
    #         return
    #     if track_id in self.liked_track_ids:
    #         self.sc_client.unlike_track(track_id)
    #     else:
    #         self.sc_client.like_track(track_id)
    #     self.liked_track_ids = self.sc_client.get_liked_track_ids()

    def action_next_track(self) -> None:
        self.change_track(self.playlist_idx[self.src] + 1)

    def action_previous_track(self) -> None:
        self.change_track(self.playlist_idx[self.src] - 1)

    def action_volume_down(self) -> None:
        vol = max(0, self.vlc_player.audio_get_volume() - 5)
        self.vlc_player.audio_set_volume(vol)

    def action_volume_up(self) -> None:
        vol = min(100, self.vlc_player.audio_get_volume() + 5)
        self.vlc_player.audio_set_volume(vol)


def fmt_time(msec: int) -> str:
    sec = msec // 1000
    hours = sec // 3600
    mins = sec % 3600 // 60
    secs = sec % 60
    return (f"{hours:02d}:" if hours else "   ") + f"{mins:02d}:{secs:02d}"


def fmt_track(track: Track) -> str:
    return f"{track.artist} - {track.title}"
