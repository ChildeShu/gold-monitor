#!/usr/bin/env python3
"""
Generate 洛书 App icons
- Golden square with "书" character (or "洛" character)
- Based on the existing gold icon design from the App
"""
from PIL import Image, ImageDraw, ImageFont
import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
BG = "#d4af37"  # Gold color matching the app's icon
FG = "#0a0a15"  # Dark text


def draw_icon(size, char="书"):
    """Draw a golden square icon with Chinese character."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rectangle background (matching the 7px border-radius from CSS)
    radius = int(size * 0.15)
    padding = 0
    rect = (padding, padding, size - padding, size - padding)
    draw.rounded_rectangle(rect, radius=radius, fill=BG)

    # Draw character
    # Try to use a system font, fallback to default
    font_size = int(size * 0.55)
    font = None
    for font_name in [
        "C:/Windows/Fonts/msyh.ttc",  # Microsoft YaHei
        "C:/Windows/Fonts/msyhl.ttc",  # Microsoft YaHei Light
        "C:/Windows/Fonts/simhei.ttf",  # SimHei
        "C:/Windows/Fonts/simsun.ttc",  # SimSun
    ]:
        if os.path.exists(font_name):
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except:
                pass

    if font is None:
        font = ImageFont.load_default()

    # Calculate text position to center
    bbox = draw.textbbox((0, 0), char, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2
    y = (size - text_h) // 2 - int(size * 0.05)  # Slight visual adjustment

    draw.text((x, y), char, fill=FG, font=font)

    return img


def main():
    # Generate 192x192 and 512x512 icons
    for size in [192, 512]:
        img = draw_icon(size, char="书")
        path = os.path.join(OUTPUT_DIR, f"icon-{size}.png")
        img.save(path, "PNG")
        print(f"[OK] Generated {path} ({size}x{size})")

    # Also generate a smaller favicon
    img = draw_icon(64, char="书")
    path = os.path.join(OUTPUT_DIR, "favicon.ico")
    img.save(path, "ICO")
    print(f"[OK] Generated {path}")

    print("\nDone! Icons are ready for the PWA.")


if __name__ == "__main__":
    main()
