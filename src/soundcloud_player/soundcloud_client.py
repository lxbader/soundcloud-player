import json
import re
import time
from dataclasses import dataclass
from random import shuffle
from typing import Any, Generator

import requests

TIMEOUT_S = 3


@dataclass
class Track:
    id: int
    title: str
    artist: str
    duration_secs: float

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Track):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class SoundCloudClient:
    def __init__(self, oauth_token: str) -> None:
        self.base_url = "https://api-v2.soundcloud.com/"
        self.session = requests.session()
        self.session.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101"
                " Firefox/140.0"
            ),
            "Authorization": f"OAuth {oauth_token}",
        }
        self.update_client_id()
        self.user_id = self.get("me")["id"]
        self.streamable_links: dict[int, tuple[str, float]] = {}
        self.liked_track_ids = self.update_liked_track_ids()

    def update_client_id(self) -> None:
        assets_script_regex = re.compile(
            r"src=\"(https:\/\/a-v2\.sndcdn\.com/assets/[^\.]+\.js)\""
        )
        client_id_regex = re.compile(r"client_id:\"([^\"]+)\"")
        r = requests.get("https://soundcloud.com", timeout=TIMEOUT_S)
        r.raise_for_status()
        matches = assets_script_regex.findall(r.text)
        if not matches:
            raise Exception("Could not generate client ID - no asset scripts found")
        url = matches[-1]
        r = requests.get(url, timeout=TIMEOUT_S)
        r.raise_for_status()
        client_id = client_id_regex.search(r.text)
        if not client_id:
            raise Exception(f"Could not find client_id in script '{url}'")
        self.session.params |= dict(client_id=client_id.group(1))  # type: ignore

    def _get_with_backoff(self, url: str, **kwargs) -> requests.Response:
        max_retries = 3
        for attempt in range(max_retries + 1):
            r = self.session.get(url, timeout=TIMEOUT_S, **kwargs)
            if r.ok or attempt == max_retries:
                r.raise_for_status()
                return r
            time.sleep(0.5 * (2**attempt))
        return r

    def get(self, path: str, **params) -> dict:
        r = self._get_with_backoff(self.base_url + path, params=params)
        return json.loads(r.text)

    def get_collection(self, path: str, **params) -> Generator[Any]:
        next_url = None
        while True:
            r = self._get_with_backoff(
                next_url or (self.base_url + path), params=None if next_url else params
            )
            data = r.json()
            for resource in data["collection"]:
                yield resource
            next_url = data.get("next_href", None)
            if not next_url:
                break

    def get_streamable_link(self, track_id: int) -> str:
        now = time.time()
        if cached := self.streamable_links.get(track_id, None):
            link, from_time = cached
            if now - from_time < 3600:
                return link
        track = self.get(f"tracks/{track_id}")
        transcoding = None
        for t in track["media"]["transcodings"]:
            if "mp3" in t["preset"] and t["format"]["protocol"] == "hls":
                transcoding = t
                break
        if not transcoding:
            raise Exception("No usable transcoding found.")
        r = self.session.get(transcoding["url"], timeout=TIMEOUT_S)
        r.raise_for_status()
        link = r.json()["url"]
        self.streamable_links[track_id] = (link, now)
        return link

    def update_liked_track_ids(self, first: int | None = None) -> list[int]:
        all_likes = list(self.get_collection("me/track_likes/ids"))
        shuffle(all_likes)
        if first:
            all_likes = [first] + [l for l in all_likes if l != first]
        return all_likes

    def get_liked_tracks(self) -> Generator[Track]:
        for track_id in self.liked_track_ids:
            t = self.get(f"tracks/{track_id}")
            yield Track(
                id=t["id"],
                title=t["title"],
                artist=t["user"]["username"],
                duration_secs=t["duration"] / 1000,
            )

    def get_feed(self, min_track_length_sec: int) -> Generator[Track]:
        seen = set()
        for i in self.get_collection(
            "stream", activityTypes="TrackPost,TrackRepost,PlaylistPost"
        ):
            if (
                "track" not in i
                or i["track"]["duration"] < min_track_length_sec * 1000
                or i["track"]["id"] in seen
            ):
                continue
            track = Track(
                id=i["track"]["id"],
                title=i["track"]["title"],
                artist=i["track"]["user"]["username"],
                duration_secs=i["track"]["duration"] / 1000,
            )
            seen.add(track.id)
            yield track
