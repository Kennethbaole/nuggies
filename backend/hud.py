"""Render a snapshot to a small monochrome image for a future display adapter.

Pillow is optional: install requirements-display.txt. No GPIO/I2C assumptions.
"""

import argparse
import json
import math
import os
from urllib.request import Request, urlopen


def render_frame(state, width=128, height=64, mirror_x=False, mirror_y=False):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    if width < 128 or height < 64:
        raise ValueError("Reference renderer requires at least 128 × 64")
    image = Image.new("1", (width, height))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=7)
    for index, slot in enumerate(state["slots"]):
        angle = index * math.pi / 4 - math.pi / 2
        x, y = width / 2 + math.cos(angle) * width * .37, height / 2 + math.sin(angle) * height * .35
        label = slot["label"][:7]
        box = draw.textbbox((0, 0), label, font=font)
        text_width, text_height = box[2] - box[0], box[3] - box[1]
        selected = index == state["selected"]
        if selected:
            draw.rectangle((x - text_width / 2 - 2, y - 5, x + text_width / 2 + 2, y + 5), fill=1)
        draw.text((x - text_width / 2, y - text_height / 2 - box[1]), label, font=font,
                  fill=0 if selected else int(slot["enabled"]))
    text = state.get("draft") if state["screen"] == "spell" else state.get("confirmed")
    text = text or "Ready"
    lines, current = [], ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=font) > width * .4 and current:
            lines.append(current); current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    for index, line in enumerate(lines[:3]):
        if index == 2 and len(lines) > 3:
            line = line[:8] + "…"
        text_width = draw.textlength(line, font=font)
        draw.text(((width - text_width) / 2, height / 2 - min(len(lines), 3) * 4 + index * 8), line, font=font, fill=1)
    if mirror_x:
        image = ImageOps.mirror(image)
    if mirror_y:
        image = ImageOps.flip(image)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--mirror-x", action="store_true")
    parser.add_argument("--mirror-y", action="store_true")
    args = parser.parse_args()
    request = Request(args.url.rstrip("/") + "/api/state", headers={"Authorization": "Bearer " + os.environ.get("APP_TOKEN", "")})
    with urlopen(request, timeout=5) as response:
        state = json.load(response)
    render_frame(state, mirror_x=args.mirror_x, mirror_y=args.mirror_y).save(args.output)


if __name__ == "__main__":
    main()
