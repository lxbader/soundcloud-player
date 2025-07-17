import time
from random import shuffle
from typing import Generator, Literal

import vlc
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Static

from soundcloud_player.soundcloud_client import SoundCloudClient, Track

SRC_LITERAL = Literal["likes", "feed"]


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
        n_items = 9
        start = max(self.player.current_idx - n_items // 2, 0)
        end = start + n_items
        if end >= len(self.player.current_playlist):
            offset = end - len(self.player.current_playlist)
            start, end = start - offset, end - offset
        for i in range(start, end):
            track = self.player.current_playlist[i]
            title_str = f"[orange]{i + 1}[/orange] {fmt_track(track)}"
            if i == self.player.current_idx:
                title_str = f"[bold]{title_str}[/bold]"
            else:
                title_str = f"[dim]{title_str}[/dim]"
            if self.player.liked_track_ids and track.id in self.player.liked_track_ids:
                title_str = title_str + " [blue](Liked)[/blue]"
            playlist.append(title_str)
        content.append("\n".join(playlist))

        # Track count
        content.append(
            f"[dim][orange]{self.player.current_playlist_source.title()}:"
            f" {len(self.player.current_playlist)} tracks[/orange][/dim]"
        )

        # Time
        current, total = self.player.get_time()
        max_blocks = 30
        prog_blocks = round(current / total * max_blocks) if total else 0
        prog_line = "[bold]" + fmt_time(current) + " "
        prog_line += "█" * prog_blocks + "░" * (max_blocks - prog_blocks)
        prog_line += " " + fmt_time(total) + "[/bold]"
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
        ("m", "load_more_tracks", "Load More Tracks"),
        # ("l", "toggle_track_like", "Like/Unlike Track"),
        ("left", "previous_track", "Previous"),
        ("right", "next_track", "Next"),
        ("down", "volume_down", "Vol Down"),
        ("up", "volume_up", "Vol Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, sc_client: SoundCloudClient) -> None:
        super().__init__()
        self.theme = "textual-dark"

        # Soundcloud setup
        self.sc_client = sc_client
        self.playlist_generators: dict[str, Generator[Track]] = dict(
            likes=self.sc_client.get_liked_tracks(), feed=self.sc_client.get_feed()
        )
        self.playlists: dict[str, list[Track]] = dict(likes=[], feed=[])
        self.liked_track_ids = self.sc_client.get_liked_track_ids()

        # Set initial state
        self.current_idx = 0
        self.current_start_time_s = 0
        self.current_playlist: list[Track] = []
        self.current_playlist_source: SRC_LITERAL = "feed"
        self.is_active = False

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
        self.switch_playlist(self.current_playlist_source)
        self.update_display()
        self.set_interval(0.2, self.update_display)

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
                        self.change_track, new_idx=self.current_idx + 1
                    )
                else:
                    self.call_from_thread(self.refresh_track)
            time.sleep(0.2)

    def switch_playlist(self, source: SRC_LITERAL) -> None:
        self.current_playlist_source = source
        if not self.playlists[source]:
            self.expand_current_playlist()
        self.current_playlist = self.playlists[source].copy()
        self.change_track(0)

    def expand_current_playlist(self, count: int = 20) -> None:
        pl_gen = self.playlist_generators[self.current_playlist_source]
        new_items = [
            track
            for track in [next(pl_gen, None) for i in range(count)]
            if track is not None
        ]
        self.playlists[self.current_playlist_source].extend(new_items)
        self.current_playlist.extend(new_items)

    def change_track(self, new_idx: int, start_time_s: int = 0) -> None:
        self.pause()
        self.current_idx = new_idx % len(self.current_playlist)
        url = self.sc_client.get_streamable_link(
            self.current_playlist[self.current_idx].id
        )
        media = self.vlc_instance.media_new(url)
        self.current_start_time_s = start_time_s
        media.add_option(f"start-time={start_time_s}")
        self.vlc_player.set_media(media)
        self.update_display()
        self.sub_title = (
            f"Now Playing: {fmt_track(self.current_playlist[self.current_idx])}"
        )
        self.play()

    def refresh_track(self) -> None:
        track_time = int(self.vlc_player.get_time() / 1000)
        self.change_track(
            self.current_idx, start_time_s=track_time + self.current_start_time_s
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

    def action_toggle_play(self) -> None:
        if self.is_active:
            self.pause()
        else:
            self.play()

    def action_refresh_track(self) -> None:
        self.refresh_track()

    def action_shuffle(self) -> None:
        start = self.current_playlist[self.current_idx]
        rest = (
            self.current_playlist[: self.current_idx]
            + self.current_playlist[self.current_idx + 1 :]
        )
        shuffle(rest)
        self.current_playlist = [start] + rest
        self.current_idx = 0

    def action_alphabetic_sort(self) -> None:
        current_track = self.current_playlist[self.current_idx]
        self.current_playlist.sort(
            key=lambda track: f"{track.artist.lower()} - {track.title.lower()}"
        )
        for i, track in enumerate(self.current_playlist):
            if track.id == current_track.id:
                self.current_idx = i
                break

    def action_toggle_playlist(self) -> None:
        self.switch_playlist(
            "likes" if self.current_playlist_source == "feed" else "feed"
        )

    def action_load_more_tracks(self) -> None:
        self.expand_current_playlist()

    # def action_toggle_track_like(self) -> None:
    #     track_id = self.current_playlist[self.current_idx].id
    #     if not self.liked_track_ids:
    #         return
    #     if track_id in self.liked_track_ids:
    #         self.sc_client.unlike_track(track_id)
    #     else:
    #         self.sc_client.like_track(track_id)
    #     self.liked_track_ids = self.sc_client.get_liked_track_ids()

    def action_next_track(self) -> None:
        self.change_track(self.current_idx + 1)

    def action_previous_track(self) -> None:
        self.change_track(self.current_idx - 1)

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
    return (f"{hours:02d}:" if hours else "") + f"{mins:02d}:{secs:02d}"


def fmt_track(track: Track) -> str:
    return f"{track.artist} - {track.title}"
