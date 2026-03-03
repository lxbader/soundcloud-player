import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

BG_STYLE = "dim #FFD700"


class Background(ABC):
    @abstractmethod
    def resize(self, w: int, h: int) -> None: ...

    @abstractmethod
    def get_bg_rows(self, w: int, h: int) -> list[str]: ...

    def render(self, content_lines: list[Text], w: int, h: int) -> Text:
        bg_rows = self.get_bg_rows(w, h)
        top_pad = max(0, (h - len(content_lines)) // 2)
        result = Text()
        for row in range(h):
            bg_row = bg_rows[row]
            content_idx = row - top_pad
            if content_idx < 0 or content_idx >= len(content_lines):
                # Background line not overlapped by content
                result.append(bg_row, style=BG_STYLE)
            else:
                # Overlay content line over background line
                line = content_lines[content_idx]
                plain = line.plain
                if not plain.strip():
                    result.append(bg_row, style=BG_STYLE)
                else:
                    content_w = cell_len(plain)
                    left = max(0, (w - content_w) // 2)
                    right = max(0, w - content_w - left)
                    result.append(bg_row[:left], style=BG_STYLE)
                    result.append_text(line)
                    result.append(
                        bg_row[left + content_w : left + content_w + right],
                        style=BG_STYLE,
                    )
            if row < h - 1:
                result.append("\n")
        return result


@dataclass
class Star:
    x: float
    y: float
    brightness: float
    delta: float


class Starfield(Background):
    def __init__(self) -> None:
        self._max_stars: int = 0
        self._stars: list[Star] = []

    @staticmethod
    def _new_star(w: int, h: int) -> Star:
        return Star(
            random.random() * w, random.random() * h, 0.0, random.uniform(0.01, 0.12)
        )

    def resize(self, w: int, h: int) -> None:
        self._max_stars = int(w * h / 70)

    def _update_stars(self, w: int, h: int):
        if len(self._stars) < self._max_stars:
            self._stars.append(self._new_star(w, h))
        elif len(self._stars) > self._max_stars:
            random.shuffle(self._stars)
            self._stars = self._stars[: len(self._stars) - 1]

    def get_bg_rows(self, w: int, h: int) -> list[str]:
        self._update_stars(w, h)
        grid = [[" "] * w for _ in range(h)]
        for i, star in enumerate(self._stars):
            star.brightness += star.delta
            if star.brightness >= 1.0:
                star.delta = -star.delta
            elif star.brightness <= 0.0:
                self._stars[i] = self._new_star(w, h)
            if star.brightness > 0.1:
                ix, iy = int(star.x), int(star.y)
                if 0 <= ix < w and 0 <= iy < h:
                    char = (
                        "*"
                        if star.brightness > 0.7
                        else ("+" if star.brightness > 0.4 else ".")
                    )
                    grid[iy][ix] = char
        return ["".join(row) for row in grid]
