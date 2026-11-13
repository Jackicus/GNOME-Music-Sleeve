#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

# Take the metainfo screenshots again, in one step:
#
#     scripts/retake_screenshots.sh [--out DIR] [SUBJECT…]
#
# Each SUBJECT (by default the metainfo's own set, METAINFO below) is shot dark and light
# as DIR/<subject>-dark.png and DIR/<subject>-light.png (DIR: data/screenshots): the demo
# library, the default window size (1100x760, at scale 1) unless the subject sets one, with
# the window's shadow and rounded corners on a transparent background (screenshot.py
# --frame), as a window screenshot is. `all` names every subject below. It installs the
# build first (configure build/ with scripts/check.sh once), runs each shot on the private
# display of scripts/headless.sh with GSettings on the memory backend, so the Settings portal
# answers GNOME's defaults (the blue accent, the close button alone) and not the desktop's,
# and shrinks the pictures losslessly with oxipng, stripping their text chunks.
#
# screenshot.py runs the app as the release profile: no .Devel stripes, name or icon.

set -euo pipefail

cd "$(dirname "$0")/.."

METAINFO=(home albums album now-playing artist search)

# The subjects: each one's screenshot.py arguments.
declare -A SUBJECTS=(
    [home]='--page home --playing'
    [albums]='--page albums --playing'
    [album]='--page albums --open album:first --playing'
    [now-playing]='--page albums --now-playing syllable --position 16.7'
    [artist]='--page artists --open artist-page:1724041001 --playing'
    [search]='--search drift --search-in music --playing'
    [fullscreen-lyrics]='--page albums --fullscreen-player lyrics --position 40'
    [selection]='--page albums --open playlist:l.pl001 --select 3 --playing'
    [narrow]='--size 360x640 --page albums --open album:first --playing'
)
ORDER=(home albums album now-playing artist search fullscreen-lyrics selection narrow)

out=data/screenshots
subjects=()
while (($#)); do
    case $1 in
        --out) out=$2; shift 2 ;;
        all) subjects+=("${ORDER[@]}"); shift ;;
        -h|--help) sed -n '5,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)
            if [[ -z ${SUBJECTS[$1]+set} ]]; then
                echo "retake_screenshots.sh: no subject $1 (${ORDER[*]} or all)" >&2
                exit 2
            fi
            subjects+=("$1"); shift ;;
    esac
done
((${#subjects[@]})) || subjects=("${METAINFO[@]}")

command -v oxipng > /dev/null || { echo 'retake_screenshots.sh: needs oxipng' >&2; exit 1; }
meson install -C build --skip-subprojects --quiet
mkdir -p "$out"

for subject in "${subjects[@]}"; do
    read -r -a arguments <<< "${SUBJECTS[$subject]}"
    for scheme in dark light; do
        scheme_argument=()
        [[ $scheme == light ]] && scheme_argument=(--light)
        GSETTINGS_BACKEND=memory scripts/headless.sh python3 scripts/screenshot.py \
            "$out/$subject-$scheme.png" --demo --frame --signed-in 'Alex Rivera' \
            "${scheme_argument[@]}" "${arguments[@]}" > /dev/null
        echo "$out/$subject-$scheme.png"
    done
done

for subject in "${subjects[@]}"; do
    oxipng --quiet --opt 4 --strip safe "$out/$subject-dark.png" "$out/$subject-light.png"
done
