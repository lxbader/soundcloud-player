from random import shuffle
from typing import Generator, Literal

import vlc
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Static
# from vlc import EventType

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
        for i in range(self.player.current_idx - 2, self.player.current_idx + 3):
            i = i % len(self.player.current_playlist)
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
            f"[dim][orange]{self.player.current_playlist_source.title()}: {len(self.player.current_playlist)} tracks[/orange][/dim]"
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
            likes=self.sc_client.get_liked_tracks(),
            feed=self.sc_client.get_feed(),
        )
        self.playlists: dict[str, list[Track]] = dict(likes=[], feed=[])
        self.liked_track_ids = self.sc_client.get_liked_track_ids()

        # Set initial state
        self.current_idx = None
        self.current_playlist = []
        self.current_playlist_source: SRC_LITERAL = "feed"

        # VLC setup
        self.vlc_instance = vlc.Instance(
            "--intf dummy --no-video --reset-plugins-cache --reset-config"
        )
        self.vlc_instance.log_unset()
        self.vlc_player = self.vlc_instance.media_player_new()
        self.vlc_player.audio_set_volume(70)
        # self.event_manager = self.vlc_player.event_manager()
        # self.event_manager.event_attach(
        #     EventType.MediaPlayerEndReached,
        #     lambda event: self.app.call_from_thread(
        #         self.change_track, self.current_idx + 1
        #     ),
        # )

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

    def update_display(self) -> None:
        self.query_one(PlayerView).update_view()

    def switch_playlist(self, source: SRC_LITERAL) -> None:
        self.current_playlist_source = source
        if not self.playlists[source]:
            self.expand_current_playlist()
        self.current_playlist = self.playlists[source].copy()
        self.change_track(0)

    def expand_current_playlist(self, count: int = 20) -> None:
        pl_gen = self.playlist_generators[self.current_playlist_source]
        new_items = [next(pl_gen, None) for i in range(count)]
        new_items = [track for track in new_items if track is not None]
        self.playlists[self.current_playlist_source].extend(new_items)
        self.current_playlist.extend(new_items)

    def change_track(self, new_idx: int) -> None:
        self.vlc_player.pause()
        self.current_idx = new_idx % len(self.current_playlist)
        url = self.sc_client.get_streamable_link(
            self.current_playlist[self.current_idx].id
        )
        media = self.vlc_instance.media_new(url)
        self.vlc_player.set_media(media)
        self.vlc_player.play()
        self.update_display()
        self.sub_title = (
            f"Now Playing: {fmt_track(self.current_playlist[self.current_idx])}"
        )

    def action_toggle_play(self) -> None:
        self.vlc_player.pause()

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
        self.expand_current_playlist(count=20)

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
