import json
import re
from dataclasses import dataclass
from typing import Any, Generator

import requests


@dataclass
class Track:
    id: int
    title: str
    artist: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Track):
            return NotImplemented
        return (
            self.id == other.id
            and self.title == other.title
            and self.artist == other.artist
        )

    def __hash__(self) -> int:
        return hash(self.id)


class SoundCloudClient:
    def __init__(self, oauth_token: str) -> None:
        self.base_url = "https://api-v2.soundcloud.com/"
        self.session = requests.session()
        self.session.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
            ),
            "Authorization": f"OAuth {oauth_token}",
        }
        self.update_client_id()

    def update_client_id(self) -> None:
        assets_script_regex = re.compile(
            r"src=\"(https:\/\/a-v2\.sndcdn\.com/assets/[^\.]+\.js)\""
        )
        client_id_regex = re.compile(r"client_id:\"([^\"]+)\"")
        r = requests.get("https://soundcloud.com")
        r.raise_for_status()
        matches = assets_script_regex.findall(r.text)
        if not matches:
            raise Exception("Could not generate client ID - no asset scripts found")
        url = matches[-1]
        r = requests.get(url)
        r.raise_for_status()
        client_id = client_id_regex.search(r.text)
        if not client_id:
            raise Exception(f"Could not find client_id in script '{url}'")
        self.session.params |= dict(client_id=client_id.group(1))

    def get(self, path: str, **params) -> dict:
        r = self.session.get(self.base_url + path, params=params)
        r.raise_for_status()
        return json.loads(r.text)

    def get_collection(self, path: str, **params) -> Generator[Any]:
        next_url = None
        while True:
            r = self.session.get(
                next_url or (self.base_url + path), params=None if next_url else params
            )
            r.raise_for_status()
            data = r.json()
            for resource in data["collection"]:
                yield resource
            next_url = data.get("next_href", None)
            if not next_url:
                break

    def get_streamable_link(self, track_id: int) -> str:
        track = self.get(f"tracks/{track_id}")
        transcoding = None
        for t in track["media"]["transcodings"]:
            if "mp3" in t["preset"] and t["format"]["protocol"] == "hls":
                transcoding = t
                break
        if not transcoding:
            raise Exception("No usable transcoding found.")
        r = self.session.get(transcoding["url"])
        r.raise_for_status()
        return r.json()["url"]

    def get_liked_track_ids(self) -> set[int]:
        return set(self.get_collection("me/track_likes/ids"))

    def get_liked_tracks(self) -> Generator[Track]:
        my_id = self.get("me")["id"]
        for t in self.get_collection(f"users/{my_id}/likes"):
            if "track" not in t:
                continue
            yield Track(
                id=t["track"]["id"],
                title=t["track"]["title"],
                artist=t["track"]["user"]["username"],
            )

    def get_feed(self, min_length_sec: int = 1800) -> Generator[Track]:
        seen = set()
        for i in self.get_collection(
            "stream", activityTypes="TrackPost,TrackRepost,PlaylistPost"
        ):
            if (
                "track" not in i
                or i["track"]["duration"] < min_length_sec * 1000
                or i["track"]["id"] in seen
            ):
                continue
            track = Track(
                id=i["track"]["id"],
                title=i["track"]["title"],
                artist=i["track"]["user"]["username"],
            )
            seen.add(track.id)
            yield track
