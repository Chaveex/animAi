"""Text dump of a sprite (trial helper, expert animation): one char per palette colour."""
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGBA")
w, h = im.size
px = im.load()
cols = {}
box = im.getbbox()
chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
x0, y0, x1, y1 = box
print("     " + "".join(str(x % 10) for x in range(x0, x1)), " x0=%d" % x0)
for y in range(y0, y1):
    row = ""
    for x in range(x0, x1):
        r, g, b, a = px[x, y]
        if a == 0:
            row += "."
        else:
            k = "#%02x%02x%02x" % (r, g, b)
            cols.setdefault(k, chars[len(cols)])
            row += cols[k]
    print("%3d  %s" % (y, row))
print(cols)
