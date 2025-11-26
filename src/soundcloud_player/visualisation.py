from random import random, uniform

# Braille base char, with no dots visible
BRAILLE_BASE = 0x2800

# Braille dot mapping (orientation as printed). Combining all dots' on/off states into
# a binary number according to this mapping yields an offset that can be applied to the
# Braille base char to determine the correct Braille char that represents the desired
# state. For example, to create ⣇ (dots 0, 1, 2, 6, and 7 are turned on) we simply have
# to offset the Braille base char by 11000111 (on/off states for dots 76543210).
DOTS = [
    [0, 3],  # row 0 (top)
    [1, 4],  # row 1
    [2, 5],  # row 2
    [6, 7],  # row 3 (bottom)
]


def get_braille_col(
    left_val: float, right_val: float, n_rows: int, inverse: bool
) -> list[str]:
    """Given a left and right value (both must be in [0,1]), return Braille characters
    that - stacked from top to bottom - show a representation of the two values. In the
    simplest version where n_rows=1, a left value of 1 and a right value of 0.25 would
    return ⣇. The same values with n_rows=2 would return ⡇ followed by ⣧."""
    chars = []
    # Iterate through column, bottom up
    for row in range(n_rows):
        total_offset = 0
        # Iterate through Braille dots, bottom up
        for subrow, offsets in enumerate(DOTS[::-1]):
            height = row * 1 / n_rows + subrow * 1 / n_rows / 4 + 1 / n_rows / 8
            for val, offset in zip([left_val, right_val], offsets):
                if (val > height) and not inverse:
                    total_offset |= 1 << offset
                elif (val < height) and inverse:
                    total_offset |= 1 << offset
        chars.append(chr(BRAILLE_BASE + total_offset))
    return chars[::-1]  # return top-to-bottom view for easier postprocessing


def print_braille_multiline(values, n_rows: int = 1, inverse: bool = False) -> str:
    chars = [
        get_braille_col(values[i], values[i + 1], n_rows=n_rows, inverse=inverse)
        for i in range(0, len(values), 2)
    ]
    return "\n".join("".join(col[i] for col in chars) for i in range(n_rows))


def update_viz(old_viz: list[float]) -> list[float]:
    new_viz = []
    for i, val in enumerate(old_viz):
        # Trigger some random peaks
        if random() < 0.03:
            val = 1
        # Let bars be influenced by neighboring values
        if i > 0:
            val += 0.2 * (old_viz[i - 1] - old_viz[i])
        if i < len(old_viz) - 1:
            val += 0.2 * (old_viz[i + 1] - old_viz[i])
        # Apply some decay and clip
        val = max(0.0, min(1.0, val * 0.9))
        if val < 0.1:
            val = 0
        new_viz.append(val)
    return new_viz
