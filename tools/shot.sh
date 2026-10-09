#!/bin/sh
# shot.sh NAME [x0 y0 x1 y1]: full-resolution BG3 screenshot to LootAdvisor/shots/NAME.png (+ NAME_crop.png if a
# pixel box in the 2560x1600 frame is given).
LA="$(cd "$(dirname "$0")/.." && (pwd -W 2>/dev/null || pwd))"   # this repo (Windows form for PowerShell/Python)
S="$LA/shots"
powershell -NoProfile -ExecutionPolicy Bypass -File "$LA/../BG3Tools/tools/bg3drive/crop.ps1" -Out "$S/$1.png" -MaxW 4000 < /dev/null > /dev/null
[ -n "$5" ] && python -c "
from PIL import Image; Image.open('$S/$1.png').crop(($2,$3,$4,$5)).save('$S/$1_crop.png')"
echo "$S/$1.png"
