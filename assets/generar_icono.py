"""Genera assets/icon.png e icon.ico (lupa + check sobre fondo magenta). Requiere Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

AQUI = Path(__file__).resolve().parent
S = 1024  # se dibuja grande y se reduce (antialiasing)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=(194, 24, 91, 255))

# Lupa
cx, cy, r, grosor = 430, 430, 230, 70
d.ellipse((cx - r, cy - r, cx + r, cy + r), outline="white", width=grosor)
d.line((cx + 165, cy + 165, 820, 820), fill="white", width=110)
d.ellipse((820 - 55, 820 - 55, 820 + 55, 820 + 55), fill="white")

# Check dentro de la lupa
d.line((330, 440, 410, 520), fill="white", width=58)
d.line((410, 520, 545, 345), fill="white", width=58)
for x, y in ((330, 440), (410, 520), (545, 345)):
    d.ellipse((x - 29, y - 29, x + 29, y + 29), fill="white")

png = img.resize((256, 256), Image.LANCZOS)
png.save(AQUI / "icon.png")
img.save(AQUI / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Íconos generados en", AQUI)
