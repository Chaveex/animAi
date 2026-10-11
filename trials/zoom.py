"""Zoom frames side by side on a neutral background (trial helper). usage: zoom.py out.png scale file1 file2 ... [--mark x,y]"""
import sys
from PIL import Image, ImageDraw
out, scale = sys.argv[1], int(sys.argv[2])
files = [a for a in sys.argv[3:] if not a.startswith("--mark")]
marks = [tuple(map(int, a.split("=")[1].split(","))) for a in sys.argv[3:] if a.startswith("--mark")]
ims = [Image.open(f).convert("RGBA") for f in files]
W = sum(i.width for i in ims) * scale + 8 * (len(ims) + 1); H = max(i.height for i in ims) * scale + 16
sheet = Image.new("RGBA", (W, H), (200, 60, 200, 255))
x = 8
d = ImageDraw.Draw(sheet)
for im in ims:
    big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    sheet.paste(big, (x, 8), big)
    for mx, my in marks:
        d.rectangle([x + mx * scale - 1, 8 + my * scale - 1, x + (mx + 1) * scale, 8 + (my + 1) * scale], outline=(255, 255, 0, 255))
    x += big.width + 8
sheet.save(out)
