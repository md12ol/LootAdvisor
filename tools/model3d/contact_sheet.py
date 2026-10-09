"""Tile PNG renders into one contact sheet: python tools/model3d/contact_sheet.py out.png cols w img1 img2 ..."""
import sys

from PIL import Image


def main(argv):
    out, cols, w = argv[1], int(argv[2]), int(argv[3])
    ims = [Image.open(p).convert("RGB") for p in argv[4:]]
    h = int(w * ims[0].height / ims[0].width)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (20, 16, 12))
    for i, im in enumerate(ims):
        sheet.paste(im.resize((w, h), Image.LANCZOS), ((i % cols) * w, (i // cols) * h))
    sheet.save(out)


if __name__ == "__main__":
    main(sys.argv)
