from random import shuffle
from typing import Literal

import vlc
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Static
from vlc import EventType

from soundcloud_player.soundcloud_client import SoundCloudClient, Track


class PlayerView(Static):
    def __init__(self, player, **kwargs):
        super().__init__(**kwargs)
        self.player = player
        self.styles.height = "auto"
        self.styles.margin = 1
        self.styles.text_align = "center"

    def update_view(self):
        content = []

        # Playlist
        playlist = []
        for i in range(self.player.idx - 2, self.player.idx + 3):
            i = i % len(self.player.playlist)
            track = self.player.playlist[i]
            if i == self.player.idx:
                title_str = f"[bold]{fmt_track(track)}[/bold]"
            else:
                title_str = f"[dim]{fmt_track(track)}[/dim]"
            if self.player.liked_track_ids and track.id in self.player.liked_track_ids:
                title_str = "[blue]" + title_str + "[/blue]"
            playlist.append(title_str)
        content.append("\n".join(playlist))

        # Track count
        content.append(
            f"[dim][orange]{self.player.playlist_source.title()}: {len(self.player.playlist)} tracks[/orange][/dim]"
        )

        # Time
        current = self.player.vlc_player.get_time() or 0
        total = self.player.vlc_player.get_length() or 0
        max_blocks = 30
        progress_blocks = round(current / total * max_blocks) if total else 0
        content.append(
            f"[bold]{fmt_time(current)} {'█' * progress_blocks}{'░' * (max_blocks - progress_blocks)} {fmt_time(total)}[/bold]"
        )

        # Volume
        content.append(f"🔈 {self.player.vlc_player.audio_get_volume()}% 🔊")

        self.update("\n\n".join(content))


class Player(App):
    BINDINGS = [
        ("space", "toggle_play", "Play/Pause"),
        ("s", "shuffle", "Shuffle"),
        ("a", "sort", "Sort Alphabetically"),
        ("l", "toggle_playlist", "Toggle Likes/Feed"),
        ("left", "previous_track", "Previous Track"),
        ("right", "next_track", "Next Track"),
        ("down", "volume_down", "Volume Down"),
        ("up", "volume_up", "Volume Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, sc_client: SoundCloudClient):
        super().__init__()
        self.theme = "textual-dark"

        # Soundcloud setup
        self.sc_client = sc_client
        self.liked_track_ids = self.sc_client.get_liked_track_ids()
        self.idx = None
        self.playlist = None
        self.playlist_source: Literal["likes", "feed"] = "likes"

        # VLC setup
        self.vlc_instance = vlc.Instance(
            "--intf dummy --no-video --reset-plugins-cache --reset-config"
        )
        self.vlc_instance.log_unset()
        self.vlc_player = self.vlc_instance.media_player_new()
        self.vlc_player.audio_set_volume(70)
        self.event_manager = self.vlc_player.event_manager()
        self.event_manager.event_attach(
            EventType.MediaPlayerEndReached,
            lambda event: self.app.call_from_thread(self.change_track, self.idx + 1),
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container():
            yield PlayerView(self, id="playlist")
        yield Footer()

    def on_mount(self) -> None:
        self.update_playlist()
        self.update_display()
        self.set_interval(0.2, self.update_display)

    def update_display(self) -> None:
        self.query_one(PlayerView).update_view()

    def change_track(self, new_idx: int) -> None:
        self.vlc_player.pause()
        self.idx = new_idx % len(self.playlist)
        url = self.sc_client.get_streamable_link(self.playlist[self.idx].id)
        media = self.vlc_instance.media_new(url)
        self.vlc_player.set_media(media)
        self.vlc_player.play()
        self.update_display()
        self.sub_title = f"Now Playing: {fmt_track(self.playlist[self.idx])}"

    def update_playlist(self):
        if self.playlist_source == "feed":
            self.playlist = self.sc_client.get_feed()
        else:
            self.playlist = self.sc_client.get_liked_tracks()
        shuffle(self.playlist)
        self.change_track(0)

    def action_toggle_play(self) -> None:
        self.vlc_player.pause()

    def action_shuffle(self) -> None:
        start = self.playlist[self.idx]
        rest = self.playlist[: self.idx] + self.playlist[self.idx + 1 :]
        shuffle(rest)
        self.playlist = [start] + rest
        self.idx = 0

    def action_sort(self) -> None:
        current_track = self.playlist[self.idx]
        self.playlist.sort(
            key=lambda track: f"{track.artist.lower()} - {track.title.lower()}"
        )
        for i, track in enumerate(self.playlist):
            if track.id == current_track.id:
                self.idx = i
                break

    def action_toggle_playlist(self) -> None:
        self.playlist_source = "likes" if self.playlist_source == "feed" else "feed"
        self.update_playlist()

    def action_next_track(self) -> None:
        self.change_track(self.idx + 1)

    def action_previous_track(self) -> None:
        self.change_track(self.idx - 1)

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
