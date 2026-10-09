#!/bin/sh
# shot.sh NAME [x0 y0 x1 y1]: full-resolution screenshot of the screen (bring BG3 to the front first) to
# LootAdvisor/shots/NAME.png (+ NAME_crop.png if a pixel box in the captured frame is given). Uses BG3Tools next to
# this repo (tools/testing/screenshot.ps1).
here=$(cd "$(dirname "$0")" && { pwd -W 2>/dev/null || pwd; })
S="$(dirname "$here")/shots"
mkdir -p "$S"
powershell -NoProfile -ExecutionPolicy Bypass -File "$(dirname "$(dirname "$here")")/BG3Tools/tools/testing/screenshot.ps1" -Out "$S/$1.png" -MaxW 4000 < /dev/null > /dev/null
[ -n "$5" ] && python -c "
from PIL import Image; Image.open('$S/$1.png').crop(($2,$3,$4,$5)).save('$S/$1_crop.png')"
echo "$S/$1.png"
