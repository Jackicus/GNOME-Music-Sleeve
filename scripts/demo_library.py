#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A made-up Apple Music library for demo and screenshots:
`demo_library.py [--cache DIR] [--albums N] [--playlists N] [--tracks N] [--videos N]
[--long-playlist N]`.

Writes library.json in the shape src/backend/README.md describes, the covers
and thumbnails it names (drawn here, at config's COVER_SIZE and THUMB_SIZE)
and the art/.sizes marker, into DIR (default build/demo). Every artist, album,
song, playlist, station, curator and person in it is invented, the editors'
labels too ("Harbourlight Chill", "Harbourlight Radio", where Apple's say
"Apple Music"), and so is every cover, drawn here (draw_cover): no Apple mark,
real name or real artwork appears in it, nor so in a screenshot taken on it. It
came from the GNOME Shell extension with the backend, and is this app's own now.
`--albums N` (N > 40) adds generated albums, by generated artists, to the 40
hand-written ones, for measuring big libraries: about 12 songs an album, so
2,500 albums make 30,000 songs, or `--tracks N` songs in all when given (the
generated albums are sized to reach it). Their song titles are all distinct, as
a real library's nearly are (a word and a noun, then a tail or a number where
that pair is taken), so sorting and collating them costs what it would.
`--playlists N` (N > 13) adds
generated playlists, each of 22 songs, at the top level of the folders.
`--long-playlist N` adds one playlist of N of the library's songs (as many as it
has, at most), `l.pllong` ("The Long Playlist", at the top level, before
Favourite Songs), and `--videos N` (N > 6) generated music videos after the six
hand-written ones, by any of the artists: the lists a scroll test needs at size
(scroll_test.py --open playlist:l.pllong, --page music-videos). The other pages
(an artist's, the Radio, Search and Charts answers) keep the six videos. The
covers are drawn in parallel. The 40 hand-written albums and 13 playlists stay
as they are whatever the options: build/demo is byte-identical.
The last playlist is Favourite Songs, flagged by attributes.isFavourites.
Every album, playlist and music video has an invented `added` (the Recently Added
shelf's albums the newest), and `favourites` names Favourite Songs' songs, some
albums, playlists and a video, and one in twenty of the generated albums' songs
and albums (add_dates_and_favourites).
Three playlist folders, one inside another, hold some of the playlists; the
rest are at the top level (`folders`, whose "root" entry lists the top level).
sections.videos holds six invented music videos with 16:9 artwork, as Apple's
is (the thumbnails 320 x 180). Each hand-written artist also gets the page
Apple's catalog would answer for it (artists/<catalog id>.json, the shape
normalize.artist_page() gives: its top songs, latest release and shelves, made
of the demo's own albums, songs and videos and a few invented singles,
playlists, radio episodes and interviews, and for every third artist an invented
3:1 banner drawn here, the first artist's among them), each hand-written album what the
catalog would show under its tracks (albums/<catalog id>.json, the shape
normalize.album_page() gives: its release date, copyright and label, and its
shelves, made of the demo's own albums, videos and playlists and an invented
edition or two), each catalog playlist of the artists' pages what the catalog would
show under its tracks (playlists/<id>.json, normalize.playlist_page()'s shape: an
invented Apple curator, its page in categories/, and Featured Artists, More By the
curator and You Might Also Like of the demo's own artists and playlists), which the
demo engine answers from, and each playlist the songs Apple would suggest adding to it
(suggestions/<playlist id>.json, normalize.playlist_suggestions()'s shape:
twenty-four of the demo's own songs it does not hold), and the Radio page's answer
(radio.json, normalize.radio_shelves()'s shape: invented live stations, shows, episodes
and genre stations beside the demo's own albums and videos, each show's page in
categories/, all but the last under an invented banner), the catalog the demo's search
answers from (demo-search.json: its artists, albums, songs, playlists, videos and
stations, the Radio page's shows, and
invented curators with their pages in categories/), and the Charts page's
(charts.json, normalize.charts_shelves()'s shape: the demo's own songs, albums,
playlists and videos ranked, and invented Daily Top 100 and City Charts playlists of
its songs, for invented places; invented genres in genres.json, each genre's charts of
the demo's albums of it in charts/<id>.json), the Replay page's (replay.json and
replay/<year>.json, normalize.replay_page()'s shape: the demo's own songs, artists and
albums ranked for each invented year, and an invented Replay playlist of its songs for each
year), the New page's (browse.json,
normalize.editorial_shelves()'s shape: invented banners over the demo's own albums and
playlists, its shelves, and More to Explore's invented links, each link's page in rooms/,
groupings/ or multirooms/), and each hand-written album's songs' credits (credits/<catalog
id>.json, normalize.song_credits()'s shape: invented performers, writers, producers and
engineers; the last album's last song none). Last it writes .demo-stamp, the
record of what made it (demo_stamp.py), by which the harness and demo.sh know an out-of-date
build/demo and write it again. The other keys the app's sync adds
(sections.songs, artUrl) are optional and left out: the demo has no loose
songs and nothing to fetch.
Uses only Python stdlib and PyGObject / Cairo (no pip dependencies).
"""
import argparse
import concurrent.futures
import hashlib
import heapq
import importlib.util
import json
import math
import multiprocessing
import os
import pathlib
import random
import sys
from datetime import UTC, datetime

import cairo
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, GLib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The backend from the source tree, as tests/__init__.py loads it: src/ is laid
# out for installation and becomes the `applemusic` package only there.
if 'applemusic' not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        'applemusic', ROOT / 'src' / '__init__.py', submodule_search_locations=[str(ROOT / 'src')])
    _module = importlib.util.module_from_spec(_spec)
    sys.modules['applemusic'] = _module
    _spec.loader.exec_module(_module)

from applemusic.backend import config, normalize  # noqa: E402

# scripts/ is on the path when this runs as a script, not when a test loads it by its file.
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))
import demo_stamp  # noqa: E402

# ---------------------------------------------------------------------------
# Visual styling and palettes
# ---------------------------------------------------------------------------

PALETTES = [
    ('#0d1b2a', '#1b4965', '#62b6cb'),  # Deep ocean
    ('#10002b', '#5a189a', '#e0aaff'),  # Violet nebula
    ('#1f2421', '#499f68', '#dce2aa'),  # Sage forest
    ('#2b0914', '#d90429', '#ffb4a2'),  # Crimson velvet
    ('#0a1128', '#0077b6', '#90e0ef'),  # Electric ice
    ('#1c1917', '#d97706', '#fef3c7'),  # Amber glow
    ('#240046', '#9d4edd', '#ff9e00'),  # Synthwave dusk
    ('#002830', '#0081a7', '#fdfcdc'),  # Nordic fjord
    ('#1a1423', '#5c3d75', '#eac435'),  # Midnight & gold
    ('#14213d', '#fca311', '#e5e5e5'),  # Navy & marigold
    ('#1b263b', '#e76f51', '#f4a261'),  # Sunset terrace
    ('#073b3a', '#0b6e4f', '#80ed99'),  # Emerald canopy
    ('#2e1f27', '#854d27', '#dd722a'),  # Terracotta autumn
    ('#212529', '#495057', '#e9c46a'),  # Graphite and mustard
    ('#132a13', '#31572c', '#90a955'),  # Olive ridge
    ('#2b2d42', '#8d99ae', '#ef233c'),  # Slate & scarlet
    ('#180018', '#7209b7', '#4cc9f0'),  # Cyber violet
    ('#2c1b18', '#a75d5d', '#ffc3a0'),  # Dusty rose & coffee
    ('#0b132b', '#1c2541', '#5bc0be'),  # Midnight teal
    ('#1e1e24', '#444140', '#e54b4b'),  # Charcoal & coral
    ('#023047', '#219ebc', '#ffb703'),  # Mediterranean harbor
    ('#2b1e3a', '#a23b72', '#f18f01'),  # Twilight plum
    ('#1a202c', '#4a5568', '#f6ad55'),  # Slate and apricot
    ('#1d3557', '#457b9d', '#a8dadc'),  # Atlantic blues
    ('#3d0c11', '#d1495b', '#edae49'),  # Rich garnet
    ('#2d2a26', '#b5654a', '#e8c9a0'),  # Terracotta clay
    ('#1f2a2e', '#5f7c74', '#c9d6c3'),  # Eucalyptus
    ('#2a2135', '#b07ba6', '#f2d0c9'),  # Dusk rose
    ('#22313f', '#c9a227', '#efe3c2'),  # Ink and ochre
    ('#1b1b1b', '#3f6e8c', '#f0ede5'),  # Denim
    ('#3a1f1d', '#c44536', '#f7e1c3'),  # Tomato and cream
    ('#16302b', '#c86b3c', '#f3c98b'),  # Pine and rust
    ('#2b2f3a', '#9aa5b1', '#f6d365'),  # Steel and butter
]

# Each hand-written artist's About: where they are from, when born or formed (Apple's own
# words for it), and whether they are a group.
ARTIST_FACTS = [
    ('Stromness, Orkney, Scotland', '2011', True),
    ('Rotterdam, Netherlands', '2014', True),
    ('Tofino, BC, Canada', '2016', True),
    ('Kanazawa, Japan', '2009', True),
    ('Lisbon, Portugal', '2017', True),
    ('Reykjavík, Iceland', '2012', True),
    ('Bristol, England', '2015', True),
    ('Gothenburg, Sweden', '2010', True),
    ('Sapporo, Japan', '4 March 1991', False),
    ('Ghent, Belgium', '2013', True),
    ('Wellington, New Zealand', '2018', True),
    ('Leipzig, Germany', '2016', True),
    ('Galway, Ireland', '2019', True),
    ('Tallinn, Estonia', '2014', True),
    ('New Orleans, LA, United States', '2008', True),
]

# The radio shows an artist's episodes air on, and the words an episode or an interview takes.
DEMO_SHOWS = ['Lighthouse One', 'Slow Tide Radio', 'The Long Play', 'Night Shift']
# The radio shows the invented artists host (their pages' Radio Shows).
DEMO_HOSTED_SHOWS = ['{artist} Radio', 'Late Lights with {artist}', 'The {artist} Hour']
DEMO_EPISODES = ['{artist} in Conversation', 'The Making of {album}', '{genre} Spotlight',
                 'A Night with {artist}']
DEMO_INTERVIEWS = ['{artist} on {album}', '{artist}: Behind the Songs', 'Live from the Studio']
SUGGESTIONS = 24  # a playlist's suggested songs: twelve shown at most, and spares
# The record labels of the hand-written albums' footers (one an artist), and the other
# editions an album's Other Versions offers (the first always, the second every other album).
DEMO_LABELS = ['Lowtide Recordings', 'Paper Lantern Records', 'Driftwood Audio',
               'Quiet Harbour Music', 'Northlight Sound']
DEMO_EDITIONS = ['{title} (Deluxe)', '{title} (Remastered)']
# The first artist's album to come (Apple's isPrerelease): its songs, two of them out already
# as singles (the others have no playParams in Apple's answer: `unreleased`), and its date.
DEMO_UPCOMING = ('Lanterns Over the Reef', '2030-12-04', [
    ('First Light on the Breakwater', False), ('Harbour Signal', True),
    ('The Drowned Orchard', False), ('Lantern Procession', True), ('Saltglass', False),
    ('Underneath the Pier Lights', False), ('Tidewater Hymn', False),
    ('Reef at Dusk', False)])
# The people of the hand-written albums' songs' credits beside their artists (credits/), and
# the roles they are credited with, by Apple's kinds of credit (normalize.song_credits).
DEMO_CREDIT_PEOPLE = ['Ada Brightwater', 'Bram Holloway', 'Cleo Ashdown', 'Dario Fenwick',
                      'Elin Marlowe', 'Felix Dunmore', 'Greta Sallow', 'Hugo Penrith',
                      'Ines Quarry', 'Jonah Thistle', 'Kira Wendle', 'Lars Okewood',
                      'Mira Castell', 'Nico Harrowgate', 'Odile Fenn', 'Pavel Lindqvist']
DEMO_PERFORMER_ROLES = [['Vocals'], ['Guitar'], ['Bass'], ['Drums'], ['Keyboards'],
                        ['Synthesizer', 'Programming'], ['Strings'], ['Backing Vocals']]
DEMO_WRITER_ROLES = [['Composer', 'Lyricist'], ['Composer'], ['Lyricist'], ['Songwriter']]
DEMO_PRODUCTION_ROLES = [['Producer'], ['Producer', 'Recording Engineer'], ['Mixing Engineer'],
                         ['Mastering Engineer'], ['Assistant Engineer']]
# Apple's headings for its kinds of credit, as it titles them in English.
DEMO_CREDIT_TITLES = {'performer': 'Performers', 'composer-and-lyrics': 'Composition & Lyrics',
                      'production-and-engineering': 'Production & Engineering'}
# The Radio page's invented live stations (the first is the library's own first station),
# each with the programme it is shown airing (the demo's answer has no times, so no
# `events`: the subtitle stands for what is on air), its radio shows (each with its host)
# and its genre stations.
DEMO_LIVE = [('Lighthouse One', 'The Morning Tide with Mara Quinn'),
             ('Lighthouse Hits', 'Evergreen Requests with Theo Marsh'),
             ('Lighthouse Country', 'Back Roads with June Calloway'),
             ('Lighthouse Club', 'After Hours with DJ Selkie')]
DEMO_RADIO_SHOWS = [('The Morning Tide', 'Mara Quinn'), ('Evergreen Requests', 'Theo Marsh'),
                    ('Back Roads', 'June Calloway'), ('The Long Play', 'Ines Varga')]
# The Charts page's invented places: a Daily Top 100 for the world and each of these
# countries, and a City Chart for each of these cities.
DEMO_CHART_COUNTRIES = ['Northmarch', 'Isle of Avery', 'Calder Coast', 'Westerly Reach']
DEMO_CHART_CITIES = ['Port Avery', 'Fernhollow', 'Saltmere', 'Kestrel Bay', 'Lindenford',
                     'Marlow Heights']
# Its invented genres (genres.json, in this order): an id of the kind Apple's are (digits),
# the name, and the demo albums' genres that make the genre's charts (charts/<id>.json).
DEMO_CHART_GENRES = [
    ('9001', 'Alternative', ('Post-Rock', 'Shoegaze', 'Math Rock', 'Indie Pop', 'Indie Folk',
                             'Dream Pop')),
    ('9002', 'Electronic', ('Synthwave', 'Synthpop', 'Electronic', 'Deep House',
                            'Melodic Techno')),
    ('9003', 'Jazz', ('Nu-Jazz', 'Funk & Jazz', 'Contemporary Jazz')),
    ('9004', 'Classical', ('Modern Classical', 'Cinematic')),
    ('9005', 'R&B/Soul', ('Neo-Soul',)),
    ('9006', 'Hip-Hop/Rap', ('Lo-Fi Hip-Hop',)),
    ('9007', 'Ambient', ('Ambient', 'Downtempo')),
]
# The years of the demo's invented Replay, newest first: the latest year's answer is
# replay.json, each earlier year's replay/<year>.json.
DEMO_REPLAY_YEARS = ('2026', '2025', '2024')
DEMO_GENRE_STATIONS = [('Coastal Indie', 'Indie & Alternative'), ('Night Jazz', 'Jazz'),
                       ('Harbour Folk', 'Folk'), ('Deep Focus', 'Ambient'),
                       ('Northern Soul Kitchen', 'R&B/Soul'), ('Tape Hiss Classics', 'Rock')]
# The search's curators: Apple-like editors, whose tile opens a page of their playlists, and
# a third party's (a label's), which has no page in the app (music.apple.com's, in the demo
# refused). None plays.
DEMO_SEARCH_CURATORS = [('Harbourlight Chill', 'apple'), ('Harbourlight Jazz', 'apple'),
                        ('Night Tide Editors', 'apple'), ('Paper Lantern Records', 'label')]

# The covers' designs, each a whole picture drawn on the 512-unit square (draw_cover). An
# album's follows its genre (GENRE_MOTIFS), so an artist's records look of a piece and a
# shelf of them varied; anything else's is chosen by its index.
MOTIFS = [
    'aurora',
    'dunes',
    'bauhaus',
    'bokeh',
    'contours',
    'colour_field',
    'orbit',
    'mosaic',
    'swiss',
    'ribbons',
    'horizon_grid',
    'arch',
]

GENRE_MOTIFS = {
    'Post-Rock': ['dunes', 'contours', 'ribbons'],
    'Synthwave': ['horizon_grid', 'orbit', 'ribbons'],
    'Electronic': ['orbit', 'ribbons', 'swiss'],
    'Indie Folk': ['dunes', 'arch', 'colour_field'],
    'Modern Classical': ['contours', 'colour_field', 'arch'],
    'Dream Pop': ['bokeh', 'aurora', 'ribbons'],
    'Synthpop': ['aurora', 'bokeh', 'horizon_grid'],
    'Ambient': ['aurora', 'orbit', 'contours'],
    'Neo-Soul': ['colour_field', 'bokeh', 'swiss'],
    'Shoegaze': ['bokeh', 'aurora', 'colour_field'],
    'Nu-Jazz': ['swiss', 'bauhaus', 'mosaic'],
    'Cinematic': ['dunes', 'orbit', 'colour_field'],
    'Lo-Fi Hip-Hop': ['mosaic', 'arch', 'bauhaus'],
    'Deep House': ['ribbons', 'swiss', 'orbit'],
    'Melodic Techno': ['contours', 'ribbons', 'swiss'],
    'Indie Pop': ['bauhaus', 'mosaic', 'arch'],
    'Math Rock': ['mosaic', 'bauhaus', 'swiss'],
    'Funk & Jazz': ['mosaic', 'bauhaus', 'swiss'],
    'Contemporary Jazz': ['colour_field', 'bokeh', 'swiss'],
}

# The badges of what editors make (a playlist, a station, a show, a chart): their covers
# carry the title large, as a streaming service's own do; an album's has its words small,
# or none.
EDITORIAL_BADGES = {'PLAYLIST', 'RADIO', 'LIVE', 'SHOW', 'REPLAY', 'TOP 100', 'TOP 25'}
PAPER = (0.945, 0.918, 0.859)  # the light covers' ground, an off-white paper


def album_motif(genre, index):
    """The design of an album of `genre`, the index-th of the library."""
    choices = GENRE_MOTIFS.get(genre)
    return choices[index % len(choices)] if choices else MOTIFS[index % len(MOTIFS)]


def hex_to_rgb(hex_code):
    """Convert hex string '#rrggbb' to (r, g, b) float tuple in 0..1."""
    h = hex_code.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def mix(first, second, amount):
    """The colour `amount` of the way from `first` to `second`."""
    return tuple(a + (b - a) * amount for a, b in zip(first, second, strict=True))


def wrap_text(ctx, text, max_width, font_size):
    """Wrap text to fit within max_width using Cairo text extents."""
    ctx.set_font_size(font_size)
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        trial = ' '.join(current_line + [word])
        extents = ctx.text_extents(trial)
        if extents.width <= max_width or not current_line:
            current_line.append(word)
        else:
            lines.append(' '.join(current_line))
            current_line = [word]
    if current_line:
        lines.append(' '.join(current_line))
    return lines


def spaced_width(ctx, text, spacing):
    """The width of text shown by show_spaced()."""
    return sum(ctx.text_extents(char).x_advance for char in text) + spacing * (len(text) - 1)


def show_spaced(ctx, text, x, y, spacing):
    """Show text letter-spaced, as a sleeve's small capitals are, from (x, y)."""
    for char in text:
        ctx.move_to(x, y)
        ctx.show_text(char)
        x += ctx.text_extents(char).x_advance + spacing


_GRAIN = []


def grain_pattern():
    """A tile of film grain, mid-grey noise painted over a cover with OVERLAY: made once in
    each process, from a fixed seed, so a cover's grain is the same every time."""
    if not _GRAIN:
        rnd = random.Random(5)
        size = 160
        pixels = bytearray()
        for _pixel in range(size * size):
            value = max(0, min(255, int(rnd.gauss(128, 42))))
            pixels += bytes((value, value, value, 255))
        surface = cairo.ImageSurface.create_for_data(pixels, cairo.FORMAT_ARGB32, size, size,
                                                     size * 4)
        pattern = cairo.SurfacePattern(surface)
        pattern.set_extend(cairo.EXTEND_REPEAT)
        _GRAIN.append((pixels, surface, pattern))
    return _GRAIN[0][2]


def radial_glow(ctx, x, y, radius, colour, alpha):
    """A soft light of `colour`, fading out from (x, y) over `radius`."""
    glow = cairo.RadialGradient(x, y, 0, x, y, radius)
    glow.add_color_stop_rgba(0.0, *colour, alpha)
    glow.add_color_stop_rgba(1.0, *colour, 0.0)
    ctx.set_source(glow)
    ctx.paint()


def hill_path(ctx, rnd, base, amplitude, step=8):
    """A hill line across the square at `base`, a sum of two slow sines, closed below."""
    waves = [(rnd.uniform(0.004, 0.012), rnd.uniform(0, 2 * math.pi), amplitude),
             (rnd.uniform(0.015, 0.03), rnd.uniform(0, 2 * math.pi), amplitude * 0.35)]
    ctx.move_to(0, 512)
    for x in range(0, 513, step):
        ctx.line_to(x, base + sum(a * math.sin(f * x + p) for f, p, a in waves))
    ctx.line_to(512, 512)
    ctx.close_path()


# Each design paints the whole square and returns the colours words take on it at the top
# and at the bottom (None where words would not read).

def motif_aurora(ctx, rnd, dark, mid, light):
    ctx.set_source_rgb(*dark)
    ctx.paint()
    # A glow in each quarter, in an order of its own, so the colours never pool in one place.
    corners = [(128, 128), (384, 128), (128, 384), (384, 384)]
    rnd.shuffle(corners)
    for (x, y), (colour, alpha) in zip(corners, ((mid, 1.0), (light, 0.85),
                                                  (mix(mid, light, 0.5), 0.8), (mid, 0.9)),
                                       strict=True):
        radial_glow(ctx, x + rnd.uniform(-70, 70), y + rnd.uniform(-70, 70),
                    rnd.uniform(200, 300), colour, alpha)
    radial_glow(ctx, rnd.uniform(100, 412), rnd.uniform(100, 412), 160, dark, 0.7)
    return (1, 1, 1), (1, 1, 1)


def motif_dunes(ctx, rnd, dark, mid, light):
    sky = cairo.LinearGradient(0, 0, 0, 330)
    sky.add_color_stop_rgb(0.0, *mix(mid, light, 0.55))
    sky.add_color_stop_rgb(1.0, *mix(light, (1, 1, 1), 0.35))
    ctx.set_source(sky)
    ctx.paint()
    ctx.arc(rnd.uniform(130, 380), rnd.uniform(170, 230), rnd.uniform(42, 70), 0, 2 * math.pi)
    ctx.set_source_rgba(*mix(light, (1, 1, 1), 0.6), 0.95)
    ctx.fill()
    for layer in range(4):
        ctx.set_source_rgb(*mix(mix(light, mid, 0.4), dark, (layer + 1) / 4.4))
        hill_path(ctx, rnd, 262 + layer * 58, rnd.uniform(14, 30))
        ctx.fill()
    return mix(dark, mid, 0.2), mix(light, (1, 1, 1), 0.5)


def motif_bauhaus(ctx, rnd, dark, mid, light):
    ctx.set_source_rgb(*mix(PAPER, light, 0.12))
    ctx.paint()
    colours = [dark, mid, mix(mid, dark, 0.45), mix(mid, light, 0.35)]
    # Three rows of shapes from the top, the bottom kept clear for the words.
    cell, left, top = 120, 76, 44
    for row in range(3):
        for column in range(3):
            shape = rnd.choice(['circle', 'half', 'quarter', 'square', 'bars', None, None])
            if shape is None:
                continue
            ctx.save()
            ctx.translate(left + (column + 0.5) * cell, top + (row + 0.5) * cell)
            ctx.rotate(rnd.choice([0, 0.5, 1, 1.5]) * math.pi)
            ctx.set_source_rgb(*rnd.choice(colours))
            half = cell / 2 - 4
            if shape == 'circle':
                ctx.arc(0, 0, half, 0, 2 * math.pi)
            elif shape == 'half':
                ctx.arc(0, half, half * 2, math.pi, 2 * math.pi)
                ctx.close_path()
                ctx.save()
                ctx.rectangle(-half, -half, half * 2, half * 2)
                ctx.clip()
                ctx.fill()
                ctx.restore()
            elif shape == 'quarter':
                ctx.move_to(-half, -half)
                ctx.arc(-half, -half, half * 2, 0, math.pi / 2)
                ctx.close_path()
            elif shape == 'square':
                ctx.rectangle(-half, -half, half * 2, half * 2)
            else:
                for bar in range(4):
                    ctx.rectangle(-half, -half + bar * half / 2, half * 2, half / 4)
            ctx.fill()
            ctx.restore()
    return None, dark


def motif_bokeh(ctx, rnd, dark, mid, light):
    ground = cairo.LinearGradient(0, 0, 0, 512)
    ground.add_color_stop_rgb(0.0, *dark)
    ground.add_color_stop_rgb(1.0, *mix(dark, mid, 0.55))
    ctx.set_source(ground)
    ctx.paint()
    warm = mix(light, (1.0, 0.86, 0.62), 0.4)
    for _light in range(46):
        x, y, r = rnd.uniform(-20, 532), rnd.uniform(-20, 532), rnd.uniform(12, 68)
        colour = rnd.choice([mid, light, warm, mix(mid, light, 0.5)])
        alpha = rnd.uniform(0.18, 0.55)
        disc = cairo.RadialGradient(x, y, 0, x, y, r)
        disc.add_color_stop_rgba(0.0, *colour, alpha * 0.7)
        disc.add_color_stop_rgba(0.82, *colour, alpha)
        disc.add_color_stop_rgba(1.0, *colour, 0.0)
        ctx.arc(x, y, r, 0, 2 * math.pi)
        ctx.set_source(disc)
        ctx.fill()
    return (1, 1, 1), (1, 1, 1)


def motif_contours(ctx, rnd, dark, mid, light):
    ground = cairo.LinearGradient(0, 0, 512, 512)
    ground.add_color_stop_rgb(0.0, *mix(dark, mid, 0.6))
    ground.add_color_stop_rgb(1.0, *dark)
    ctx.set_source(ground)
    ctx.paint()
    for peak in range(2):
        cx, cy = rnd.uniform(130, 380), rnd.uniform(130, 380)
        phases = [rnd.uniform(0, 2 * math.pi) for _ in range(3)]
        for level in range(16 if peak == 0 else 7):
            radius = 14 + level * 19
            ctx.new_path()
            for step in range(121):
                angle = step / 120 * 2 * math.pi
                wobble = (1 + 0.16 * math.sin(2 * angle + phases[0] + level * 0.15)
                          + 0.08 * math.sin(3 * angle + phases[1])
                          + 0.05 * math.sin(5 * angle + phases[2] - level * 0.2))
                ctx.line_to(cx + math.cos(angle) * radius * wobble,
                            cy + math.sin(angle) * radius * wobble * 0.92)
            ctx.close_path()
            ctx.set_line_width(1.8 if level % 4 == 0 else 1.0)
            ctx.set_source_rgba(*light, 0.6 if level % 4 == 0 else 0.35)
            ctx.stroke()
    return (1, 1, 1), (1, 1, 1)


def soft_rect(ctx, x, y, width, height, colour, alpha=1.0, softness=14):
    """A rectangle with feathered edges, as paint soaked into canvas."""
    for step in range(softness, 0, -2):
        ctx.rectangle(x - step, y - step, width + 2 * step, height + 2 * step)
        ctx.set_source_rgba(*colour, alpha * 0.14)
        ctx.fill()
    ctx.rectangle(x, y, width, height)
    ctx.set_source_rgba(*colour, alpha * 0.9)
    ctx.fill()


def motif_colour_field(ctx, rnd, dark, mid, light):
    ctx.set_source_rgb(*mix(mid, dark, 0.25))
    ctx.paint()
    split = rnd.uniform(230, 290)
    soft_rect(ctx, 46, 44, 420, split - 64, mix(light, mid, rnd.uniform(0.1, 0.4)))
    soft_rect(ctx, 46, split + 12, 420, 456 - split, mix(dark, mid, 0.35))
    if rnd.random() < 0.5:
        soft_rect(ctx, 46, split - 6, 420, 10, mix(mid, light, 0.6), 0.8, 6)
    return None, mix(light, (1, 1, 1), 0.4)


def motif_orbit(ctx, rnd, dark, mid, light):
    ctx.set_source_rgb(*mix(dark, (0, 0, 0), 0.3))
    ctx.paint()
    for _star in range(90):
        ctx.arc(rnd.uniform(0, 512), rnd.uniform(0, 512), rnd.uniform(0.6, 2.0), 0, 2 * math.pi)
        ctx.set_source_rgba(*mix(light, (1, 1, 1), 0.5), rnd.uniform(0.25, 0.9))
        ctx.fill()
    x, y, r = rnd.uniform(200, 312), rnd.uniform(220, 300), rnd.uniform(96, 130)
    radial_glow(ctx, x, y, r * 2.2, mid, 0.45)
    body = cairo.RadialGradient(x - r * 0.4, y - r * 0.45, r * 0.1, x, y, r)
    body.add_color_stop_rgb(0.0, *mix(light, (1, 1, 1), 0.3))
    body.add_color_stop_rgb(0.55, *mid)
    body.add_color_stop_rgb(1.0, *mix(dark, mid, 0.3))
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.set_source(body)
    ctx.fill()
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(-rnd.uniform(0.2, 0.45))
    ctx.scale(1, 0.24)
    ctx.arc(0, 0, r * 1.75, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_line_width(2.5)
    ctx.set_source_rgba(*light, 0.75)
    ctx.stroke()
    return (1, 1, 1), (1, 1, 1)


def motif_mosaic(ctx, rnd, dark, mid, light):
    count = rnd.choice([4, 5, 6])
    cell = 512 / count
    colours = [dark, mid, light, mix(dark, mid, 0.5), mix(mid, light, 0.5), PAPER]
    for row in range(count):
        for column in range(count):
            x, y = column * cell, row * cell
            ground = rnd.choice(colours)
            ctx.rectangle(x, y, cell + 0.5, cell + 0.5)
            ctx.set_source_rgb(*ground)
            ctx.fill()
            if rnd.random() < 0.45:
                ctx.set_source_rgb(*rnd.choice([c for c in colours if c != ground]))
                if rnd.random() < 0.5:
                    ctx.arc(x + cell / 2, y + cell / 2, cell * 0.36, 0, 2 * math.pi)
                else:
                    corner = rnd.randrange(4)
                    cx = x + (cell if corner in (1, 2) else 0)
                    cy = y + (cell if corner >= 2 else 0)
                    ctx.move_to(cx, cy)
                    ctx.arc(cx, cy, cell, (corner + 2) * math.pi / 2, (corner + 3) * math.pi / 2)
                    ctx.close_path()
                ctx.save()
                ctx.rectangle(x, y, cell, cell)
                ctx.clip()
                ctx.fill()
                ctx.restore()
    return None, None


def motif_ribbons(ctx, rnd, dark, mid, light):
    ground = cairo.LinearGradient(0, 0, 0, 512)
    ground.add_color_stop_rgb(0.0, *mix(dark, (0, 0, 0), 0.2))
    ground.add_color_stop_rgb(1.0, *dark)
    ctx.set_source(ground)
    ctx.paint()
    base = rnd.uniform(220, 290)
    freq, phase = rnd.uniform(0.008, 0.014), rnd.uniform(0, 2 * math.pi)
    twist = rnd.uniform(0.02, 0.05)
    for line in range(70):
        ctx.new_path()
        for x in range(-10, 523, 6):
            y = (base + math.sin(x * freq + phase) * 60
                 + math.sin(x * freq * 0.5 + line * twist) * (line - 35) * 1.4)
            ctx.line_to(x, y)
        ctx.set_line_width(1.1)
        ctx.set_source_rgba(*mix(mid, light, line / 70), 0.55)
        ctx.stroke()
    return (1, 1, 1), (1, 1, 1)


def motif_horizon_grid(ctx, rnd, dark, mid, light):
    horizon = 300
    sky = cairo.LinearGradient(0, 0, 0, horizon)
    sky.add_color_stop_rgb(0.0, *mix(dark, (0, 0, 0), 0.3))
    sky.add_color_stop_rgb(1.0, *mid)
    ctx.set_source(sky)
    ctx.rectangle(0, 0, 512, horizon)
    ctx.fill()
    radius = rnd.uniform(95, 125)
    sun = cairo.LinearGradient(0, horizon - radius * 1.4, 0, horizon)
    sun.add_color_stop_rgb(0.0, *mix(light, (1, 1, 1), 0.4))
    sun.add_color_stop_rgb(1.0, *mix(light, mid, 0.5))
    ctx.save()
    ctx.rectangle(0, 0, 512, horizon)
    ctx.clip()
    ctx.arc(256, horizon - radius * 0.35, radius, 0, 2 * math.pi)
    ctx.set_source(sun)
    ctx.fill()
    ctx.set_source_rgb(*mid)
    for band in range(6):
        ctx.rectangle(0, horizon - 8 - band * 13, 512, 6 - band * 0.8)
        ctx.fill()
    ctx.restore()
    ctx.set_source_rgb(*mix(dark, (0, 0, 0), 0.4))
    ctx.rectangle(0, horizon, 512, 512 - horizon)
    ctx.fill()
    ctx.set_line_width(1.3)
    ctx.set_source_rgba(*light, 0.55)
    for column in range(-12, 13):
        ctx.move_to(256 + column * 12, horizon)
        ctx.line_to(256 + column * 90, 512)
        ctx.stroke()
    for row in range(9):
        y = horizon + (512 - horizon) * (row / 8) ** 2
        ctx.move_to(0, y)
        ctx.line_to(512, y)
        ctx.stroke()
    return (1, 1, 1), None


def motif_arch(ctx, rnd, dark, mid, light):
    wall = mix(PAPER, light, 0.3)
    ctx.set_source_rgb(*wall)
    ctx.paint()
    floor = rnd.uniform(370, 410)
    ctx.set_source_rgb(*mix(wall, mid, 0.25))
    ctx.rectangle(0, floor, 512, 512 - floor)
    ctx.fill()
    width = rnd.uniform(170, 230)
    left = 256 - width / 2
    top = rnd.uniform(110, 150)
    ctx.move_to(left, floor)
    ctx.line_to(left, top + width / 2)
    ctx.arc(256, top + width / 2, width / 2, math.pi, 0)
    ctx.line_to(left + width, floor)
    ctx.close_path()
    ctx.set_source_rgb(*mid)
    ctx.fill()
    inner = width * 0.58
    ctx.move_to(256 - inner / 2, floor)
    ctx.arc(256, top + width / 2 + 30, inner / 2, math.pi, 0)
    ctx.line_to(256 + inner / 2, floor)
    ctx.close_path()
    ctx.set_source_rgb(*dark)
    ctx.fill()
    ctx.arc(256 + rnd.choice([-1, 1]) * width * 0.78, top + 10, rnd.uniform(22, 34), 0,
            2 * math.pi)
    ctx.set_source_rgb(*mix(mid, light, 0.3))
    ctx.fill()
    return dark, dark


def motif_swiss(ctx, rnd, dark, mid, light, title, subtitle):
    """Type as the picture: the title's first word set huge, a rule, a block of small type,
    a disc of colour."""
    paper = rnd.random() < 0.5
    ground, ink = (mix(PAPER, light, 0.1), dark) if paper else (mid, mix(light, (1, 1, 1), 0.5))
    ctx.set_source_rgb(*ground)
    ctx.paint()
    ctx.arc(rnd.uniform(300, 420), rnd.uniform(290, 380), rnd.uniform(60, 100), 0, 2 * math.pi)
    ctx.set_source_rgb(*(mid if paper else dark))
    ctx.fill()
    words = title.split()
    word = (' '.join(words[:2]) if len(words) > 1 and len(words[0]) <= 3 else words[0]).upper()
    ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    size = 200
    ctx.set_font_size(size)
    while size > 40 and ctx.text_extents(word).width > 440:
        size -= 4
        ctx.set_font_size(size)
    extents = ctx.text_extents(word)
    ctx.set_source_rgb(*ink)
    ctx.move_to(36 - extents.x_bearing, 40 - extents.y_bearing)
    ctx.show_text(word)
    rule = 40 + extents.height + 22
    ctx.set_line_width(3)
    ctx.move_to(36, rule)
    ctx.line_to(476, rule)
    ctx.stroke()
    ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(15)
    for number, line in enumerate([subtitle or '', title]):
        ctx.move_to(36, 452 + number * 22)
        ctx.show_text(line)


MOTIF_DRAW = {
    'aurora': motif_aurora, 'dunes': motif_dunes, 'bauhaus': motif_bauhaus,
    'bokeh': motif_bokeh, 'contours': motif_contours, 'colour_field': motif_colour_field,
    'orbit': motif_orbit, 'mosaic': motif_mosaic, 'ribbons': motif_ribbons,
    'horizon_grid': motif_horizon_grid, 'arch': motif_arch,
}


def draw_portrait(ctx, rnd, dark, mid, light, figures):
    """An artist's photograph as a silhouette: stage light behind, a rim of light on each
    figure. The tile crops the square to its inscribed circle, so all that matters sits well
    inside it, and no words are drawn: the views print the name beside it."""
    ground = cairo.LinearGradient(0, 0, 0, 512)
    ground.add_color_stop_rgb(0.0, *mix(dark, mid, 0.5))
    ground.add_color_stop_rgb(1.0, *dark)
    ctx.set_source(ground)
    ctx.paint()
    radial_glow(ctx, rnd.uniform(200, 312), rnd.uniform(150, 230), 300,
                mix(light, mid, 0.3), 0.75)
    for _speck in range(30):
        ctx.arc(rnd.uniform(60, 452), rnd.uniform(60, 300), rnd.uniform(1, 3), 0, 2 * math.pi)
        ctx.set_source_rgba(*light, rnd.uniform(0.2, 0.5))
        ctx.fill()
    # Lit from one side: the figures' near side catches the light.
    side = rnd.choice([-1, 1])
    # The outer figures first, the middle one, the tallest, last: in front.
    for number in sorted(range(figures), key=lambda n: -abs(n - (figures - 1) / 2)):
        offset = (number - (figures - 1) / 2) * 125
        ctx.save()
        ctx.translate(256 + offset + rnd.uniform(-8, 8), 500 if offset == 0 else 470)
        ctx.scale(*((1.0, 1.0) if offset == 0 else (0.82, 0.82)))
        ctx.rotate(rnd.uniform(-0.05, 0.05))
        ctx.new_path()
        ctx.save()
        ctx.translate(rnd.uniform(-6, 6), -268)
        ctx.scale(0.84, 1.0)
        ctx.arc(0, 0, 62, 0, 2 * math.pi)
        ctx.restore()
        ctx.new_sub_path()
        ctx.move_to(-190, 40)
        ctx.curve_to(-182, -100, -120, -140, -46, -158)
        ctx.line_to(-34, -205)
        ctx.line_to(34, -205)
        ctx.line_to(46, -158)
        ctx.curve_to(120, -140, 182, -100, 190, 40)
        ctx.close_path()
        path = ctx.copy_path()
        shade = cairo.LinearGradient(-190 * side, 0, 190 * side, 0)
        shade.add_color_stop_rgb(0.0, *mix(dark, (0, 0, 0), 0.5))
        shade.add_color_stop_rgb(1.0, *mix(dark, mid, 0.35))
        ctx.set_source(shade)
        ctx.fill()
        ctx.append_path(path)
        rim = cairo.LinearGradient(-190 * side, 0, 190 * side, 0)
        rim.add_color_stop_rgba(0.0, *light, 0.0)
        rim.add_color_stop_rgba(1.0, *mix(light, (1, 1, 1), 0.3), 0.7)
        ctx.set_line_width(3)
        ctx.set_source(rim)
        ctx.stroke()
        ctx.restore()


def draw_words(ctx, rnd, title, subtitle, badge, inks):
    """The cover's words: an editorial cover's title large at the bottom; an album's in one
    of a few sleeve layouts, small and quiet, or none at all, as most sleeves have."""
    ink_top, ink_bottom = inks
    if badge in EDITORIAL_BADGES:
        if ink_bottom is None:
            ink_bottom = (1, 1, 1)
            scrim = cairo.LinearGradient(0, 300, 0, 512)
            scrim.add_color_stop_rgba(0.0, 0, 0, 0, 0.0)
            scrim.add_color_stop_rgba(1.0, 0, 0, 0, 0.6)
            ctx.set_source(scrim)
            ctx.paint()
        ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        size = 40
        lines = wrap_text(ctx, title, 430, size)
        if len(lines) > 2:
            size = 32
            lines = wrap_text(ctx, title, 430, size)
        ctx.set_source_rgb(*ink_bottom)
        for number, line in enumerate(lines):
            ctx.move_to(36, 476 - (len(lines) - 1 - number) * round(size * 1.12))
            ctx.show_text(line)
        return
    layout = rnd.choice(['none', 'none', 'top_small', 'bottom_serif', 'top_centre'])
    if layout in ('top_small', 'top_centre') and ink_top is None:
        layout = 'bottom_serif'
    if layout == 'bottom_serif' and ink_bottom is None:
        layout = 'top_small' if ink_top is not None else 'none'
    if layout == 'top_small':
        ctx.set_source_rgb(*ink_top)
        ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(15)
        show_spaced(ctx, (subtitle or '').upper(), 36, 54, 2.2)
        ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(19)
        ctx.move_to(36, 80)
        ctx.show_text(title)
    elif layout == 'top_centre':
        ctx.set_source_rgb(*ink_top)
        ctx.select_font_face('Serif', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        name = (subtitle or title).upper()
        size = 30
        ctx.set_font_size(size)
        while size > 14 and spaced_width(ctx, name, 3) > 440:
            size -= 2
            ctx.set_font_size(size)
        show_spaced(ctx, name, 256 - spaced_width(ctx, name, 3) / 2, 66, 3)
    elif layout == 'bottom_serif':
        ctx.set_source_rgb(*ink_bottom)
        ctx.select_font_face('Serif', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_NORMAL)
        lines = wrap_text(ctx, title, 420, 34)[:2]
        for number, line in enumerate(lines):
            ctx.move_to(36, 470 - (len(lines) - 1 - number) * 38)
            ctx.show_text(line)


def draw_cover(out_path, title, subtitle, badge, palette, motif, is_artist=False,
               size=config.COVER_SIZE, wide=False):
    """Draw a size x size square artwork with Cairo and save as JPEG via GdkPixbuf.
    The drawing is laid out on a 512-unit square and scaled to `size`: the `motif`'s picture
    (MOTIFS) in the palette's colours, maybe words (draw_words; `badge` says what kind of
    thing it is, and is not drawn), and film grain over it all. Its random choices are
    seeded by its words, so a cover is the same every time. `is_artist` draws an artist's
    portrait instead; `wide` a music video's 16:9 frame (size wide, the middle 512 x 288 band
    of the square picture, no words), as a still from the video."""
    dark, mid, light = (hex_to_rgb(colour) for colour in palette)
    rnd = random.Random(hashlib.sha1(f'{title}|{subtitle}|{motif}|{is_artist}'.encode()).digest())

    width, height = (size, round(size * 9 / 16)) if wide else (size, size)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surf)
    ctx.scale(size / 512, size / 512)
    if wide:
        ctx.translate(0, -112)

    if is_artist:
        draw_portrait(ctx, rnd, dark, mid, light,
                      3 if title.startswith('The ') or ' & ' in title else 1)
    elif motif == 'swiss' and not wide:
        motif_swiss(ctx, rnd, dark, mid, light, title, subtitle)
    else:
        inks = MOTIF_DRAW.get(motif, motif_contours)(ctx, rnd, dark, mid, light)
        if not wide:
            draw_words(ctx, rnd, title, subtitle, badge, inks)

    ctx.identity_matrix()
    ctx.set_operator(cairo.OPERATOR_OVERLAY)
    ctx.set_source(grain_pattern())
    ctx.paint_with_alpha(0.16)

    save_jpeg(surf, width, height, out_path)


def save_jpeg(surf, width, height, out_path):
    """Save an opaque cairo ARGB32 surface as a JPEG via GdkPixbuf, straight from its pixels
    rather than through a PNG (which was most of a build's time). The picture is opaque, so
    premultiplied or not is all one; cairo keeps it as native-endian 32-bit xRGB words, a
    stride of exactly width * 4, and GdkPixbuf wants R, G, B bytes."""
    surf.flush()
    xrgb = bytes(surf.get_data())
    red, green, blue = (2, 1, 0) if sys.byteorder == 'little' else (1, 2, 3)
    rgb = bytearray(width * height * 3)
    rgb[0::3] = xrgb[red::4]
    rgb[1::3] = xrgb[green::4]
    rgb[2::3] = xrgb[blue::4]
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(bytes(rgb)), GdkPixbuf.Colorspace.RGB, False, 8, width, height, width * 3)
    pixbuf.savev(out_path, 'jpeg', ['quality'], ['85'])


# An invented artist banner's size: the 3:1 shape the app asks Apple's wide cut at
# (remote.BANNER_ASPECT), as wide as a large window's header at a scale of 1.
BANNER_SIZE = (1920, 640)


def draw_banner(out_path, palette, figures=1, seed=0, size=BANNER_SIZE):
    """Draw an invented artist banner, as Apple's wide cut of an artist's photograph is: on a
    stage-lit field in the palette's colours, `figures` head-and-shoulders silhouettes right
    of the middle, the lower left kept plain where the page puts the name. Laid out on a
    1536 x 512 canvas scaled to `size`; saved as a JPEG."""
    dark_rgb, mid_rgb, light_rgb = (hex_to_rgb(colour) for colour in palette)
    width, height = size
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surf)
    ctx.scale(width / 1536, height / 512)
    rnd = random.Random(seed)

    field = cairo.LinearGradient(0, 0, 1536, 512)
    field.add_color_stop_rgb(0.0, *dark_rgb)
    field.add_color_stop_rgb(0.6, *mid_rgb)
    field.add_color_stop_rgb(1.0, *dark_rgb)
    ctx.set_source(field)
    ctx.paint()

    # Stage lights from above, fanning out.
    for x in (420, 900, 1300):
        ray = cairo.LinearGradient(x, 0, x, 512)
        ray.add_color_stop_rgba(0.0, *light_rgb, 0.35)
        ray.add_color_stop_rgba(1.0, *light_rgb, 0.0)
        ctx.move_to(x - 24, 0)
        ctx.line_to(x + 24, 0)
        ctx.line_to(x + 230, 512)
        ctx.line_to(x - 230, 512)
        ctx.close_path()
        ctx.set_source(ray)
        ctx.fill()

    # A glow behind the figures, and dust in the light.
    glow = cairo.RadialGradient(1000, 240, 20, 1000, 240, 420)
    glow.add_color_stop_rgba(0.0, *light_rgb, 0.5)
    glow.add_color_stop_rgba(1.0, *light_rgb, 0.0)
    ctx.set_source(glow)
    ctx.paint()
    for _speck in range(90):
        ctx.arc(rnd.uniform(500, 1536), rnd.uniform(0, 420), rnd.uniform(1, 3.5), 0,
                2 * math.pi)
        ctx.set_source_rgba(*light_rgb, rnd.uniform(0.2, 0.6))
        ctx.fill()

    # The figures, the first the tallest, in the middle of the light.
    for number in range(figures):
        x = 1000 + (number - (figures - 1) / 2) * 190
        scale = 1.0 if number == (figures - 1) // 2 else 0.85
        ctx.save()
        ctx.translate(x, 512)
        ctx.scale(scale, scale)
        ctx.set_source_rgb(*dark_rgb)
        ctx.arc(0, -262, 66, 0, 2 * math.pi)
        ctx.fill()
        ctx.arc(0, 40, 200, math.pi, 2 * math.pi)
        ctx.fill()
        ctx.restore()

    save_jpeg(surf, width, height, out_path)


# ---------------------------------------------------------------------------
# Data definitions: Artists, Albums, Playlists, Radio Stations
# ---------------------------------------------------------------------------

ARTISTS_DATA = [
    {
        'name': 'Midnight Archipelago',
        'genre': 'Post-Rock',
        'bio': ('An instrumental post-rock collective exploring expansive dynamic shifts, '
                'tape-looped guitars, and oceanic textures.'),
    },
    {
        'name': 'Solaris Circuit',
        'genre': 'Synthwave',
        'bio': ('Blends analog polyphonic synthesizers with driving drum machine patterns, '
                'evoking neon-lit metropolitan nights.'),
    },
    {
        'name': 'Mara Lind & The Tide',
        'genre': 'Indie Folk',
        'bio': ('Weaves fingerpicked acoustic guitars, upright bass, and intimate vocal harmonies '
                'into evocative coastal landscapes.'),
    },
    {
        'name': 'Komorebi Quartet',
        'genre': 'Modern Classical',
        'bio': ('Combines prepared piano, cello, viola, and delicate field recordings, creating '
                'contemplative spaces exploring natural light.'),
    },
    {
        'name': 'Neon Boulevard',
        'genre': 'Dream Pop',
        'bio': ('Crafts lush, shimmering dream pop and synthpop with reverb-drenched guitars, '
                'sparkling arpeggios, and melancholic melodies.'),
    },
    {
        'name': 'Echoes of Orion',
        'genre': 'Ambient',
        'bio': ('Produces deep, immersive space ambient music utilizing modular synthesizer '
                'drones and resonant acoustic filters.'),
    },
    {
        'name': 'Velvet Horizon',
        'genre': 'Neo-Soul',
        'bio': ('Marries warm Rhodes electric pianos, silky vocal arrangements, and unhurried '
                'hip-hop-influenced grooves.'),
    },
    {
        'name': 'Dust & Radiance',
        'genre': 'Shoegaze',
        'bio': ('Creates dense walls of fuzzy distortion and soaring guitar glissandos, anchored '
                'by propulsive rhythm sections.'),
    },
    {
        'name': 'Sora Takahashi',
        'genre': 'Nu-Jazz',
        'bio': ('Tokyo-based keyboardist bridging modal acoustic jazz, complex syncopations, and '
                'modern UK broken beat production.'),
    },
    {
        'name': 'The Glass Observatory',
        'genre': 'Cinematic',
        'bio': ('Crafts grand, emotional cinematic narratives combining sweeping orchestral '
                'strings and subtle electronic undercurrents.'),
    },
    {
        'name': 'Cassette Memories',
        'genre': 'Lo-Fi Hip-Hop',
        'bio': ('Crafts nostalgic instrumental lo-fi beats saturated with warm vinyl crackle, '
                'dust-laden samples, and relaxed drums.'),
    },
    {
        'name': 'Aura & Frequency',
        'genre': 'Deep House',
        'bio': ('Explores the intersections of hypnotic deep house, rolling basslines, and '
                'melodic techno for peak-time dance floors.'),
    },
    {
        'name': 'Hollyhock Avenue',
        'genre': 'Indie Pop',
        'bio': ('Celebrated for upbeat jangly guitars, brass accents, lyrical wit, and '
                'irresistible infectious hooks.'),
    },
    {
        'name': 'Paper Parachutes',
        'genre': 'Math Rock',
        'bio': ('Pairs intricate finger-tapping guitar work and interlocking odd-time polyrhythms '
                'with passionate, soaring choruses.'),
    },
    {
        'name': 'Subterranean Brass',
        'genre': 'Funk & Jazz',
        'bio': ('A high-octane 8-piece brass powerhouse fusing New Orleans street grooves, hard '
                'bop phrasing, and heavy funk backbeats.'),
    },
]

ALBUMS_DATA = [
    # 1. Midnight Archipelago (3 albums)
    {
        'artist_idx': 0,
        'title': 'Signal from the Shallows',
        'year': 2018,
        'genre': 'Post-Rock',
        'summary': ('An atmospheric exploration of maritime isolation, anchored by reverberant '
                    'guitars and swelling cymbal washes.'),
        'discs': [
            [
                'Low Tide Warning', 'Beacon in the Fog', 'Submerged Currents',
                'Breakwater Echo', 'Distant Shoals', 'Tidal Drift',
                'The Shallows Wake', 'Anchor Line', 'Salt & Timber', 'Returning Tide',
            ],
        ],
    },
    {
        'artist_idx': 0,
        'title': 'Islands in Suspension',
        'year': 2021,
        'genre': 'Post-Rock',
        'summary': ('Expansive arrangements tracing the contours of remote archipelagos with '
                    'soaring crescendos and delicate acoustic interludes.'),
        'discs': [
            [
                'Archipelago Sunrise', 'Windward Passage', 'Suspension Bridge',
                'Isle of Glass', 'Mist Over Cape Hope', 'Granite Coast',
                "Seafarer's Compass", 'Quiet Estuary', 'Echoes on the Water',
                'Cove of Lanterns', 'Midnight Horizon', 'Drifting Home',
            ],
        ],
    },
    {
        'artist_idx': 0,
        'title': 'Cartography of Fog',
        'year': 2024,
        'genre': 'Post-Rock',
        'summary': ('A sweeping double-album journey across uncharted coastal sounds, moving from '
                    'meditative drones to thundering sonic squalls.'),
        'discs': [
            [
                "The Mapmaker's Ledger", 'Charted Coastline', 'Northbound Swell',
                'Lost Coordinates', 'Dense Maritime Air', 'Shoal Marker',
                'Sounding the Depth', 'First Anchorage',
            ],
            [
                'The Western Reach', 'Ghost Ship Relay', 'Barometer Falling',
                'Lighthouse Beam', 'Reef Navigation', 'Storm Petrels',
                'Compass Variation', 'Safe Harbor Lights',
            ],
        ],
    },

    # 2. Solaris Circuit (3 albums)
    {
        'artist_idx': 1,
        'title': 'Neon Velocity',
        'year': 2019,
        'genre': 'Synthwave',
        'summary': ('A nocturnal celebration of analog synthesizers, gated reverbs, and '
                    'high-speed highway escapades.'),
        'discs': [
            [
                'Ignition Sequence', 'Overdrive City', 'Chrome Highway',
                'Midnight Pursuit', 'Turbocharger', 'Gridlock Romance',
                'Analog Boulevard', 'Redline Horizon', 'Nightfall Accelerant',
                'Synthetic Pulse', 'Dawn Run',
            ],
        ],
    },
    {
        'artist_idx': 1,
        'title': 'Transmission Zero',
        'year': 2022,
        'genre': 'Synthwave',
        'summary': ('Dark cyberpunk motifs collide with cinematic arpeggios in a conceptual '
                    'narrative of underground radio dissidents.'),
        'discs': [
            [
                'Frequency Lock', 'Cybernetic Heart', 'Signal Decode',
                'Sublevel Terminal', 'Fiber Optic Sky', 'Rogue Satellite',
                'Quantum Static', 'Packet Rain', 'Baud Rate 9600', 'Carrier Lost',
            ],
        ],
    },
    {
        'artist_idx': 1,
        'title': 'Suborbital Drift',
        'year': 2025,
        'genre': 'Electronic',
        'summary': ('Weightless electronic rhythms and modular sequences inspired by low-Earth '
                    'orbit observations.'),
        'discs': [
            [
                'Atmosphere Exit', 'Zero G Velocity', 'Ion Engines',
                'Orbital Decay', 'Sunward Drift', 'Apogee Burn',
                'Silent Thrusters', 'Dark Side Transit', 'Atmospheric Re-entry',
            ],
        ],
    },

    # 3. Mara Lind & The Tide (3 albums)
    {
        'artist_idx': 2,
        'title': 'Saltwater Hymns',
        'year': 2017,
        'genre': 'Indie Folk',
        'summary': ('Intimate fingerpicked acoustic ballads recorded in an empty wooden chapel by '
                    'the ocean.'),
        'discs': [
            [
                'Morning on the Pier', 'Tidepool Reflections', 'Dune Grass',
                "Fisherman's Daughter", 'Copper Kettle', 'Salt Air',
                'Woodsmoke & Sea', 'The Old Dinghy', 'Driftwood Fire', 'Lullaby for High Seas',
            ],
        ],
    },
    {
        'artist_idx': 2,
        'title': 'Canyon Fireflies',
        'year': 2020,
        'genre': 'Indie Folk',
        'summary': ('Earthy harmonies and porch-side storytelling capturing summer twilights in '
                    'the high desert.'),
        'discs': [
            [
                'Red Rock Valley', 'Firefly Glow', 'Dust on the Windshield',
                'Canyon Wall Whispers', 'Pinecone Lanterns', 'Riverbend Song',
                'Porch Swing Melody', 'Twilight Crickets', 'Hitching Post',
                'Cedar Smoke', 'Sleep Beneath the Stars',
            ],
        ],
    },
    {
        'artist_idx': 2,
        'title': 'The Northern Harbor',
        'year': 2023,
        'genre': 'Indie Folk',
        'summary': ('Rich chamber-folk arrangements with upright bass, fiddle, and poetic lyrics '
                    'of homecoming.'),
        'discs': [
            [
                'Harbor Bells', 'Ferry Crossing', 'Woolen Sweaters',
                'Gull Wing Flight', 'November Mist', 'Cobblestone Street',
                'Anchored in the Bay', 'Teahouse Window', 'Rowboat Solitude',
                'Cold Current', 'Winter Wharf', 'Homeward Voyage',
            ],
        ],
    },

    # 4. Komorebi Quartet (3 albums)
    {
        'artist_idx': 3,
        'title': 'Leaves in Still Water',
        'year': 2016,
        'genre': 'Modern Classical',
        'summary': ('Gentle prepared piano and string motifs mirroring the calm ripples of autumn '
                    'ponds.'),
        'discs': [
            [
                'First Ripple', 'Canopy Sunlight', 'Fallen Maple',
                'Silent Pond', 'Moss Garden', 'Raindrop Cadence',
                'Autumn Reverie', 'Bamboo Shadows', 'Evening Stillness',
            ],
        ],
    },
    {
        'artist_idx': 3,
        'title': 'Architecture of Silence',
        'year': 2021,
        'genre': 'Modern Classical',
        'summary': ('A profound two-part meditation recorded inside historic cathedral cloisters, '
                    'pairing resonance with deep pause.'),
        'discs': [
            [
                'Foundation Stone', 'The Empty Corridor', 'Arches of Dust',
                'Resonant Room', 'Vaulted Ceiling', 'Shaft of Light', 'Courtyard Rain',
            ],
            [
                'Pillar Shadows', 'Stairway in Marble', 'Acoustic Reflection',
                'The Cloister', 'Stone Bench', 'Belfry Breeze',
                'Quiet Nave', 'Final Echo',
            ],
        ],
    },
    {
        'artist_idx': 3,
        'title': 'Winter Light Studies',
        'year': 2024,
        'genre': 'Modern Classical',
        'summary': ('Sparse cello and viola duets capturing the fragile crystalline stillness of '
                    'northern winters.'),
        'discs': [
            [
                'Frost on Cedar', 'Pale Sunlight', 'Frozen Lake Etude',
                'Icicle Harmonics', 'Snowfall Nocturne', 'Winter Solstice',
                'Breath in Cold Air', 'Glacial Purity', 'Thawing Stream', 'Early Spring Whisper',
            ],
        ],
    },

    # 5. Neon Boulevard (3 albums)
    {
        'artist_idx': 4,
        'title': 'Midnight Cassette Club',
        'year': 2018,
        'genre': 'Dream Pop',
        'summary': ('Wistful dream-pop shimmering with vintage chorus pedals, tape flutter, and '
                    'romantic nostalgia.'),
        'discs': [
            [
                'Side A Track 1', 'Roller Disco', "Sunset Boulevard '88",
                'Starlight Diner', 'Lipstick Mirror', 'Prom Night Regrets',
                'Pastel Convertible', 'Tape Rewind', 'Neon Palms',
                'Late Call', 'Fade to Sunrise',
            ],
        ],
    },
    {
        'artist_idx': 4,
        'title': 'Electric Reverie',
        'year': 2021,
        'genre': 'Synthpop',
        'summary': ('Energetic hooks and sparkling synth arpeggios designed for midnight drives '
                    'and neon skylines.'),
        'discs': [
            [
                'Dream Sequence', 'Laser Waltz', 'Prism Glow',
                'Memory Card', 'Velvet Highway', 'Synthesizer Heartbeat',
                'Heat Shimmer', 'Cobalt Static', 'Kiss at the Crossing', 'Reverie Outro',
            ],
        ],
    },
    {
        'artist_idx': 4,
        'title': 'After Hours Echo',
        'year': 2024,
        'genre': 'Synthpop',
        'summary': ('Reflective downtempo synthpop capturing the quiet intimacy of empty city '
                    'streets at 3 AM.'),
        'discs': [
            [
                'City Lights Blurring', 'Last Call at the Lounge', 'Rainy Asphalt',
                'Subway Tile Reflection', 'Taxi Ride Reverie', 'Neon Umbrella',
                'Nightjar', '2 AM Espresso', 'Empty Dancefloor',
                'Corner Booth', 'Distant Sirens', 'Dawn Breaking Over Rooftops',
            ],
        ],
    },

    # 6. Echoes of Orion (3 albums)
    {
        'artist_idx': 5,
        'title': 'Stellar Cartography',
        'year': 2015,
        'genre': 'Ambient',
        'summary': ('Expansive analog drone compositions mapping distant celestial landmarks and '
                    'quiet cosmic voids.'),
        'discs': [
            [
                'Columns of Dust', 'Horsehead Nebula', 'Lagrange Point 2',
                'Oort Cloud Passage', 'Kuiper Belt Drift', 'Cassini Gap',
                'Andromeda Approaching', 'Cosmic Horizon',
            ],
        ],
    },
    {
        'artist_idx': 5,
        'title': 'Voyager Suite',
        'year': 2019,
        'genre': 'Ambient',
        'summary': ('A grand conceptual double album tracing the solitary trajectory of robotic '
                    'explorers beyond our solar system.'),
        'discs': [
            [
                'Golden Record Intro', 'Jupiter Flyby', 'Great Red Spot',
                'Radiation Belts', 'Rings of Saturn', 'Enceladus Geysers',
                "Titan's Atmosphere", 'Heliosphere Boundary',
            ],
            [
                'Interstellar Medium', 'Faint Blue Speck', 'Signal Lag 19 Hours',
                'Dark Void Transit', 'Radioisotope Glow', 'Cosmic Dust Impacts',
                'Deep Space Antenna', 'Wandering the Galaxy', 'Infinite Silence',
            ],
        ],
    },
    {
        'artist_idx': 5,
        'title': 'Deep Cosmic Field',
        'year': 2023,
        'genre': 'Ambient',
        'summary': ('Sub-bass frequencies and slow-evolving harmonic filters evocative of cosmic '
                    'background radiation.'),
        'discs': [
            [
                'Vacuum Energy', 'Edge of the Well', 'Singularity Pulse',
                'Gravitational Wave', 'Supercluster Web', 'Dark Matter Halo',
                'Cosmic Microwave Glow', 'Pulsar Beacon', 'Eternal Expansion',
            ],
        ],
    },

    # 7. Velvet Horizon (3 albums)
    {
        'artist_idx': 6,
        'title': 'Golden Hour Vibrations',
        'year': 2020,
        'genre': 'Neo-Soul',
        'summary': ('Warm Rhodes progressions, buttery vocal arrangements, and laid-back grooves '
                    'for sunset unwinding.'),
        'discs': [
            [
                'Honey Amber', 'Warm Breeze', 'Rooftop Sundown',
                'Smooth as Sunday', 'Silk Sheets', 'Golden Hour Glow',
                'Chai Tea & Chords', 'Unspoken Rhythm', 'Lazy Sunday Grooves',
                'Amber Skies', 'Dusk Embrace',
            ],
        ],
    },
    {
        'artist_idx': 6,
        'title': 'Jasmine After Eleven',
        'year': 2022,
        'genre': 'Neo-Soul',
        'summary': ('Sensual nighttime R&B and jazz-infused chord work detailing romance and city '
                    'nightlife.'),
        'discs': [
            [
                'Night Jasmine', 'Velvet Petals', 'Moonlit Patio',
                'Low Key Loving', 'Dim Lights & Wine', 'Late Night Text',
                'Heart on a Wire', 'Jasmine After Eleven', 'Ember, Slowly',
                'Soulful Cadence', 'Velvet Silhouette', 'After the Lamps Go Out',
            ],
        ],
    },
    {
        'artist_idx': 6,
        'title': 'Velvet Sessions Vol. 1',
        'year': 2025,
        'genre': 'Neo-Soul',
        'summary': ('Live-in-studio jams highlighting improvisational chemistry and unhurried '
                    'acoustic warmth.'),
        'discs': [
            [
                'Session Prelude', 'Rhodes in F Minor', 'Pocket Groove',
                'Muted Trumpet Soul', 'Bassline Serenade', 'Finger Snaps',
                'Vinyl Interlude', 'Vintage Warmth', 'Late Jam', 'Outro Toast',
            ],
        ],
    },

    # 8. Dust & Radiance (3 albums)
    {
        'artist_idx': 7,
        'title': 'Tremolo Summer',
        'year': 2017,
        'genre': 'Shoegaze',
        'summary': ('Glissando guitar washes, dizzying whammy bar vibrato, and buried vocals in a '
                    'haze of summer feedback.'),
        'discs': [
            [
                'Feedback Loop', 'Sun Drenched Fuzz', 'Tremolo Waves',
                'Blinding Glare', 'Reverb Haze', 'Silver Lake Walk',
                'Distortion Kiss', 'Pedalboard Dreams', "Summer's End Swell",
                'Overdrive Twilight',
            ],
        ],
    },
    {
        'artist_idx': 7,
        'title': 'Feedback Cathedral',
        'year': 2020,
        'genre': 'Shoegaze',
        'summary': ('Towering walls of sonic fuzz and harmonic resonance creating an overwhelming '
                    'yet sacred sonic sanctuary.'),
        'discs': [
            [
                'Nave of Noise', 'Echo Vestry', 'Stained Glass Shards',
                'Vault of Reverb', 'Sustained Note', 'Altar of Amps',
                'Sonic Sacrament', 'Cathedral Bells', 'Fuzz Choir',
                'Harmonic Resonator', 'Upward Nave',
            ],
        ],
    },
    {
        'artist_idx': 7,
        'title': 'Distortion in Bloom',
        'year': 2023,
        'genre': 'Shoegaze',
        'summary': ('A massive two-disc shoegaze opus tracing fragile acoustic melodies as they '
                    'disintegrate into euphoric distortion.'),
        'discs': [
            [
                'First Petal Feedback', 'Overdriven Stem', 'Wall of Sound Blossom',
                'Swirling Chorus', 'Decay Rate', 'Fuzz Meadow',
                'Grounded Wire', 'Static Garden', 'Greenhouse Drone',
            ],
            [
                'Noon Sun Glare', 'Tape Saturation', 'Reverb Spores',
                'Electric Vine', 'Wild Thistle Distortion', 'Blown Speaker Bloom',
                'Dusk Petal', 'Night-Blooming Jasmine Fuzz', 'Root System',
            ],
        ],
    },

    # 9. Sora Takahashi (3 albums)
    {
        'artist_idx': 8,
        'title': 'Tokyo Rain Reflections',
        'year': 2019,
        'genre': 'Nu-Jazz',
        'summary': ("Fluid piano lines and brushed syncopations capturing rainy evenings under "
                    "Shinjuku's neon signs."),
        'discs': [
            [
                'Shinjuku Crosswalk', 'Umbrella Drops', 'Neon in Puddles',
                'Yamanote Line Groove', 'Underpass Improvisation', 'Midnight Ramen Blues',
                'Alleyway Lanterns', 'Rainy Windowpane', 'Electric Piano Mist',
                'Last Train at Midnight',
            ],
        ],
    },
    {
        'artist_idx': 8,
        'title': 'Modal Drift',
        'year': 2022,
        'genre': 'Nu-Jazz',
        'summary': ('Complex modal jazz harmonies interwoven with lively broken-beat drumming and '
                    'upright bass flourishes.'),
        'discs': [
            [
                'Dorian Awakening', 'Pentatonic Cloud', 'Syncopated Pulse',
                'Rhodes Drift', 'Bass Solo in E', 'Brushed Snare',
                'Polytonal Glide', 'Fourth Interval', 'Floating Measure',
                'Modal Shift', 'Coda Reflections',
            ],
        ],
    },
    {
        'artist_idx': 8,
        'title': 'Syncopation City',
        'year': 2025,
        'genre': 'Nu-Jazz',
        'summary': ('A vibrant celebration of urban kinetic energy, shifting time signatures, and '
                    'sparkling Rhodes solos.'),
        'discs': [
            [
                'Rush Hour 8 AM', 'Cross-Rhythm Station', 'Broken Beat Espresso',
                'Hi-Hat Shuffle', 'Subway Echoes', '7/8 On the Expressway',
                'Pedestrian Syncopation', 'Rooftop Jam', 'Offbeat Romance',
                'Groove Laboratory', 'City Never Stops', 'Night Transit',
            ],
        ],
    },

    # 10. The Glass Observatory (3 albums)
    {
        'artist_idx': 9,
        'title': 'Constellation Hours',
        'year': 2018,
        'genre': 'Cinematic',
        'summary': ('Orchestral strings and brass motifs evoking brass astrolabes and historic '
                    'hilltop stargazing domes.'),
        'discs': [
            [
                'Lens Calibration', 'Amber Skies', 'Telescopic Sweep',
                'The Dome Opens', 'Brass Gears', 'Focal Plane',
                'Starlight Preserved', 'Spectral Lines', 'Dawn Shutter',
            ],
        ],
    },
    {
        'artist_idx': 9,
        'title': 'The Permafrost Echo',
        'year': 2022,
        'genre': 'Cinematic',
        'summary': ('A chilling double-disc soundtrack for Arctic expeditions, balancing sub-zero '
                    'strings with thundering percussion.'),
        'discs': [
            [
                'Tundra Expedition', 'Ice Core Samples', 'Glacial Moraine',
                'The Frozen Valley', 'Blizzard Approaches', 'Aurora Borealis Choir',
                'Sub-Zero Pressure', 'First Thaw',
            ],
            [
                'Deep Crevasse', 'The Singing Ice', 'Frozen Compass',
                'Glacier Tongue', 'Mammoth Bones', 'Arctic Midnight Sun',
                'Permafrost Memory', 'Echoing Fjord',
            ],
        ],
    },
    {
        'artist_idx': 9,
        'title': 'Mirrors and Meteors',
        'year': 2025,
        'genre': 'Cinematic',
        'summary': ('Dynamic brass swells and pulsing electronics inspired by meteor showers and '
                    'optical astronomy.'),
        'discs': [
            [
                'Parabolic Mirror', 'Shooting Star Trace', 'Atmospheric Entry',
                'Meteor Shower Suite', 'Silver Coating', 'Night Sky Panorama',
                'Gravity Lens', 'Impact Crater Echo', 'Reflecting Pool',
                'Orbital Sweep',
            ],
        ],
    },

    # 11. Cassette Memories (2 albums)
    {
        'artist_idx': 10,
        'title': 'Warm Tape Hiss',
        'year': 2020,
        'genre': 'Lo-Fi Hip-Hop',
        'summary': ('Cozy beats saturated with vinyl crackle, dust-laden piano loops, and gentle '
                    'rainy day vibes.'),
        'discs': [
            [
                'Coffee Grinder Intro', 'Morning Sunlight', 'Vintage Vinyl Flip',
                'Rainy Day Study', 'Muffled Snare', 'Dusty Keys',
                'Tape Head Cleaning', 'Porch Stoop Beats', 'Subtle Headnod',
                'Cat on the Amplifier', 'Bonsai Tree', 'Midnight Chillout',
                'Crayon Drawings', 'Goodnight Tape',
            ],
        ],
    },
    {
        'artist_idx': 10,
        'title': 'Late Night Porch Sessions',
        'year': 2023,
        'genre': 'Lo-Fi Hip-Hop',
        'summary': ('Relaxed porch-side beatcraft weaving acoustic guitar licks with cricket '
                    'ambiance and gentle kicks.'),
        'discs': [
            [
                'Screen Door Slam', 'Crickets in Stereo', 'Gentle Strum',
                'Neighborhood Lamp', 'Cold Lemonade', 'Firefly Beat',
                'Vinyl Crackle Breeze', 'Faded Photograph', 'Late Summer Thoughts',
                'Distant Trains', 'Muted Horn', 'Twilight Chords', 'Moon Over the Yard',
            ],
        ],
    },

    # 12. Aura & Frequency (2 albums)
    {
        'artist_idx': 11,
        'title': 'Underground Reverberation',
        'year': 2019,
        'genre': 'Deep House',
        'summary': ('Hypnotic rolling basslines and warm dub chords crafted for intimate basement '
                    'sound systems.'),
        'discs': [
            [
                'Basement Entrance', 'Sub-Bass Pressure', '4 AM Warehouse',
                'Strobe Sequence', 'Hypnotic Loop', 'Filter Sweep',
                'Deep Resonance', 'Modular Acid', 'Peak Time', 'Tunnel Echo',
            ],
        ],
    },
    {
        'artist_idx': 11,
        'title': 'Resonance Chamber',
        'year': 2023,
        'genre': 'Melodic Techno',
        'summary': ('A two-disc exploration of cavernous industrial reverbs, driving kicks, and '
                    'ascending synth leads.'),
        'discs': [
            [
                'Chamber Acoustics', 'Kicking Low', 'Analog Hi-Hats',
                'Dark Matter Groove', 'Sonic Oscillation', 'Subterranean Sweep',
                'Pulse Modulation', 'Reverb Tail',
            ],
            [
                'Second Chamber', 'Echo Velocity', 'Industrial Percussion',
                'Hypnotic State', 'Midnight Frequency', 'Sine Wave Meditation',
                'Driving Rhythm', 'Dawn Release',
            ],
        ],
    },

    # 13. Hollyhock Avenue (2 albums)
    {
        'artist_idx': 12,
        'title': 'Wildflower Gazette',
        'year': 2021,
        'genre': 'Indie Pop',
        'summary': ('Jangly acoustic guitars, whimsical lyricism, and chamber strings celebrating '
                    'springtime adventures.'),
        'discs': [
            [
                'Morning Gazette', 'Dandelion Clock', 'Bicycle Bell Song',
                'Picnic in the Park', 'Penny Loafers', 'Botanical Garden Waltz',
                'Lemon Drop Sun', 'Paper Glider', 'Cottage Garden',
                'Chamber Strings', 'Sunday Stroll',
            ],
        ],
    },
    {
        'artist_idx': 12,
        'title': 'Paper Lantern Waltz',
        'year': 2024,
        'genre': 'Indie Pop',
        'summary': ('Delicate melodies and brass touches evoking evening lanterns swaying along '
                    'garden paths.'),
        'discs': [
            [
                'Festival Eve', 'Paper Lantern Glow', 'String of Lights',
                'Carousel Melody', 'Night Market Waltz', 'Origami Boat',
                'Moonlit Pathway', 'Gentle Clarinet', 'Last Lantern', 'Sleepy Town',
            ],
        ],
    },

    # 14. Paper Parachutes (2 albums)
    {
        'artist_idx': 13,
        'title': 'Odd Time Signatures',
        'year': 2019,
        'genre': 'Math Rock',
        'summary': ('Intricate finger-tapping patterns in 7/8 and 5/4 anchored by passionate '
                    'vocal melodies.'),
        'discs': [
            [
                'Count in 7/4', 'Finger Tap Intro', 'Polyrhythm Cafe',
                'Twinkly Guitars', 'Angular Chords', 'Off-Grid Breakdown',
                'Syncopated Heart', 'Math Class Blues', 'Pedal Shuffle',
                '5/8 Resolution', 'Final Measure',
            ],
        ],
    },
    {
        'artist_idx': 13,
        'title': 'Kinetic Geometry',
        'year': 2023,
        'genre': 'Math Rock',
        'summary': ('Sharp rhythmic shifts, interlocking guitar loops, and explosive dynamic '
                    'releases.'),
        'discs': [
            [
                'Tesseract', 'Sharp Angles', 'Interlocking Rhythms',
                'Fractal Breakdown', 'Kinetic Motion', 'Triangulation',
                'Perpendicular Lines', 'Velocity Vector', 'Harmonic Symmetry', 'Zero Point',
            ],
        ],
    },

    # 15. Subterranean Brass (2 albums)
    {
        'artist_idx': 14,
        'title': 'Low Frequency Grooves',
        'year': 2020,
        'genre': 'Funk & Jazz',
        'summary': ('Sousaphone basslines and infectious New Orleans second-line drumming with '
                    'hard-hitting funk energy.'),
        'discs': [
            [
                'Sousaphone Strut', 'Trombone Shout', 'Funk in the Alley',
                'Second Line Beat', 'Heavy Horn Section', 'Groove Machine',
                'Low End Rumble', 'Street Parade', 'Brass Breakdown',
                'Fat Bass Groove', 'Encore Funk',
            ],
        ],
    },
    {
        'artist_idx': 14,
        'title': 'The Basement Collective',
        'year': 2024,
        'genre': 'Contemporary Jazz',
        'summary': ('Fiery brass solo trades and infectious syncopated backbeats captured in an '
                    'intimate basement jam session.'),
        'discs': [
            [
                'Basement Jam Prelude', 'Tenor Sax Battle', 'Syncopated Snare',
                'Hot Pepper Horns', 'Bourbon Street Stomp', 'Midnight Brass Session',
                'Funky Footsteps', 'Muted Trumpet Jam', 'Collective Improv',
                'Big Brass Energy', 'Last Call Groove', 'Walk Home Stomp',
            ],
        ],
    },
]

PLAYLISTS_DATA = [
    {
        'title': 'Late Night Drift',
        'subtitle': 'Harbourlight Chill',
        'genre': 'Downtempo',
        'summary': ('Low-tempo beats, atmospheric synths, and mellow melodies for late hours and '
                    'quiet contemplations.'),
        'filter_genres': ['Ambient', 'Lo-Fi Hip-Hop', 'Neo-Soul', 'Modern Classical'],
    },
    {
        'title': 'Analog Horizons',
        'subtitle': 'Harbourlight Electronic',
        'genre': 'Electronic',
        'summary': ('Warm analog synthesizer compositions, arpeggiated sequences, and vintage '
                    'drum machines.'),
        'filter_genres': ['Synthwave', 'Electronic', 'Deep House', 'Melodic Techno'],
    },
    {
        'title': 'Indie Currents',
        'subtitle': 'Harbourlight Indie',
        'genre': 'Alternative & Indie',
        'summary': ('The most compelling new sounds from independent bands, singer-songwriters, '
                    'and DIY studios.'),
        'filter_genres': ['Indie Folk', 'Indie Pop', 'Math Rock', 'Post-Rock'],
    },
    {
        'title': 'Still Hours',
        'subtitle': 'Harbourlight Ambient',
        'genre': 'Ambient',
        'summary': ('Uncluttered ambient soundscapes and subtle drones designed to foster '
                    'concentration and flow.'),
        'filter_genres': ['Ambient', 'Modern Classical'],
    },
    {
        'title': 'Modern Jazz Underground',
        'subtitle': 'Harbourlight Jazz',
        'genre': 'Jazz',
        'summary': ('Contemporary jazz explorations, complex rhythms, and forward-thinking '
                    'acoustic improvisations.'),
        'filter_genres': ['Nu-Jazz', 'Funk & Jazz', 'Contemporary Jazz'],
    },
    {
        'title': 'Sunset Drive',
        'subtitle': 'Curated by Robin Vale',
        'genre': 'Indie Pop',
        'summary': ('Golden hour indie anthems and euphoric hooks perfect for winding coastal '
                    'roads and open windows.'),
        'filter_genres': ['Dream Pop', 'Indie Pop', 'Indie Folk', 'Synthpop'],
    },
    {
        'title': 'Neon Expressway',
        'subtitle': 'Harbourlight Synthwave',
        'genre': 'Synthwave',
        'summary': ('High-octane synthwave, retro electro, and driving basslines for night '
                    'driving under streetlights.'),
        'filter_genres': ['Synthwave', 'Synthpop', 'Electronic'],
    },
    {
        'title': 'Golden Hour Melodies',
        'subtitle': 'Harbourlight Acoustic',
        'genre': 'Acoustic & Folk',
        'summary': ('Warm fingerstyle acoustics, gentle cello lines, and heartfelt vocal '
                    'performances.'),
        'filter_genres': ['Indie Folk', 'Modern Classical', 'Neo-Soul'],
    },
    {
        'title': 'Subterranean Bass',
        'subtitle': 'Harbourlight Club',
        'genre': 'Deep House',
        'summary': ('Deep, rolling grooves and hypnotic club rhythms from subterranean '
                    'underground dancefloors.'),
        'filter_genres': ['Deep House', 'Melodic Techno', 'Electronic'],
    },
    {
        'title': 'Quiet Reflections',
        'subtitle': 'Harbourlight Classical',
        'genre': 'Modern Classical',
        'summary': ('Gentle piano studies, minimalist string quartets, and contemplative '
                    'neo-classical works.'),
        'filter_genres': ['Modern Classical', 'Ambient', 'Cinematic'],
    },
    {
        'title': 'Soul & Reverie',
        'subtitle': 'Harbourlight R&B',
        'genre': 'Neo-Soul',
        'summary': ('Lush chord progressions, velvet vocals, and head-nodding neo-soul grooves '
                    'for relaxed evenings.'),
        'filter_genres': ['Neo-Soul', 'Lo-Fi Hip-Hop', 'Nu-Jazz'],
    },
    {
        'title': 'Heavy Shoegaze & Echoes',
        'subtitle': 'Curated by Ellis Marsh',
        'genre': 'Shoegaze',
        'summary': ('Swirling fuzz pedals, feedback-drenched melodies, and ethereal '
                    'reverberations that envelop the senses.'),
        'filter_genres': ['Shoegaze', 'Post-Rock', 'Math Rock'],
    },
]

# The Favourite Songs playlist, the songs the listener loves. Apple keeps it as an ordinary
# library playlist with a flag of its own; here the flag is attributes.isFavourites
# (applemusic.library.FAVOURITES), which the app's sync maps Apple's onto. No genre or year, as
# Apple's has none.
FAVOURITES_DATA = {
    'title': 'Favourite Songs',
    'subtitle': '',  # a library playlist: no curator
    'summary': 'The songs you love, newest first.',
    'size': 36,
}

# The playlist folders, as Apple's sidebar nests them: a folder's playlists are numbers into
# PLAYLISTS_DATA (1 is l.pl001), its folders are titles here. The playlists no folder holds,
# Favourite Songs among them, are at the top level. Each children list is in an order of its
# own, as Apple's API answers (the playlists, then the folders, in no order of title), and the
# app lists them as Apple Music's sidebar does: Favourite Songs, folders, playlists, by title.
FOLDERS_DATA = [
    {'title': 'Chill & Focus', 'folders': ['Jazz Nights'], 'playlists': [1, 4, 10]},
    {'title': 'Jazz Nights', 'folders': [], 'playlists': [5, 11]},
    {'title': 'On the Road', 'folders': [], 'playlists': [6, 7, 2]},
]

STATIONS_DATA = [
    {
        'title': 'Lighthouse One',
        'subtitle': 'Harbourlight Radio',
        'genre': 'Various',
        'summary': ('The pulse of music culture with daily live broadcasts, exclusive artist '
                    'interviews, and global premieres.'),
    },
    {
        'title': 'Evergreen Hits Radio',
        'subtitle': 'Harbourlight Radio',
        'genre': 'Pop & Rock',
        'summary': ("Celebrating the songs you know and love from the '80s, '90s, and 2000s with "
                    "passionate daily hosts."),
    },
    {
        'title': 'Slow Tide Radio',
        'subtitle': 'Harbourlight Radio',
        'genre': 'Downtempo & Ambient',
        'summary': ('An uninterrupted stream of relaxed beats, mellow melodies, and soothing '
                    'acoustic textures.'),
    },
    {
        'title': 'Echoes in the Dark',
        'subtitle': 'Harbourlight Radio',
        'genre': 'Electronic & Ambient',
        'summary': ('Atmospheric electronica, hypnotic modular synthesis, and dark ambient '
                    'soundscapes for nocturnal hours.'),
    },
    {
        'title': 'Pacific Highway Radio',
        'subtitle': 'Harbourlight Radio',
        'genre': 'Indie & Alternative',
        'summary': ('Carefree indie melodies, breezy dream pop, and road-trip classics broadcast '
                    'straight from the coast.'),
    },
    {
        'title': 'Soundstage Nine',
        'subtitle': 'Harbourlight Radio',
        'genre': 'Cinematic & Soundtracks',
        'summary': ('Sweeping orchestral film scores, modern classical compositions, and epic '
                    'cinematic themes.'),
    },
    {
        'title': 'Ambient Sleep Radio',
        'subtitle': 'Harbourlight Radio',
        'genre': 'Ambient',
        'summary': ('Gentle sonic textures, continuous pink noise, and calming generative drones '
                    'designed for deep sleep.'),
    },
    {
        'title': 'Global Rhythm Pulse',
        'subtitle': 'Harbourlight Radio',
        'genre': 'World & Nu-Jazz',
        'summary': ('Infectious polyrhythms, Afrobeat brass, Latin jazz grooves, and '
                    'cross-cultural beat experiments.'),
    },
]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

# Music videos, each by one of the hand-written artists (an index into ARTISTS_DATA).
VIDEOS_DATA = [
    {'title': 'Lanterns over the Shallows', 'artist_idx': 0, 'year': 2021},
    {'title': 'Night Drive to Nowhere', 'artist_idx': 1, 'year': 2022},
    {'title': 'Harbour Lights (Live at the Pier)', 'artist_idx': 2, 'year': 2023},
    {'title': 'Tissue-Paper Moons', 'artist_idx': 4, 'year': 2020},
    {'title': 'Slow Burn Sunday', 'artist_idx': 6, 'year': 2024},
    {'title': 'Tape Loop Afternoon', 'artist_idx': 10, 'year': 2025},
]


# The newest date added the demo has (its Recently Added shelf's first album), and how far
# back the rest go: a library built up over some years.
NEWEST_ADDED = 1790265600  # 2026-09-24T16:00:00Z
ADDED_SPAN = 7 * 365 * 24 * 3600


def added_text(seconds):
    """An invented `added`, as Apple writes a dateAdded: ISO 8601, to the second, UTC."""
    return datetime.fromtimestamp(seconds, UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def add_dates_and_favourites(albums, playlists, videos, newest_albums, favourite_tracks):
    """Give every album, playlist (Favourite Songs aside, which Apple makes) and music video an
    invented `added`, the Recently Added shelf's albums the newest in its order, and return
    library.json's `favourites`: the Favourite Songs playlist's songs (by catalog id, as the
    sync records them), one in twenty of the generated albums' songs, some albums, playlists
    and a video (library id and catalog id). Each from a random source of its own, after
    everything else is made, so nothing else changes."""
    rnd = random.Random(53)
    newest = {album['id']: position for position, album in enumerate(newest_albums)}
    for album in albums:
        if album['id'] in newest:
            album['added'] = added_text(NEWEST_ADDED - newest[album['id']] * 26 * 3600)
        else:
            album['added'] = added_text(NEWEST_ADDED - 30 * 24 * 3600
                                        - rnd.randrange(ADDED_SPAN))
    for item in playlists + videos:
        # Favourite Songs has none; the long playlist has its own, so that nothing else moves.
        if not (item.get('attributes') or {}).get('isFavourites') and 'added' not in item:
            item['added'] = added_text(NEWEST_ADDED - 20 * 24 * 3600 - rnd.randrange(ADDED_SPAN))

    def both(item):
        return [value for value in (item['id'], item.get('catalogId')) if value]

    picks = random.Random(59)
    songs = [track['catalogId'] or track['id'] for track in favourite_tracks]
    generated = albums[len(ALBUMS_DATA):]
    for album in generated:
        for group in album['groups']:
            for entry in group['entries']:
                if picks.random() < 0.05:
                    songs.append(entry['catalogId'] or entry['id'])
    hand_written = albums[:len(ALBUMS_DATA)]
    liked_albums = picks.sample(hand_written, min(6, len(hand_written)))
    liked_albums += [album for album in generated if picks.random() < 0.05]
    own = [item for item in playlists if not (item.get('attributes') or {}).get('isFavourites')]
    liked_playlists = picks.sample(own[:len(PLAYLISTS_DATA)], min(2, len(own)))
    liked_videos = videos[:1]
    return {
        'songs': list(dict.fromkeys(songs)),
        'albums': [value for album in liked_albums for value in both(album)],
        'playlists': [value for item in liked_playlists for value in both(item)],
        'videos': [value for item in liked_videos for value in both(item)],
    }


def build_folders(playlist_ids):
    """library.json's `folders` from FOLDERS_DATA: the "root" entry first, listing the top
    level, then each folder in FOLDERS_DATA's order. playlist_ids are the playlists' ids in
    section order; ids like l.fd001 are given in FOLDERS_DATA's order."""
    ids = {data['title']: f'l.fd{n:03d}' for n, data in enumerate(FOLDERS_DATA, 1)}
    parents = {child: ids[data['title']] for data in FOLDERS_DATA for child in data['folders']}
    folders = []
    held = set()
    for data in FOLDERS_DATA:
        children = [{'kind': 'playlist', 'id': playlist_ids[n - 1]} for n in data['playlists']]
        children += [{'kind': 'folder', 'id': ids[title]} for title in data['folders']]
        held.update(playlist_ids[n - 1] for n in data['playlists'])
        folders.append({
            'id': ids[data['title']],
            'title': data['title'],
            'parent': parents.get(data['title'], 'root'),
            'children': children,
        })
    top = [{'kind': 'playlist', 'id': pid} for pid in playlist_ids if pid not in held]
    top += [{'kind': 'folder', 'id': folder['id']}
            for folder in folders if folder['parent'] == 'root']
    return [{'id': 'root', 'title': 'Playlists', 'parent': None, 'children': top}] + folders


def slug(text):
    """Generate a clean URL-friendly slug."""
    return ''.join(c.lower() if c.isalnum() else '-' for c in text).strip('-')


def format_duration(ms):
    """Format milliseconds into 'M:SS' label."""
    total_seconds = round(ms / 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f'{minutes}:{seconds:02d}'


# ---------------------------------------------------------------------------
# Generated albums for big libraries (--albums)
# ---------------------------------------------------------------------------

GEN_WORDS = [
    'Amber', 'Silver', 'Hollow', 'Quiet', 'Electric', 'Paper', 'Velvet', 'Distant',
    'Northern', 'Golden', 'Crystal', 'Scarlet', 'Faded', 'Wandering', 'Bright',
    'Tidal', 'Frozen', 'Hidden', 'Lunar', 'Copper', 'Glass', 'Slow', 'Pale',
    'Silent', 'Burning', 'Winter', 'Coastal', 'Borrowed', 'Open', 'Last',
]
GEN_NOUNS = [
    'Harbours', 'Satellites', 'Gardens', 'Rivers', 'Lanterns', 'Signals',
    'Horizons', 'Orchards', 'Tides', 'Mirrors', 'Valleys', 'Engines', 'Letters',
    'Islands', 'Wires', 'Meadows', 'Comets', 'Streets', 'Kites', 'Waves',
    'Embers', 'Canyons', 'Clouds', 'Parades', 'Circuits', 'Forests', 'Bridges',
    'Maps', 'Rooms', 'Stations',
]
# What a generated song title gets when its word and noun are taken: realistic
# endings first, a number when those run out.
GEN_TAILS = [
    'at Dawn', 'in Blue', '(Reprise)', 'for Two', 'Again', '(Live)', 'Revisited', 'on Tape',
    'at Night', 'in Motion', '(Interlude)', 'Pt. II', 'Undone', '(Acoustic)', 'in the Rain',
    'Overture', '(Demo)', 'After Hours', 'Redux', '(Edit)', 'by Morning', 'in Reverse',
    'Suite', '(Instrumental)', 'Once More', 'at the Edge', 'in Silver', '(Extended)',
    'Theme', 'Unfolding', 'from Afar', '(Alternate Take)', 'in Colour', 'Lullaby',
    '(Radio Mix)', 'Nocturne', 'Waltz', 'Sketch', '(Outro)', 'Coda',
]
GEN_FIRST = ['Ada', 'Bram', 'Cleo', 'Dario', 'Elin', 'Fenna', 'Gus', 'Hana', 'Ivo', 'Juno',
             'Kaito', 'Lior', 'Mina', 'Nils', 'Oona', 'Pim', 'Rhea', 'Sol', 'Tove', 'Wren']
GEN_LAST = ['Aldane', 'Brisk', 'Corran', 'Dunmore', 'Elsworth', 'Falkner', 'Greaves', 'Hollin',
            'Ivers', 'Jessop', 'Kettle', 'Lowry', 'Marchetti', 'Norland', 'Oakes', 'Pellow',
            'Quill', 'Rowan', 'Sable', 'Thorne']


def song_counts(album_count, track_count):
    """How many songs each of `album_count` generated albums gets so that, with the
    hand-written albums', the library holds `track_count` songs in all: 8 to 16 an album
    around the mean, the last few adjusted to land exactly. Seeded on its own."""
    if album_count <= 0:
        return []
    written = sum(len(disc) for album in ALBUMS_DATA for disc in album['discs'])
    wanted = track_count - written
    if wanted < album_count:
        raise ValueError(f'--tracks must be at least {written + album_count} for '
                         f'{album_count} generated albums')
    mean = round(wanted / album_count)
    rnd = random.Random(11)
    counts = [rnd.randint(max(1, mean - 4), mean + 4) for _ in range(album_count)]
    step = 1 if sum(counts) < wanted else -1
    position = 0
    while sum(counts) != wanted:
        if counts[position] + step >= 1:
            counts[position] += step
        position = (position + 1) % album_count
    return counts


def generated_albums(count, tracks=None):
    """(artists, albums) in ARTISTS_DATA's and ALBUMS_DATA's shapes: the hand-written
    ones, then enough invented ones to make `count` albums, by invented artists of one
    to six albums each, of 8 to 16 songs, or sized so the library holds `tracks` songs in
    all when that is given. Seeded, so a count always gives the same library."""
    artists = list(ARTISTS_DATA)
    albums = list(ALBUMS_DATA)
    rnd = random.Random(7)  # not the builder's: the hand-written part stays as it was
    genres = sorted({artist['genre'] for artist in ARTISTS_DATA})
    seen_artists = {artist['name'] for artist in artists}
    seen_titles = {album['title'] for album in albums}
    seen_songs = {song for album in albums for disc in album['discs'] for song in disc}
    tails = random.Random(17)  # its own, so the albums and artists drawn from rnd stay as they were
    counts = song_counts(count - len(albums), tracks) if tracks is not None else None
    remaining = 0

    def unique(make, seen):
        for _ in range(20):
            name = make()
            if name not in seen:
                break
        else:
            name = f'{make()} {len(seen) + 1}'
        seen.add(name)
        return name

    def song_title(base):
        """base, or base with a tail (or at last a number) that no song has yet."""
        title = base
        for _ in range(20):
            if title not in seen_songs:
                break
            title = f'{base} {tails.choice(GEN_TAILS)}'
        else:
            number = 2
            while f'{base} {number}' in seen_songs:
                number += 1
            title = f'{base} {number}'
        seen_songs.add(title)
        return title

    while len(albums) < count:
        if remaining == 0:
            remaining = rnd.randint(1, 6)
            name = unique(lambda: rnd.choice([
                f'The {rnd.choice(GEN_WORDS)} {rnd.choice(GEN_NOUNS)}',
                f'{rnd.choice(GEN_FIRST)} {rnd.choice(GEN_LAST)}',
                f'{rnd.choice(GEN_NOUNS)} & {rnd.choice(GEN_NOUNS)}',
            ]), seen_artists)
            genre = rnd.choice(genres)
            bio = f'An invented {genre.lower()} act, generated for big demo libraries.'
            artists.append({'name': name, 'genre': genre, 'bio': bio})
        remaining -= 1
        artist = artists[-1]
        title = unique(lambda: rnd.choice([
            f'{rnd.choice(GEN_WORDS)} {rnd.choice(GEN_NOUNS)}',
            f'{rnd.choice(GEN_NOUNS)} of {rnd.choice(GEN_WORDS)} {rnd.choice(GEN_NOUNS)}',
            f'The {rnd.choice(GEN_WORDS)} {rnd.choice(GEN_NOUNS)}',
        ]), seen_titles)
        song_count = counts[len(albums) - len(ALBUMS_DATA)] if counts else rnd.randint(8, 16)
        songs = [song_title(f'{rnd.choice(GEN_WORDS)} {rnd.choice(GEN_NOUNS)}')
                 for _ in range(song_count)]
        albums.append({
            'artist_idx': len(artists) - 1,
            'title': title,
            'year': rnd.randint(1968, 2026),
            'genre': artist['genre'],
            'summary': f"A generated {artist['genre'].lower()} album by {artist['name']}.",
            'discs': [songs],
        })
    return artists, albums


def generated_playlists(count):
    """PLAYLISTS_DATA's entries, then enough invented ones to make `count` playlists with
    Favourite Songs (which the builder adds last) counted in: curated by invented people or
    "Harbourlight <genre>", each drawing on one to three genres. Seeded."""
    playlists = list(PLAYLISTS_DATA)
    rnd = random.Random(13)  # its own: the hand-written playlists' songs stay as they were
    genres = sorted({artist['genre'] for artist in ARTISTS_DATA})
    seen = {playlist['title'] for playlist in playlists}
    while len(playlists) + 1 < count:
        for _ in range(20):
            title = rnd.choice([
                f'{rnd.choice(GEN_WORDS)} {rnd.choice(GEN_NOUNS)} Mix',
                f'{rnd.choice(GEN_NOUNS)} for {rnd.choice(GEN_WORDS)} Days',
                f"{rnd.choice(GEN_FIRST)}'s {rnd.choice(GEN_NOUNS)}",
            ])
            if title not in seen:
                break
        else:
            title = f'{title} {len(seen) + 1}'
        seen.add(title)
        genre = rnd.choice(genres)
        curator = rnd.choice([f'Curated by {rnd.choice(GEN_FIRST)} {rnd.choice(GEN_LAST)}',
                              f'Harbourlight {genre}'])
        playlists.append({
            'title': title,
            'subtitle': curator,
            'genre': genre,
            'summary': f'A generated {genre.lower()} playlist for big demo libraries.',
            'filter_genres': sorted(set([genre] + rnd.sample(genres, rnd.randint(0, 2)))),
        })
    return playlists


def generated_videos(count, artists_data):
    """VIDEOS_DATA's entries, then enough invented ones to make `count` music videos, each by
    one of artists_data (the generated artists too, when there are any): titles a word and
    a noun, with a tail or a number where that pair is taken. Seeded."""
    videos = list(VIDEOS_DATA)
    rnd = random.Random(29)  # its own: nothing else drawn changes
    seen = {video['title'] for video in videos}
    while len(videos) < count:
        title = f'{rnd.choice(GEN_WORDS)} {rnd.choice(GEN_NOUNS)}'
        if title in seen:
            title = f'{title} {rnd.choice(GEN_TAILS)}'
        if title in seen:
            title = f'{title} {len(videos) + 1}'
        seen.add(title)
        videos.append({'title': title, 'artist_idx': rnd.randrange(len(artists_data)),
                       'year': rnd.randint(2005, 2026)})
    return videos


# The playlist --long-playlist adds: a fixed ID, so a scroll test can open it.
LONG_PLAYLIST_ID = 'l.pllong'


def _draw_one(job):
    out_path, kwargs, thumb_path, box = job
    if 'banner' in kwargs:  # an artist's banner: no thumbnail
        draw_banner(out_path, **kwargs['banner'])
        return
    draw_cover(out_path, **kwargs)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(out_path, *box, True)
    pixbuf.savev(thumb_path, 'jpeg', ['quality'], ['90'])


def thumb_file(thumb_dir, art_path, wide=False):
    """The thumbnail of the cover at art_path in thumb_dir, named as a sync names it
    (normalize.thumb_name(): a wide cover's, a video's, apart)."""
    return os.path.join(thumb_dir, normalize.thumb_name(os.path.basename(art_path), wide))


def draw_covers(covers, thumb_dir, thumb_size):
    """Draw each queued cover (draw_cover arguments) and its thumbnail (thumb_file(), in
    normalize.thumb_box(): a wide cover's by its shorter edge, as a sync scales a video's) in
    thumb_dir: in this process for the usual few dozen, in a pool of processes (forked:
    there are no threads here) for a big generated library."""
    jobs = [(out_path, kwargs, thumb_file(thumb_dir, out_path, kwargs.get('wide', False)),
             normalize.thumb_box(thumb_size, kwargs.get('wide', False)))
            for out_path, kwargs in covers]
    if len(jobs) < 200:
        for job in jobs:
            _draw_one(job)
        return
    context = multiprocessing.get_context('fork')
    with concurrent.futures.ProcessPoolExecutor(mp_context=context) as pool:
        for _ in pool.map(_draw_one, jobs, chunksize=16):
            pass


# ---------------------------------------------------------------------------
# Main library builder
# ---------------------------------------------------------------------------

def build_demo_library(out_dir, cover_size=config.COVER_SIZE, thumb_size=config.THUMB_SIZE,
                       album_count=None, playlist_count=None, track_count=None,
                       video_count=None, long_playlist=None):
    """Generate library.json, cover_size artwork and the thumb_size thumbnails the
    tiles draw, and record both sizes in art/.sizes as a sync does. An album_count
    above the hand-written albums' adds generated ones (generated_albums), sized to
    hold track_count songs in all when given; a playlist_count above the hand-written
    playlists' (Favourite Songs counted) adds generated ones (generated_playlists); a
    long_playlist adds LONG_PLAYLIST_ID, of that many songs; a video_count above the
    hand-written videos' adds generated ones (generated_videos)."""
    rnd = random.Random(42)
    artists_data, albums_data = generated_albums(album_count or len(ALBUMS_DATA), track_count)
    playlists_data = generated_playlists(playlist_count or len(PLAYLISTS_DATA) + 1)
    if long_playlist:
        playlists_data.append({
            'id': LONG_PLAYLIST_ID, 'songs': long_playlist, 'title': 'The Long Playlist',
            'subtitle': '', 'genre': ARTISTS_DATA[0]['genre'],
            'summary': 'An invented playlist of thousands of songs, for scroll tests.',
        })
    videos_data = generated_videos(video_count or len(VIDEOS_DATA), artists_data)

    art_dir = os.path.join(out_dir, 'art')
    thumb_dir = os.path.join(out_dir, 'thumb')
    os.makedirs(art_dir, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)
    # Before drawing: a changed thumbnail size wipes thumb/.
    normalize.apply_art_sizes(out_dir, cover_size, thumb_size)

    # The covers are drawn together at the end (draw_covers), in parallel when
    # there are many; each draw_cover call below only queues one.
    covers = []

    def draw_cover(out_path, **kwargs):
        covers.append((out_path, kwargs))

    def thumb_for(art_path, wide=False):
        """The thumbnail of a cover in thumb/ (`wide`: a video's, drawn wide: thumb_file())."""
        return thumb_file(thumb_dir, art_path, wide)

    catalog_id_base = 1724040000
    global_trk_counter = 1

    # 1. Build Albums and Tracks
    albums = []
    # Map artist_idx -> list of album objects for this artist
    artist_albums_map = {i: [] for i in range(len(artists_data))}
    all_tracks_catalog = []

    for alb_idx, alb_data in enumerate(albums_data, 1):
        artist_info = artists_data[alb_data['artist_idx']]
        artist_name = artist_info['name']
        album_id = f'l.alb{alb_idx:03d}'
        album_cat_id = str(catalog_id_base + alb_idx * 10)
        album_url = f"https://music.apple.com/us/album/{slug(alb_data['title'])}/{album_cat_id}"

        # Assign artwork palette & motif
        palette = PALETTES[alb_idx % len(PALETTES)]
        motif = album_motif(alb_data['genre'], alb_idx)
        art_hash = hashlib.sha1(album_id.encode('utf-8')).hexdigest()
        art_path = os.path.join(art_dir, f'{art_hash}.jpg')
        draw_cover(
            out_path=art_path,
            title=alb_data['title'],
            subtitle=artist_name,
            badge=str(alb_data['year']),
            palette=palette,
            motif=motif,
            is_artist=False,
            size=cover_size,
        )
        thumb_path = thumb_for(art_path)

        # Build album tracks and groups
        album_groups = []
        album_all_tracks = []
        overall_index = 0

        for disc_idx, disc_track_names in enumerate(alb_data['discs'], 1):
            disc_entries = []
            group_name = f'Disc {disc_idx}' if len(alb_data['discs']) > 1 else 'Disc 1'

            for trk_num, trk_title in enumerate(disc_track_names, 1):
                # Duration between 140s and 380s
                dur_ms = rnd.randint(140, 380) * 1000 + rnd.randint(0, 999)
                is_explicit = rnd.random() < 0.12  # ~12% explicit

                trk_obj = {
                    'id': f'i.trk{global_trk_counter:04d}',
                    'catalogId': str(catalog_id_base + 50000 + global_trk_counter),
                    'title': trk_title,
                    'artist': artist_name,
                    'album': alb_data['title'],
                    'trackNumber': trk_num,
                    'discNumber': disc_idx,
                    'durationMs': dur_ms,
                    'durationLabel': format_duration(dur_ms),
                    'explicit': is_explicit,
                    'index': overall_index,
                    'thumb': None,
                    'type': 'library-songs',
                    'genre': alb_data['genre'],
                    'year': alb_data['year'],
                }
                global_trk_counter += 1
                overall_index += 1
                disc_entries.append(trk_obj)
                album_all_tracks.append(trk_obj)
                all_tracks_catalog.append((artist_info['genre'], trk_obj, thumb_path))

            album_groups.append({
                'name': group_name,
                'play': {'kind': 'album', 'id': album_id},
                'entries': disc_entries,
            })

        total_ms = sum(t['durationMs'] for t in album_all_tracks)
        album_explicit = any(t['explicit'] for t in album_all_tracks)

        album_item = {
            'id': album_id,
            'kind': 'album',
            'title': alb_data['title'],
            'subtitle': artist_name,
            'year': alb_data['year'],
            'genre': alb_data['genre'],
            'summary': alb_data['summary'],
            'art': art_path,
            'thumb': thumb_path,
            'artColor': palette[1],
            'trackCount': len(album_all_tracks),
            'durationMs': total_ms,
            'explicit': album_explicit,
            'catalogId': album_cat_id,
            'url': album_url,
            'play': {'kind': 'album', 'id': album_id},
            'groups': album_groups,
        }
        albums.append(album_item)
        artist_albums_map[alb_data['artist_idx']].append(album_item)

    # 2. Build Artists
    artists = []
    for art_idx, art_data in enumerate(artists_data, 1):
        artist_id = f'l.art{art_idx:03d}'
        artist_cat_id = str(catalog_id_base + 1000 + art_idx)
        artist_url = f"https://music.apple.com/us/artist/{slug(art_data['name'])}/{artist_cat_id}"

        # Assign artwork palette & motif
        palette = PALETTES[(art_idx * 3) % len(PALETTES)]
        art_hash = hashlib.sha1(artist_id.encode('utf-8')).hexdigest()
        art_path = os.path.join(art_dir, f'{art_hash}.jpg')
        draw_cover(
            out_path=art_path,
            title=art_data['name'],
            subtitle='Artist',
            badge='ARTIST',
            palette=palette,
            motif='',
            is_artist=True,
            size=cover_size,
        )

        artist_albs = artist_albums_map[art_idx - 1]
        artist_groups = []
        for alb in artist_albs:
            # Flatten tracks from album groups
            alb_tracks = []
            for g in alb['groups']:
                alb_tracks.extend(g['entries'])

            artist_groups.append({
                'name': alb['title'],
                'play': {'kind': 'album', 'id': alb['id']},
                'entries': alb_tracks,
            })

        artist_item = {
            'id': artist_id,
            'kind': 'artist',
            'title': art_data['name'],
            'subtitle': '',
            'year': None,
            'genre': art_data['genre'],
            'summary': art_data['bio'],
            'art': art_path,
            'thumb': thumb_for(art_path),
            'artColor': palette[1],
            'albumCount': len(artist_albs),
            'explicit': False,
            'catalogId': artist_cat_id,
            'url': artist_url,
            'play': {'kind': 'artist', 'id': artist_id},
            'groups': artist_groups,
        }
        artists.append(artist_item)

    # 3. Build Playlists
    # The catalog by genre, each list in catalog order with its position, so a playlist's
    # matching tracks are merged back into catalog order (as one pass over the catalog
    # would list them) without a pass over 40,000 tracks per playlist.
    by_genre = {}
    for position, (genre, trk, thumb) in enumerate(all_tracks_catalog):
        by_genre.setdefault(genre, []).append((position, (trk, thumb)))
    playlists = []
    for pl_idx, pl_data in enumerate(playlists_data, 1):
        playlist_id = pl_data.get('id') or f'l.pl{pl_idx:03d}'
        playlist_cat_id = str(catalog_id_base + 2000 + pl_idx)
        playlist_url = ('https://music.apple.com/us/playlist/'
                        f"{slug(pl_data['title'])}/{playlist_cat_id}")

        palette = PALETTES[(pl_idx * 5) % len(PALETTES)]
        motif = MOTIFS[(pl_idx * 2) % len(MOTIFS)]
        art_hash = hashlib.sha1(playlist_id.encode('utf-8')).hexdigest()
        art_path = os.path.join(art_dir, f'{art_hash}.jpg')
        draw_cover(
            out_path=art_path,
            title=pl_data['title'],
            subtitle=pl_data['subtitle'],
            badge='PLAYLIST',
            palette=palette,
            motif=motif,
            is_artist=False,
            size=cover_size,
        )

        if 'songs' in pl_data:  # the long playlist: any songs, from a random source of its own
            selected_raw = random.Random(61).sample(
                [(t, thumb) for _, t, thumb in all_tracks_catalog],
                min(len(all_tracks_catalog), pl_data['songs']))
        else:
            # Pick candidate tracks matching playlist genre or collection
            matching_tracks = [pair for _position, pair in heapq.merge(
                *(by_genre.get(genre, []) for genre in dict.fromkeys(pl_data['filter_genres'])))]
            if len(matching_tracks) < 18:
                matching_tracks = [(t, thumb) for _, t, thumb in all_tracks_catalog]

            # Deterministic sample for this playlist
            selected_raw = rnd.sample(matching_tracks, min(len(matching_tracks), 22))

        playlist_tracks = []
        # A playlist's rows carry their own cover — the album's, here.
        for i, (raw_trk, raw_thumb) in enumerate(selected_raw):
            playlist_tracks.append({
                'id': f'i.plt{pl_idx:02d}_{i:03d}',
                'catalogId': raw_trk['catalogId'],
                'title': raw_trk['title'],
                'artist': raw_trk['artist'],
                'album': raw_trk['album'],
                'trackNumber': i + 1,
                'discNumber': 1,
                'durationMs': raw_trk['durationMs'],
                'durationLabel': raw_trk['durationLabel'],
                'explicit': raw_trk['explicit'],
                'index': i,
                'thumb': raw_thumb,
                'type': 'library-songs',
                'genre': raw_trk['genre'],
                'year': raw_trk['year'],
            })

        total_ms = sum(t['durationMs'] for t in playlist_tracks)
        playlist_explicit = any(t['explicit'] for t in playlist_tracks)

        playlist_item = {
            'id': playlist_id,
            'kind': 'playlist',
            'title': pl_data['title'],
            'subtitle': pl_data['subtitle'],
            'year': 2026,
            'genre': pl_data['genre'],
            'summary': pl_data['summary'],
            'art': art_path,
            'thumb': thumb_for(art_path),
            'artColor': palette[1],
            'trackCount': len(playlist_tracks),
            'durationMs': total_ms,
            'explicit': playlist_explicit,
            'catalogId': playlist_cat_id,
            'url': playlist_url,
            'modified': '2026-01-01T09:00:00Z',  # the listing's date, as the sync writes it
            'tracksModified': '2026-01-01T09:00:00Z',  # the tracks' stamp (README)
            'play': {'kind': 'playlist', 'id': playlist_id},
            'groups': [
                {
                    'name': 'Tracks',
                    'play': {'kind': 'playlist', 'id': playlist_id},
                    'entries': playlist_tracks,
                }
            ],
        }
        if 'songs' in pl_data:
            playlist_item['added'] = added_text(NEWEST_ADDED - 20 * 24 * 3600)
        playlists.append(playlist_item)

    # The Favourite Songs playlist, after the others so they stay as they were. Its own random
    # source, so nothing drawn from rnd afterwards changes either.
    favourites_id = f'l.pl{len(playlists) + 1:03d}'
    art_path = os.path.join(art_dir,
                            f"{hashlib.sha1(favourites_id.encode('utf-8')).hexdigest()}.jpg")
    draw_cover(
        out_path=art_path,
        title=FAVOURITES_DATA['title'],
        subtitle=None,
        badge='PLAYLIST',
        palette=('#2b0914', '#d90429', '#ffb4a2'),
        motif='aurora',
        is_artist=False,
        size=cover_size,
    )
    loved = random.Random(7).sample(all_tracks_catalog,
                                    min(len(all_tracks_catalog), FAVOURITES_DATA['size']))
    favourite_tracks = []
    for i, (_genre, raw_trk, raw_thumb) in enumerate(loved):
        favourite_tracks.append({
            'id': f'i.fav_{i:03d}',
            'catalogId': raw_trk['catalogId'],
            'title': raw_trk['title'],
            'artist': raw_trk['artist'],
            'album': raw_trk['album'],
            'trackNumber': i + 1,
            'discNumber': 1,
            'durationMs': raw_trk['durationMs'],
            'durationLabel': raw_trk['durationLabel'],
            'explicit': raw_trk['explicit'],
            'index': i,
            'thumb': raw_thumb,
            'type': 'library-songs',
            'genre': raw_trk['genre'],
            'year': raw_trk['year'],
        })
    favourites_play = {'kind': 'playlist', 'id': favourites_id}
    playlists.append({
        'id': favourites_id,
        'kind': 'playlist',
        'title': FAVOURITES_DATA['title'],
        'subtitle': FAVOURITES_DATA['subtitle'],
        'year': None,
        'genre': None,
        'summary': FAVOURITES_DATA['summary'],
        'art': art_path,
        'thumb': thumb_for(art_path),
        'artColor': '#d90429',
        'trackCount': len(favourite_tracks),
        'durationMs': sum(t['durationMs'] for t in favourite_tracks),
        'explicit': any(t['explicit'] for t in favourite_tracks),
        'catalogId': None,
        'url': None,
        'modified': '2026-01-01T09:00:00Z',
        'tracksModified': '2026-01-01T09:00:00Z',
        'play': favourites_play,
        'attributes': {'isFavourites': True},
        'groups': [{'name': 'Tracks', 'play': favourites_play, 'entries': favourite_tracks}],
    })

    # 4. Build Radio Stations
    radio_stations = []
    for st_idx, st_data in enumerate(STATIONS_DATA, 1):
        station_id = f'ra.st{st_idx:03d}'
        station_cat_id = str(catalog_id_base + 3000 + st_idx)
        station_url = ('https://music.apple.com/us/station/'
                       f"{slug(st_data['title'])}/{station_cat_id}")

        palette = PALETTES[(st_idx * 7) % len(PALETTES)]
        motif = MOTIFS[(st_idx * 3) % len(MOTIFS)]
        art_hash = hashlib.sha1(station_id.encode('utf-8')).hexdigest()
        art_path = os.path.join(art_dir, f'{art_hash}.jpg')
        draw_cover(
            out_path=art_path,
            title=st_data['title'],
            subtitle=st_data['subtitle'],
            badge='RADIO',
            palette=palette,
            motif=motif,
            is_artist=False,
            size=cover_size,
        )

        station_item = {
            'id': station_id,
            'kind': 'station',
            'title': st_data['title'],
            'subtitle': st_data['subtitle'],
            'year': None,
            'genre': st_data['genre'],
            'summary': st_data['summary'],
            'art': art_path,
            'thumb': thumb_for(art_path),
            'artColor': palette[1],
            'explicit': False,
            'catalogId': station_cat_id,
            'url': station_url,
            'play': {'kind': 'station', 'id': station_id},
            'groups': [],
        }
        radio_stations.append(station_item)

    # 5. Music videos: after the rest, with a random source of their own, so nothing above
    # changes. 16:9 artwork, and the Item shape the sync gives them (normalize_item).
    videos = []
    video_rnd = random.Random(23)
    for v_idx, v_data in enumerate(videos_data, 1):
        video_id = f'i.mv{v_idx:04d}'
        video_cat_id = str(catalog_id_base + 4000 + v_idx)
        artist_info = artists_data[v_data['artist_idx']]
        palette = PALETTES[(v_idx * 11) % len(PALETTES)]
        art_path = os.path.join(art_dir,
                                f"{hashlib.sha1(video_id.encode('utf-8')).hexdigest()}.jpg")
        draw_cover(
            out_path=art_path,
            title=v_data['title'],
            subtitle=artist_info['name'],
            badge=None,
            palette=palette,
            motif=MOTIFS[(v_idx * 7) % len(MOTIFS)],
            is_artist=False,
            size=cover_size,
            wide=True,
        )
        dur_ms = video_rnd.randint(180, 330) * 1000
        videos.append({
            'id': video_id,
            'kind': 'video',
            'title': v_data['title'],
            'subtitle': artist_info['name'],
            'year': v_data['year'],
            'genre': artist_info['genre'],
            'summary': None,
            'art': art_path,
            'thumb': thumb_for(art_path, wide=True),
            'artColor': palette[1],
            'durationMs': dur_ms,
            'explicit': False,
            'catalogId': video_cat_id,
            'url': f"https://music.apple.com/us/music-video/{slug(v_data['title'])}/{video_cat_id}",
            'play': {'kind': 'musicVideo', 'id': video_id},
            'groups': [],
        })

    # 6. Build Shelves
    # Heavy Rotation: popular albums + top playlists + 1 radio station
    heavy_rotation_items = [
        albums[1],   # Islands in Suspension
        albums[3],   # Neon Velocity
        albums[6],   # Saltwater Hymns
        albums[9],   # Leaves in Still Water
        albums[18],  # Golden Hour Vibrations
        playlists[0],  # Late Night Drift
        playlists[5],  # Sunset Drive
        radio_stations[0],  # Lighthouse One
    ]

    # Recently Added: 8 newest albums
    newest_albums = sorted(albums, key=lambda a: (a['year'] or 0, a['id']), reverse=True)[:8]

    # Recently Played (Home's own, recent-played.json: build_recently_played): 4 albums + 3
    # playlists + 1 radio station, played last first
    recently_played_items = [
        albums[4],   # Transmission Zero
        albums[12],  # Midnight Cassette Club
        albums[21],  # Tremolo Summer
        albums[24],  # Tokyo Rain Reflections
        playlists[1],  # Analog Horizons
        playlists[2],  # Indie Currents
        playlists[6],  # Neon Expressway
        radio_stations[2],  # Slow Tide Radio
    ]

    # Made for You: 4 playlists + 4 albums
    made_for_you_items = [
        playlists[3],  # Deep Focus & Stillness
        playlists[4],  # Modern Jazz Underground
        playlists[9],  # Quiet Reflections
        playlists[10],  # Soul & Reverie
        albums[15],  # Stellar Cartography
        albums[27],  # Constellation Hours
        albums[30],  # Warm Tape Hiss
        albums[38],  # Low Frequency Grooves
    ]

    shelves = [
        {
            'key': 'heavy-rotation',
            'title': 'Heavy Rotation',
            'items': heavy_rotation_items,
        },
        {
            'key': 'recently-added',
            'title': 'Recently Added',
            'items': newest_albums,
        },
        {
            'key': 'made-for-you',
            'title': 'Made for You',
            # A recommendation's reason, which Home shows under its title.
            'subtitle': 'Picked from the albums and playlists you play most',
            'items': made_for_you_items,
        },
    ]

    favourites = add_dates_and_favourites(albums, playlists, videos, newest_albums,
                                          favourite_tracks)

    library = {
        'version': 5,  # sync.LIBRARY_VERSION
        'generated': '2026-09-25T12:00:00Z',
        'storefront': 'us',
        'sections': {
            'albums': albums,
            'artists': artists,
            'playlists': playlists,
            'radio': radio_stations,
            'videos': videos,
        },
        'shelves': shelves,
        'folders': build_folders([playlist['id'] for playlist in playlists]),
        'favourites': favourites,
    }

    # 7. The catalog's page of each hand-written artist and each playlist's suggested songs,
    # after the rest, each with a random source of its own, so nothing above changes.
    own_videos = videos[:len(VIDEOS_DATA)]  # the pages' videos, whatever --videos adds
    build_artist_pages(out_dir, artists_data[:len(ARTISTS_DATA)], artists, artist_albums_map,
                       albums, own_videos, draw_cover, thumb_for, cover_size, library['generated'])
    build_suggestions(out_dir, playlists, albums, library['generated'])
    build_album_pages(out_dir, artists_data[:len(ARTISTS_DATA)], artists, artist_albums_map,
                      albums[:len(ALBUMS_DATA)], own_videos, playlists, draw_cover,
                      thumb_for,
                      cover_size, library['generated'])
    build_radio_page(out_dir, radio_stations, albums[:len(ALBUMS_DATA)], own_videos,
                     draw_cover,
                     thumb_for, cover_size, library['generated'])
    build_search_catalog(out_dir, artists[:len(ARTISTS_DATA)], albums[:len(ALBUMS_DATA)],
                         playlists, own_videos, radio_stations, draw_cover, thumb_for,
                         cover_size,
                         library['generated'])
    build_charts_page(out_dir, albums[:len(ALBUMS_DATA)], playlists[:len(PLAYLISTS_DATA)],
                      own_videos, draw_cover, thumb_for, cover_size, library['generated'])
    build_replay_page(out_dir, albums[:len(ALBUMS_DATA)], artists[:len(ARTISTS_DATA)],
                      draw_cover, thumb_for, cover_size, library['generated'])
    build_new_page(out_dir, albums[:len(ALBUMS_DATA)], playlists[:len(PLAYLISTS_DATA)],
                   own_videos, radio_stations, draw_cover, library['generated'])
    build_recently_played(out_dir, recently_played_items, library['generated'])
    build_credits(out_dir, albums[:len(ALBUMS_DATA)], library['generated'])

    draw_covers(covers, thumb_dir, thumb_size)

    out_file = os.path.join(out_dir, 'library.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(library, f, indent=2)

    print(
        f'demo library: {len(albums)} albums, {len(artists)} artists, '
        f'{len(playlists)} playlists, {len(radio_stations)} radio stations, '
        f'{len(videos)} music videos in {out_dir}'
    )


def build_search_catalog(out_dir, artists, albums, playlists, videos, stations, draw_cover,
                         thumb_for, cover_size, generated):
    """Write demo-search.json (normalize.demo_search_path()): the invented catalog the demo
    engine searches (Engine.search, catalog.demo_search()), {shelves: [{key, items}]} by search
    kind: the hand-written artists, their albums and songs, the playlists, music videos and
    stations, the Radio page's shows (radio.json, written first: their pages are there) and
    invented curators drawn here, each Apple-like one with its page (categories/<id>.json:
    playlists of the demo's). Albums, artists and playlists keep their library ids, so their
    pages are the library's. Shows and curators carry `curatorKind`, as a search's do."""
    art_dir = os.path.join(out_dir, 'art')

    def brief(item, **changes):
        return dict(item, groups=[], **changes)

    def curator(number, title, kind, palette_index):
        item_id = f'demo.curator{number:02d}'
        path = os.path.join(art_dir, f"{hashlib.sha1(item_id.encode('utf-8')).hexdigest()}.jpg")
        palette = PALETTES[palette_index % len(PALETTES)]
        draw_cover(out_path=path, title=title, subtitle=None, badge=None, palette=palette,
                   motif=MOTIFS[palette_index % len(MOTIFS)], is_artist=False,
                   size=cover_size)
        url = f'https://music.apple.com/us/curator/{slug(title)}/{item_id}'
        if kind == 'label':  # a third party's: normalize.curator_link's shape
            return {'id': item_id, 'kind': 'link', 'title': title, 'subtitle': '',
                    'year': None, 'art': path, 'thumb': thumb_for(path), 'artColor': None,
                    'url': url, 'play': {}, 'groups': [], 'curatorKind': 'curator'}
        page = {'id': item_id, 'title': title, 'host': '', 'banner': None,
                'shelves': [{'key': f'cat-{item_id}-playlists', 'title': 'Playlists',
                             'items': [brief(playlist) for playlist in
                                       playlists[number % 3::3][:4]]}],
                'cached': generated,
                'demo': True}  # invented: the demo engine answers only these
        with open(os.path.join(out_dir, 'categories', f'{item_id}.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(page, f, indent=2)
        return {'id': item_id, 'kind': 'category', 'title': title, 'subtitle': None,
                'art': path, 'thumb': thumb_for(path), 'artColor': palette[1], 'url': url,
                'play': {}, 'groups': [], 'curatorKind': 'curator'}

    songs = []
    for album in albums:
        for group in album['groups']:
            for track in group['entries']:
                songs.append({'id': track['catalogId'], 'kind': 'song', 'title': track['title'],
                              'subtitle': track['artist'], 'album': album['title'],
                              'year': album['year'], 'genre': album['genre'], 'summary': None,
                              'art': album['art'], 'thumb': album['thumb'],
                              'artColor': album['artColor'], 'explicit': track['explicit'],
                              'durationMs': track['durationMs'],
                              'catalogId': track['catalogId'], 'url': None,
                              'play': {'kind': 'song', 'id': track['catalogId']},
                              'groups': []})
    with open(os.path.join(out_dir, 'radio.json'), encoding='utf-8') as f:
        radio = json.load(f)
    shows = [dict(show, curatorKind='show') for shelf in radio['shelves']
             if shelf['key'] == 'radio-shows' for show in shelf['items']]
    os.makedirs(os.path.join(out_dir, 'categories'), exist_ok=True)
    curators = [curator(number, title, kind, number * 5 + 1)
                for number, (title, kind) in enumerate(DEMO_SEARCH_CURATORS)]
    catalog = {
        'shelves': [
            {'key': 'artists', 'items': [brief(artist) for artist in artists]},
            {'key': 'songs', 'items': songs},
            {'key': 'albums', 'items': [brief(album) for album in albums]},
            {'key': 'playlists', 'items': [brief(playlist) for playlist in playlists]},
            {'key': 'music-videos', 'items': [brief(video) for video in videos]},
            {'key': 'stations', 'items': [brief(station) for station in stations]},
            {'key': 'radio-shows', 'items': shows},
            {'key': 'curators', 'items': curators},
        ],
        'cached': generated,
        'demo': True,  # invented: the demo engine answers only this
    }
    with open(os.path.join(out_dir, 'demo-search.json'), 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2)


def build_suggestions(out_dir, playlists, albums, generated):
    """Write suggestions/<playlist id>.json for each playlist: the songs Apple would suggest
    adding to it (normalize.playlist_suggestions()'s shape, kept as the engine keeps it),
    SUGGESTIONS of the library's songs it does not hold, its genre's first: enough for
    twelve shown and spares to fill places and step through on Refresh."""
    rnd = random.Random(37)
    out = os.path.join(out_dir, 'suggestions')
    os.makedirs(out, exist_ok=True)
    for playlist in playlists:
        held = {entry['catalogId'] for group in playlist['groups'] for entry in group['entries']}
        same, other = [], []
        for album in albums:
            for group in album['groups']:
                for track in group['entries']:
                    if track['catalogId'] in held:
                        continue
                    (same if album['genre'] == playlist['genre'] else other).append(
                        (track, album))
        picks = rnd.sample(same, min(SUGGESTIONS, len(same)))
        picks += rnd.sample(other, min(SUGGESTIONS - len(picks), len(other)))
        items = [{'id': track['catalogId'], 'kind': 'song', 'title': track['title'],
                  'subtitle': track['artist'], 'artistName': track['artist'],
                  'album': album['title'], 'year': album['year'], 'genre': album['genre'],
                  'summary': None,
                  'art': album['art'], 'thumb': album['thumb'], 'artColor': album['artColor'],
                  'explicit': track['explicit'], 'durationMs': track['durationMs'],
                  'catalogId': track['catalogId'], 'url': None,
                  'play': {'kind': 'song', 'id': track['catalogId']}, 'groups': []}
                 for track, album in picks]
        answer = {'items': items, 'cached': generated,
                  'demo': True}  # invented: the demo engine answers only these
        with open(os.path.join(out, f"{playlist['id']}.json"), 'w', encoding='utf-8') as f:
            json.dump(answer, f, indent=2)


def build_artist_pages(out_dir, artists_data, artists, artist_albums_map, albums, videos,
                       draw_cover, thumb_for, cover_size, generated):
    """Write artists/<catalog id>.json for each hand-written artist: the page the catalog would
    answer (normalize.artist_page()'s shape, kept as the engine keeps it, stamped `cached`
    with the library's date), made of the artist's albums, songs and videos in the library,
    and invented singles, playlists, radio episodes and interviews drawn here. Every other
    artist, the first among them, hosts a radio show (Radio Shows: a category tile, as
    Apple's curators are), whose page is written beside the Radio page's shows
    (categories/<id>.json: its episodes, then its playlists). Albums and songs keep their
    library ids, so their pages are the library's."""
    rnd = random.Random(31)
    art_dir = os.path.join(out_dir, 'art')
    pages_dir = os.path.join(out_dir, 'artists')
    categories_dir = os.path.join(out_dir, 'categories')
    os.makedirs(pages_dir, exist_ok=True)
    os.makedirs(categories_dir, exist_ok=True)

    def cover(item_id, title, subtitle, palette_index, wide=False, badge=None):
        path = os.path.join(art_dir, f"{hashlib.sha1(item_id.encode('utf-8')).hexdigest()}.jpg")
        draw_cover(out_path=path, title=title, subtitle=subtitle, badge=badge,
                   palette=PALETTES[palette_index % len(PALETTES)],
                   motif=MOTIFS[palette_index % len(MOTIFS)], is_artist=False,
                   size=cover_size, wide=wide)
        return path

    def brief(item, **changes):
        """An Item as a shelf carries it: no groups, unless `changes` give some."""
        return dict(item, groups=[], **changes)

    def tracks_of(album):
        return [entry for group in album['groups'] for entry in group['entries']]

    def song(track, album):
        return {'id': track['catalogId'], 'kind': 'song', 'title': track['title'],
                'subtitle': track['artist'], 'album': album['title'], 'year': album['year'],
                'art': album['art'], 'thumb': album['thumb'], 'artColor': album['artColor'],
                'explicit': track['explicit'], 'durationMs': track['durationMs'],
                'catalogId': track['catalogId'], 'url': None,
                'play': {'kind': 'song', 'id': track['catalogId']}, 'groups': []}

    def upcoming(index, name, genre):
        """The artist's invented pre-release album (DEMO_UPCOMING): its tracks out already
        playable, the others `unreleased`, as normalize.normalize_album() marks them."""
        title, released, songs = DEMO_UPCOMING
        item_id = f'demo.upcoming{index:02d}'
        year = int(released[:4])
        art = cover(item_id, title, name, index * 5 + 7, badge='SOON')
        play = {'kind': 'album', 'id': item_id}
        lengths = random.Random(53)  # its own: the rest of the page draws as before
        tracks = []
        for number, (song_title, out) in enumerate(songs, 1):
            duration = lengths.randint(170000, 330000)
            track_id = f'17240980{index:02d}{number:02d}'
            track = {'id': track_id, 'catalogId': track_id, 'title': song_title,
                     'artist': name, 'album': title, 'trackNumber': number, 'discNumber': 1,
                     'durationMs': duration, 'durationLabel': format_duration(duration),
                     'explicit': False, 'index': number - 1, 'thumb': None, 'type': 'songs'}
            if not out:
                track['unreleased'] = True
            tracks.append(track)
        return {'id': item_id, 'kind': 'album', 'title': title, 'subtitle': name,
                'artistName': name, 'year': year, 'genre': genre,
                'summary': (f'{name} return with a record of night harbours and slow-burning '
                            'crescendos, previewed by two singles.'),
                'art': art, 'thumb': thumb_for(art),
                'artColor': PALETTES[(index * 5 + 7) % len(PALETTES)][1],
                'trackCount': len(tracks), 'durationMs': sum(t['durationMs'] for t in tracks),
                'explicit': False, 'catalogId': item_id, 'url': None, 'play': play,
                'prerelease': True, 'releaseDate': released,
                'groups': [{'name': 'Disc 1', 'play': play, 'entries': tracks}]}

    def collection(item_id, kind, title, subtitle, year, entries, palette_index, badge=None):
        """An invented album or playlist of `entries` (library tracks), with its cover."""
        art = cover(item_id, title, subtitle, palette_index, badge=badge)
        play = {'kind': kind, 'id': item_id}
        tracks = [dict(entry, index=position) for position, entry in enumerate(entries)]
        return {'id': item_id, 'kind': kind, 'title': title, 'subtitle': subtitle,
                'year': year, 'genre': None, 'summary': None, 'art': art,
                'thumb': thumb_for(art), 'artColor': PALETTES[palette_index % len(PALETTES)][1],
                'trackCount': len(tracks), 'durationMs': sum(t['durationMs'] for t in tracks),
                'explicit': any(t['explicit'] for t in tracks), 'catalogId': None, 'url': None,
                'play': play, 'groups': [{'name': '', 'play': play, 'entries': tracks}]}

    catalog_playlists = []  # (artist, genre, its two playlists) for build_playlist_pages
    for index, (data, artist) in enumerate(zip(artists_data, artists, strict=False)):
        name, genre = data['name'], data['genre']
        catalog_id = artist['catalogId']
        own = sorted(artist_albums_map[index], key=lambda album: album['year'], reverse=True)
        origin, born, group = ARTIST_FACTS[index]
        tracks = [(track, album) for album in own for track in tracks_of(album)]
        newest = own[0]
        shelves = []

        def shelf(key, title, items, shelves=shelves):
            if items:
                shelves.append({'key': key, 'title': title, 'items': items, 'more': False})

        top = rnd.sample(tracks, min(24, len(tracks)))
        shelf('featured-albums', 'Essential Albums', [
            brief(album, subtitle=album['summary'].split('. ')[0].rstrip('.') + '.')
            for album in own[:2]])
        # The first artist's next album is not out yet: Apple features it as the latest
        # release and lists it first among the albums, with its tracks (the demo engine
        # answers no item(), so its page has them from here).
        coming = upcoming(index, name, genre) if index == 0 else None
        shelf('full-albums', 'Albums', ([dict(coming, subtitle=str(coming['year']))]
                                        if coming else [])
              + [brief(album, subtitle=str(album['year'])) for album in own])
        shelf('music-videos', 'Music Videos', [
            brief(video, subtitle=str(video['year'])) for video in videos
            if video['subtitle'] == name])
        # A catalog playlist's rows carry their own thumbnails, as item() names them: here,
        # each song's album's.
        picks = [dict(track, thumb=album['thumb'])
                 for track, album in rnd.sample(tracks, min(12, len(tracks)))]
        artist_playlists = [
            collection(f'pl.demo{index:02d}1', 'playlist', f'{name} Essentials',
                       f'Harbourlight {genre}', None, picks, index * 5 + 1),
            collection(f'pl.demo{index:02d}2', 'playlist', f'{name}: Deep Cuts',
                       f'Harbourlight {genre}', None, picks[::-1][:8], index * 5 + 2)]
        shelf('playlists', 'Artist Playlists', artist_playlists)
        catalog_playlists.append((artist, genre, artist_playlists))
        hosted = None
        if index % 2 == 0:
            show_title = DEMO_HOSTED_SHOWS[(index // 2) % len(DEMO_HOSTED_SHOWS)].format(
                artist=name)
            show_id = f'demo.ashow{index:02d}'
            art = cover(show_id, show_title, name, index * 5 + 4, badge='SHOW')
            hosted = {'id': show_id, 'kind': 'category', 'title': show_title,
                      'subtitle': name, 'art': art, 'thumb': thumb_for(art),
                      'artColor': PALETTES[(index * 5 + 4) % len(PALETTES)][1],
                      'url': f'https://music.apple.com/us/curator/{slug(show_title)}/{show_id}'}
            shelf('radio-shows', 'Radio Shows', [hosted])
        singles = []
        for number, (track, _album) in enumerate(rnd.sample(tracks, min(2, len(tracks))), 1):
            year = newest['year'] + (1 if number == 1 else 0)
            single = collection(f'demo.single{index:02d}{number}', 'album',
                                f"{track['title']} - Single", str(year), year, [track],
                                index * 5 + 3 + number, badge=str(year))
            singles.append(single)
        shelf('singles', 'Singles & EPs', singles)
        if index % 4 == 2:
            live = collection(f'demo.live{index:02d}', 'album', 'Live at the Harbour Hall',
                              str(newest['year']), newest['year'],
                              [track for track, _album in tracks[:6]], index * 5 + 4,
                              badge='LIVE')
            shelf('live-albums', 'Live Albums', [live])
        if index % 5 == 0:
            best = collection(f'demo.best{index:02d}', 'album', f'The Best of {name}',
                              str(newest['year']), newest['year'],
                              [track for track, _album in tracks[::2][:10]], index * 5 + 6)
            shelf('compilation-albums', 'Compilations', [best])
        guest = artist_albums_map[(index + 1) % len(artists_data)][0]
        shelf('appears-on-albums', 'Appears On', [brief(guest)])
        episodes = []
        for number in range(3):
            words = DEMO_EPISODES[(index + number) % len(DEMO_EPISODES)].format(
                artist=name, album=own[number % len(own)]['title'], genre=genre)
            item_id = f'ra.demo{index:02d}{number}'
            show = DEMO_SHOWS[(index + number) % len(DEMO_SHOWS)]
            art = cover(item_id, words, show, index * 7 + number)
            episodes.append({'id': item_id, 'kind': 'station', 'title': words, 'subtitle': show,
                             'year': None, 'genre': genre, 'summary': None, 'art': art,
                             'thumb': thumb_for(art), 'artColor': None, 'explicit': False,
                             'catalogId': None, 'url': None,
                             'play': {'kind': 'station', 'id': item_id}, 'groups': []})
        shelf('more-to-hear', 'More To Hear', episodes)
        if hosted is not None:
            show_page = {
                'id': hosted['id'], 'title': hosted['title'], 'host': name, 'banner': None,
                'shelves': [
                    {'key': f"cat-{hosted['id']}-episodes", 'title': 'Episodes',
                     'items': [dict(episode, subtitle=hosted['title']) for episode in episodes]},
                    {'key': 'playlists', 'title': '', 'items': artist_playlists}],
                'cached': generated,
                'demo': True}  # invented: the demo engine answers only these
            with open(os.path.join(categories_dir, f"{hosted['id']}.json"), 'w',
                      encoding='utf-8') as f:
                json.dump(show_page, f, indent=2)
        interviews = []
        for number in range(2):
            words = DEMO_INTERVIEWS[(index + number) % len(DEMO_INTERVIEWS)].format(
                artist=name, album=newest['title'])
            item_id = f'{int(catalog_id) * 10 + number}'
            art = cover(f'post.{item_id}', words, name, index * 3 + number, wide=True)
            seconds = rnd.randint(70, 900)
            interviews.append({'id': item_id, 'kind': 'link', 'video': True, 'title': words,
                               'subtitle': f'{seconds // 60}:{seconds % 60:02d}',
                               'year': newest['year'], 'art': art,
                               'thumb': thumb_for(art, wide=True),
                               'url': f'https://music.apple.com/us/post/{item_id}',
                               'play': {}, 'groups': []})
        shelf('more-to-see', 'More To See', interviews)
        others = [other for other in artists if other is not artist]
        shelf('similar-artists', 'Similar Artists', [
            brief(other, id=other['catalogId'], play={'kind': 'artist', 'id': other['catalogId']})
            for other in rnd.sample(others, min(8, len(others)))])

        released = f"{newest['year']}-0{index % 9 + 1}-1{index % 9}"
        # A banner for every third artist (the first among them), as Apple has one for about
        # half: drawn here, on disk as `art` where Apple's would be a URL to fetch.
        banner = None
        if index % 3 == 0:
            palette = PALETTES[(index * 5) % len(PALETTES)]
            path = os.path.join(art_dir, hashlib.sha1(
                f'banner.{catalog_id}'.encode()).hexdigest() + '.jpg')
            # Queued, drawn with the covers (in their pool: nothing may decode or save an
            # image in this process before it forks).
            draw_cover(out_path=path,
                       banner={'palette': palette, 'figures': 3 if group else 1, 'seed': index})
            width, height = BANNER_SIZE
            banner = {'url': None, 'art': path, 'crop': 'vf', 'width': width,
                      'height': height, 'color': palette[0]}
        page = {
            'id': catalog_id,
            'artist': brief(artist, id=catalog_id, origin=origin, bornOrFormed=born,
                            isGroup=group, play={'kind': 'artist', 'id': catalog_id}),
            'banner': banner,
            'latest': {'key': 'latest-release', 'title': 'Latest Release',
                       'item': (dict(coming, subtitle=str(coming['year'])) if coming else
                                brief(newest, subtitle=str(newest['year']),
                                      releaseDate=released))},
            'topSongs': {'key': 'top-songs', 'title': 'Top Songs', 'more': False,
                         'items': [song(track, album) for track, album in top]},
            'shelves': shelves,
            # The star: the first two of every four artists are favourites (the first over
            # its banner, the second on the plain header), the next two not.
            'favourite': index % 4 < 2,
            'cached': generated,
            'demo': True,  # invented: the demo engine answers only these
        }
        with open(os.path.join(pages_dir, f'{catalog_id}.json'), 'w', encoding='utf-8') as f:
            json.dump(page, f, indent=2)
        if coming is not None:
            # What the catalog shows under its tracks (normalize.album_page()'s shape): its
            # date to come, its label, and More By.
            label = DEMO_LABELS[index % len(DEMO_LABELS)]
            album_page = {
                'id': coming['id'], 'artistId': catalog_id, 'artistName': name,
                'release': {'releaseDate': coming['releaseDate'],
                            'copyright': f"℗ {coming['year']} {label}", 'recordLabel': label},
                'shelves': [{'key': 'more-by-artist', 'title': '', 'more': False,
                             'items': [brief(album, subtitle=str(album['year']),
                                             artistName=name) for album in own]}],
                'cached': generated,
                'demo': True,  # invented: the demo engine answers only these
            }
            albums_dir = os.path.join(out_dir, 'albums')
            os.makedirs(albums_dir, exist_ok=True)
            with open(os.path.join(albums_dir, f"{coming['id']}.json"), 'w',
                      encoding='utf-8') as f:
                json.dump(album_page, f, indent=2)
    build_playlist_pages(out_dir, catalog_playlists, generated)


def build_playlist_pages(out_dir, catalog_playlists, generated):
    """Write playlists/<id>.json for each catalog playlist of the artists' pages: what the
    catalog would answer for the rest of its page (normalize.playlist_page()'s shape, kept as
    the engine keeps it, stamped `cached` with the library's date): its curator, an invented
    Apple curator, Harbourlight <genre>, whose page is written in categories/<id>.json (its
    playlists), and its shelves: Featured Artists (the artist and the two after them), More
    By the curator (the artist's other playlist) and You Might Also Like (the next three
    artists' first playlists). The playlists keep their tracks, so their pages open in the
    demo. `catalog_playlists` is [(artist, genre, [two playlists])], in the artists'
    order."""
    pages_dir = os.path.join(out_dir, 'playlists')
    categories_dir = os.path.join(out_dir, 'categories')
    os.makedirs(pages_dir, exist_ok=True)
    os.makedirs(categories_dir, exist_ok=True)
    count = len(catalog_playlists)
    for index, (_artist, genre, playlists) in enumerate(catalog_playlists):
        title = f'Harbourlight {genre}'
        curator_id = f'demo.apcurator{index:02d}'
        curator = {'id': curator_id, 'kind': 'category', 'title': title, 'subtitle': None,
                   'art': None, 'artColor': None,
                   'url': f'https://music.apple.com/us/curator/{slug(title)}/{curator_id}'}
        curator_page = {'id': curator_id, 'title': title, 'host': '', 'banner': None,
                        'shelves': [{'key': f'cat-{curator_id}-playlists', 'title': 'Playlists',
                                     'items': playlists}],
                        'cached': generated,
                        'demo': True}  # invented: the demo engine answers only these
        with open(os.path.join(categories_dir, f'{curator_id}.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(curator_page, f, indent=2)
        featured = [catalog_playlists[(index + step) % count][0] for step in range(3)]
        artists = [dict(other, id=other['catalogId'], groups=[],
                        play={'kind': 'artist', 'id': other['catalogId']})
                   for other in featured]
        alike = [catalog_playlists[(index + step) % count][2][0] for step in range(1, 4)]
        for playlist in playlists:
            page = {
                'id': playlist['id'],
                'curator': curator,
                'shelves': [
                    {'key': 'featured-artists', 'title': 'Featured Artists', 'more': False,
                     'items': artists},
                    {'key': 'more-by-curator', 'title': f'More By {title}', 'more': False,
                     'items': [other for other in playlists if other is not playlist]},
                    {'key': 'you-might-also-like', 'title': 'You Might Also Like',
                     'more': False, 'items': alike}],
                'cached': generated,
                'demo': True,  # invented: the demo engine answers only these
            }
            with open(os.path.join(pages_dir, f"{playlist['id']}.json"), 'w',
                      encoding='utf-8') as f:
                json.dump(page, f, indent=2)


def build_album_pages(out_dir, artists_data, artists, artist_albums_map, albums, videos,
                      playlists, draw_cover, thumb_for, cover_size, generated):
    """Write albums/<catalog id>.json for each hand-written album: what the catalog would
    answer for the rest of its page (normalize.album_page()'s shape, kept as the engine keeps
    it, stamped `cached` with the library's date): its release date, copyright and label,
    and its shelves, made of the library's own albums, videos and playlists (their pages the
    library's) and an invented deluxe or remastered edition or two drawn here."""
    rnd = random.Random(41)
    art_dir = os.path.join(out_dir, 'art')
    pages_dir = os.path.join(out_dir, 'albums')
    os.makedirs(pages_dir, exist_ok=True)

    def brief(item, **changes):
        """An Item as a shelf carries it: no groups, unless `changes` give some."""
        return dict(item, groups=[], **changes)

    def edition(album, number):
        """An invented other version of `album`: its tracks under another title and cover."""
        item_id = f"demo.edition{album['id'][len('l.alb'):]}{number}"
        title = DEMO_EDITIONS[number].format(title=album['title'])
        year = album['year'] + (0 if number == 0 else 8)
        path = os.path.join(art_dir, f"{hashlib.sha1(item_id.encode('utf-8')).hexdigest()}.jpg")
        palette_index = int(album['id'][len('l.alb'):])  # the album's own palette, PALETTES
        draw_cover(out_path=path, title=title, subtitle=album['subtitle'],
                   badge='DELUXE' if number == 0 else 'REMASTER',
                   palette=PALETTES[(palette_index + 3 + number) % len(PALETTES)],
                   motif=MOTIFS[(palette_index + number) % len(MOTIFS)], is_artist=False,
                   size=cover_size)
        play = {'kind': 'album', 'id': item_id}
        tracks = [dict(entry, index=position) for position, entry in
                  enumerate(entry for group in album['groups'] for entry in group['entries'])]
        return dict(album, id=item_id, title=title, subtitle=str(year), year=year, art=path,
                    thumb=thumb_for(path), catalogId=None, url=None, play=play,
                    artistName=album['subtitle'],
                    groups=[{'name': '', 'play': play, 'entries': tracks}])

    for number, album in enumerate(albums):
        artist_index = next(index for index, owned in artist_albums_map.items()
                            if any(other is album for other in owned))
        artist = artists[artist_index]
        name = artists_data[artist_index]['name']
        shelves = []

        def shelf(key, title, items, shelves=shelves):
            if items:
                shelves.append({'key': key, 'title': title, 'items': items, 'more': False})

        shelf('other-versions', 'Other Versions',
              [edition(album, edition_number) for edition_number in range(2 - number % 2)])
        shelf('related-videos', 'Music Videos', [
            brief(video, artistName=name) for video in videos if video['subtitle'] == name])
        shelf('more-by-artist', '', [
            brief(other, subtitle=str(other['year']), artistName=name)
            for other in sorted(artist_albums_map[artist_index],
                                key=lambda other: other['year'], reverse=True)
            if other is not album])
        held = {entry['catalogId'] for group in album['groups'] for entry in group['entries']}
        shelf('appears-on', 'Featured On', [
            brief(playlist) for playlist in playlists
            if any(entry['catalogId'] in held
                   for group in playlist['groups'] for entry in group['entries'])])
        alike = [other for other in albums if other['genre'] == album['genre']
                 and other['subtitle'] != album['subtitle']]
        alike += rnd.sample([other for other in albums if other not in alike
                             and other['subtitle'] != album['subtitle']], 8 - min(8, len(alike)))
        shelf('you-might-also-like', 'You Might Also Like', [
            brief(other, artistName=other['subtitle']) for other in alike[:8]])

        label = DEMO_LABELS[artist_index % len(DEMO_LABELS)]
        page = {
            'id': album['catalogId'],
            'artistId': artist['catalogId'],
            'artistName': name,
            'release': {'releaseDate': f"{album['year']}-{number % 12 + 1:02d}-"
                                       f"{number % 27 + 1:02d}",
                        'copyright': f"℗ {album['year']} {label}", 'recordLabel': label},
            'shelves': shelves,
            'cached': generated,
            'demo': True,  # invented: the demo engine answers only these
        }
        with open(os.path.join(pages_dir, f"{album['catalogId']}.json"), 'w',
                  encoding='utf-8') as f:
            json.dump(page, f, indent=2)


def build_credits(out_dir, albums, generated):
    """Write credits/<catalog id>.json for each song of the hand-written albums: the credits
    Apple would answer for it (normalize.song_credits()'s shape, kept as the engine keeps it,
    stamped `cached` with the library's date): its artist and a session player or two as
    Performers, its writers, its producers and engineers, all invented. The last album's last
    song has none (the dialog's No Credits)."""
    rnd = random.Random(43)
    out = os.path.join(out_dir, 'credits')
    os.makedirs(out, exist_ok=True)
    songs = [(track, album) for album in albums for group in album['groups']
             for track in group['entries']]

    def people(count, roles):
        return [{'name': name, 'roles': rnd.choice(roles)}
                for name in rnd.sample(DEMO_CREDIT_PEOPLE, count)]

    for number, (track, album) in enumerate(songs):
        categories = []
        if number < len(songs) - 1:
            performers = [{'name': album['subtitle'], 'roles': ['Performer']}]
            performers += people(rnd.randint(1, 3), DEMO_PERFORMER_ROLES)
            for kind, found in (('performer', performers),
                                ('composer-and-lyrics', people(rnd.randint(1, 2),
                                                               DEMO_WRITER_ROLES)),
                                ('production-and-engineering', people(rnd.randint(2, 4),
                                                                      DEMO_PRODUCTION_ROLES))):
                categories.append({'kind': kind, 'title': DEMO_CREDIT_TITLES[kind],
                                   'people': found})
        answer = {'categories': categories, 'cached': generated,
                  'demo': True}  # invented: the demo engine answers only these
        with open(os.path.join(out, f"{track['catalogId']}.json"), 'w', encoding='utf-8') as f:
            json.dump(answer, f, indent=2)


def build_recently_played(out_dir, items, generated):
    """Write recent-played.json, Home's Recently Played (normalize.recently_played()'s shape,
    kept as the engine keeps it, stamped `cached` with the library's date): the library's
    own albums, playlists and station, without their track lists, as Apple's answer has
    them."""
    answer = {'items': [dict(item, groups=[]) for item in items],
              'cached': generated,
              'demo': True}  # invented: the demo engine answers only these
    with open(os.path.join(out_dir, 'recent-played.json'), 'w', encoding='utf-8') as f:
        json.dump(answer, f, indent=2)


def build_radio_page(out_dir, stations, albums, videos, draw_cover, thumb_for, cover_size,
                     generated):
    """Write radio.json, the Radio page's answer (normalize.radio_shelves()'s shape, kept as
    the engine keeps it, stamped `cached` with the library's date): the invented live
    stations first (`live`), then the latest episodes of the invented shows, the shows
    themselves (category tiles, as Apple's curators are), genre stations, albums and music
    videos from the library. Each show also gets the page its tile opens
    (categories/<id>.json, normalize.category_page()'s shape: its host, its episodes, and an
    invented 3:1 banner drawn here for all but the last). No `events`
    and no `expires`: a demo built once cannot know what is on air when it is shown."""
    art_dir = os.path.join(out_dir, 'art')
    categories_dir = os.path.join(out_dir, 'categories')
    os.makedirs(categories_dir, exist_ok=True)

    def cover(item_id, title, subtitle, palette_index, badge=None):
        path = os.path.join(art_dir, f"{hashlib.sha1(item_id.encode('utf-8')).hexdigest()}.jpg")
        draw_cover(out_path=path, title=title, subtitle=subtitle, badge=badge,
                   palette=PALETTES[palette_index % len(PALETTES)],
                   motif=MOTIFS[palette_index % len(MOTIFS)], is_artist=False, size=cover_size)
        return path

    def station(item_id, title, subtitle, genre, palette_index, badge=None, art=None):
        art = art or cover(item_id, title, subtitle, palette_index, badge=badge)
        return {'id': item_id, 'kind': 'station', 'title': title, 'subtitle': subtitle,
                'year': None, 'genre': genre, 'summary': None, 'art': art,
                'thumb': thumb_for(art), 'artColor': PALETTES[palette_index % len(PALETTES)][1],
                'explicit': False, 'catalogId': None,
                'url': f'https://music.apple.com/us/station/{slug(title)}/{item_id}',
                'play': {'kind': 'station', 'id': item_id}, 'groups': []}

    def brief(item):
        return dict(item, groups=[])

    live = []
    for number, (title, programme) in enumerate(DEMO_LIVE):
        if number == 0:  # the library's own first station: the same id and cover
            first = stations[0]
            live.append(dict(brief(first), title=title, subtitle=programme))
        else:
            live.append(station(f'ra.live{number:02d}', title, programme, 'Various',
                                number * 5 + 2, badge='LIVE'))

    shows, episodes = [], []
    for number, (show, host) in enumerate(DEMO_RADIO_SHOWS):
        show_id = f'demo.show{number:02d}'
        art = cover(show_id, show, host, number * 4 + 9, badge='SHOW')
        palette = PALETTES[(number * 4 + 9) % len(PALETTES)]
        shows.append({'id': show_id, 'kind': 'category', 'title': show, 'subtitle': host,
                      'art': art, 'thumb': thumb_for(art), 'artColor': palette[1],
                      'url': f'https://music.apple.com/us/curator/{slug(show)}/{show_id}'})
        own = []
        for part in range(3):
            album = albums[(number * 3 + part) % len(albums)]
            words = DEMO_EPISODES[(number + part) % len(DEMO_EPISODES)].format(
                artist=album['subtitle'], album=album['title'], genre=album['genre'])
            own.append(station(f'ra.ep{number:02d}{part}', words, show, album['genre'],
                               number * 4 + part + 3))
        episodes.extend(own[:2])
        # A banner for each show but the last (whose page keeps the plain title): its host
        # on a stage, drawn here, on disk as `art` where Apple's would be a URL to fetch.
        banner = None
        if number < len(DEMO_RADIO_SHOWS) - 1:
            path = os.path.join(art_dir, hashlib.sha1(
                f'banner.{show_id}'.encode()).hexdigest() + '.jpg')
            draw_cover(out_path=path, banner={'palette': palette, 'figures': 1,
                                              'seed': 100 + number})
            width, height = BANNER_SIZE
            banner = {'url': None, 'art': path, 'crop': normalize.CURATOR_BANNER_CROP,
                      'width': width, 'height': height, 'color': palette[0]}
        page = {'id': show_id, 'title': show, 'host': host, 'banner': banner,
                'shelves': [{'key': f'cat-{show_id}-episodes', 'title': 'Episodes',
                             'items': own}],
                'cached': generated,
                'demo': True}  # invented: the demo engine answers only these
        with open(os.path.join(categories_dir, f'{show_id}.json'), 'w', encoding='utf-8') as f:
            json.dump(page, f, indent=2)

    genres = [station(f'ra.genre{number:02d}', f'{name} Station', 'Harbourlight', genre,
                      number * 3 + 7)
              for number, (name, genre) in enumerate(DEMO_GENRE_STATIONS)]
    answer = {
        'shelves': [
            {'key': 'radio-live', 'title': 'Live Radio', 'items': live, 'live': True},
            {'key': 'radio-episodes', 'title': 'Latest Episodes', 'items': episodes},
            {'key': 'radio-shows', 'title': 'Radio Shows', 'items': shows},
            {'key': 'radio-genres', 'title': 'Genre Stations', 'items': genres},
            {'key': 'radio-albums', 'title': 'Heard on the Shows',
             'items': [brief(album) for album in albums[::5]]},
            {'key': 'radio-videos', 'title': 'Music Videos',
             'items': [brief(video) for video in videos]},
        ],
        'cached': generated,
        'demo': True,  # invented: the demo engine answers only these
    }
    with open(os.path.join(out_dir, 'radio.json'), 'w', encoding='utf-8') as f:
        json.dump(answer, f, indent=2)


def build_charts_page(out_dir, albums, playlists, videos, draw_cover, thumb_for, cover_size,
                      generated):
    """Write charts.json, the Charts page's answer (normalize.charts_shelves()'s shape, kept
    as the engine keeps it, stamped `cached` with the library's date): Top Songs (fifty of
    the library's songs, ranked, a list), Top Albums and Top Playlists (the library's own,
    ranked: their pages are the library's), the Daily Top 100 (the world's and invented
    countries') and City Charts (invented cities') as playlists of the library's songs with
    their tracks, so their pages open without the engine, and Top Music Videos. Beside it,
    genres.json (DEMO_CHART_GENRES, normalize.catalog_genres()'s shape) and each genre's
    charts in charts/<id>.json: Top Songs and Top Albums of the library's albums of it."""
    rnd = random.Random(43)
    art_dir = os.path.join(out_dir, 'art')

    def brief(item):
        return dict(item, groups=[])

    song = chart_song
    tracks = [(track, album) for album in albums for group in album['groups']
              for track in group['entries']]

    def chart_playlist(item_id, title, count, palette_index, badge):
        path = os.path.join(art_dir, f"{hashlib.sha1(item_id.encode('utf-8')).hexdigest()}.jpg")
        draw_cover(out_path=path, title=title, subtitle=None, badge=badge,
                   palette=PALETTES[palette_index % len(PALETTES)],
                   motif=MOTIFS[palette_index % len(MOTIFS)], is_artist=False, size=cover_size)
        play = {'kind': 'playlist', 'id': item_id}
        entries = [dict(track, index=position)
                   for position, (track, _album) in enumerate(rnd.sample(tracks, count))]
        return {'id': item_id, 'kind': 'playlist', 'title': title, 'subtitle': 'Harbourlight',
                'year': None, 'genre': None, 'summary': None, 'art': path,
                'thumb': thumb_for(path), 'artColor': PALETTES[palette_index % len(PALETTES)][1],
                'trackCount': len(entries),
                'durationMs': sum(entry['durationMs'] for entry in entries),
                'explicit': any(entry['explicit'] for entry in entries), 'catalogId': None,
                'url': None, 'play': play,
                'groups': [{'name': '', 'play': play, 'entries': entries}]}

    daily = [chart_playlist('pl.demo-top100-global', 'Top 100: Global', 40, 11, 'TOP 100')]
    daily += [chart_playlist(f'pl.demo-top100-{number:02d}', f'Top 100: {place}', 40,
                             number * 3 + 13, 'TOP 100')
              for number, place in enumerate(DEMO_CHART_COUNTRIES)]
    cities = [chart_playlist(f'pl.demo-city{number:02d}', f'Top 25: {city}', 25,
                             number * 5 + 4, 'CITY')
              for number, city in enumerate(DEMO_CHART_CITIES)]
    shown = [playlist for playlist in playlists
             if not (playlist.get('attributes') or {}).get('isFavourites')]
    answer = {
        'shelves': [
            {'key': 'charts-songs', 'title': 'Top Songs', 'chart': 'songs', 'ranked': True,
             'form': 'songs', 'items': [song(track, album)
                                        for track, album in rnd.sample(tracks, 50)]},
            {'key': 'charts-albums', 'title': 'Top Albums', 'chart': 'albums', 'ranked': True,
             'items': [brief(album) for album in rnd.sample(albums, 24)]},
            {'key': 'charts-playlists', 'title': 'Top Playlists', 'chart': 'playlists',
             'ranked': True, 'items': [brief(playlist) for playlist in shown]},
            {'key': 'charts-dailyGlobalTopCharts', 'title': 'Daily Top 100',
             'chart': 'dailyGlobalTopCharts', 'items': daily},
            {'key': 'charts-cityCharts', 'title': 'City Charts', 'chart': 'cityCharts',
             'items': cities},
            {'key': 'charts-music-videos', 'title': 'Top Music Videos', 'chart': 'music-videos',
             'ranked': True, 'items': [brief(video) for video in videos]},
        ],
        'cached': generated,
        'demo': True,  # invented: the demo engine answers only these
    }
    with open(os.path.join(out_dir, 'charts.json'), 'w', encoding='utf-8') as f:
        json.dump(answer, f, indent=2)

    # Each genre's, drawn apart (a Random of its own) so the charts above stay as they were.
    by_genre = random.Random(47)
    genres = {'genres': [{'id': genre_id, 'title': name}
                         for genre_id, name, _kinds in DEMO_CHART_GENRES],
              'cached': generated, 'demo': True}
    with open(os.path.join(out_dir, 'genres.json'), 'w', encoding='utf-8') as f:
        json.dump(genres, f, indent=2)
    os.makedirs(os.path.join(out_dir, 'charts'), exist_ok=True)
    for genre_id, _name, kinds in DEMO_CHART_GENRES:
        own = [album for album in albums if album['genre'] in kinds]
        own_tracks = [(track, album) for track, album in tracks if album['genre'] in kinds]
        chart = {
            'shelves': [
                {'key': 'charts-songs', 'title': 'Top Songs', 'chart': 'songs', 'ranked': True,
                 'form': 'songs', 'items': [
                     song(track, album) for track, album in by_genre.sample(
                         own_tracks, min(30, len(own_tracks)))]},
                {'key': 'charts-albums', 'title': 'Top Albums', 'chart': 'albums',
                 'ranked': True,
                 'items': [brief(album) for album in by_genre.sample(own, len(own))]},
            ],
            'cached': generated,
            'demo': True,  # invented: the demo engine answers only these
        }
        with open(os.path.join(out_dir, 'charts', f'{genre_id}.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(chart, f, indent=2)


def chart_song(track, album):
    """One of the library's songs as a chart's song (normalize.charts_shelves()'s, and
    Replay's Top Songs): its catalog id, its album's art and name."""
    return {'id': track['catalogId'], 'kind': 'song', 'title': track['title'],
            'subtitle': track['artist'], 'year': album['year'], 'genre': album['genre'],
            'summary': None, 'art': album['art'], 'thumb': album['thumb'],
            'artColor': album['artColor'], 'durationMs': track['durationMs'],
            'explicit': track['explicit'], 'catalogId': track['catalogId'], 'url': None,
            'play': {'kind': 'song', 'id': track['catalogId']}, 'groups': [],
            'album': album['title']}


def build_replay_page(out_dir, albums, artists, draw_cover, thumb_for, cover_size, generated):
    """Write replay.json, the Replay page's answer for the latest of DEMO_REPLAY_YEARS
    (normalize.replay_page()'s shape, kept as the engine keeps it, with its `basis`,
    normalize.REPLAY_SHAPE, and stamped `cached` with the library's date), and each earlier
    year's in replay/<year>.json: Top Songs (twenty-five
    of the library's songs, ranked, a list), Top Artists and Top Albums (ten of the
    library's own each, ranked: their pages are the library's), untitled for the app to name
    them, then each year's invented Replay playlist of the library's songs, with its tracks,
    so its page opens without the engine. A Random of its own: the other pages stay as they
    were."""
    rnd = random.Random(53)
    art_dir = os.path.join(out_dir, 'art')
    tracks = [(track, album) for album in albums for group in album['groups']
              for track in group['entries']]

    def replay_playlist(year, palette_index):
        item_id = f'pl.demo-replay-{year}'
        path = os.path.join(art_dir, f"{hashlib.sha1(item_id.encode('utf-8')).hexdigest()}.jpg")
        palette = PALETTES[palette_index % len(PALETTES)]
        draw_cover(out_path=path, title=f'Replay {year}', subtitle=None,
                   badge='REPLAY', palette=palette, motif=MOTIFS[palette_index % len(MOTIFS)],
                   is_artist=False, size=cover_size)
        play = {'kind': 'playlist', 'id': item_id}
        entries = [dict(track, index=position)
                   for position, (track, _album) in enumerate(rnd.sample(tracks, 30))]
        return {'id': item_id, 'kind': 'playlist', 'title': f'Replay {year}',
                'subtitle': 'Harbourlight', 'year': None, 'genre': None, 'summary': None,
                'art': path, 'thumb': thumb_for(path), 'artColor': palette[1],
                'trackCount': len(entries),
                'durationMs': sum(entry['durationMs'] for entry in entries),
                'explicit': any(entry['explicit'] for entry in entries), 'catalogId': None,
                'url': None, 'play': play,
                'groups': [{'name': '', 'play': play, 'entries': entries}]}

    playlists = [replay_playlist(year, number * 7 + 2)
                 for number, year in enumerate(DEMO_REPLAY_YEARS)]
    os.makedirs(os.path.join(out_dir, 'replay'), exist_ok=True)
    for number, year in enumerate(DEMO_REPLAY_YEARS):
        answer = {
            'year': year,
            'years': list(DEMO_REPLAY_YEARS),
            'shelves': [
                {'key': 'replay-songs', 'title': '', 'chart': 'songs', 'ranked': True,
                 'form': 'songs',
                 'items': [chart_song(track, album) for track, album in rnd.sample(tracks, 25)]},
                {'key': 'replay-artists', 'title': '', 'chart': 'artists', 'ranked': True,
                 'items': [dict(artist, groups=[]) for artist in rnd.sample(artists, 10)]},
                {'key': 'replay-albums', 'title': '', 'chart': 'albums', 'ranked': True,
                 'items': [dict(album, groups=[]) for album in rnd.sample(albums, 10)]},
                {'key': 'replay-playlists', 'title': '', 'chart': 'replay-playlists',
                 'items': playlists},
            ],
            'basis': normalize.REPLAY_SHAPE,  # the shape the engine keeps it in
            'cached': generated,
            'demo': True,  # invented: the demo engine answers only these
        }
        path = (os.path.join(out_dir, 'replay.json') if number == 0
                else os.path.join(out_dir, 'replay', f'{year}.json'))
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(answer, f, indent=2)


# The New page's invented banners: the label over each, its line under the title, and which
# of the library's albums (by place) or playlists (`playlist`) it shows; the last has no
# banner of its own (its cover stands in, as when Apple's answer has none).
DEMO_BANNERS = [('NEW ALBUM', 'A tide of tape-looped guitars, out now', 'album', 0),
                ('UPDATED PLAYLIST', 'Fresh picks for slow mornings', 'playlist', 1),
                ('PRE-RELEASE', 'Hear the first two songs before Friday', 'album', 3),
                ('NEW EP', 'Four songs recorded live to tape', 'album', 5),
                ('EXCLUSIVE', 'The complete sessions, remastered', 'album', 7)]
# Its links (More to Explore, then the untitled genres' row): (label, kind, id[, genre]); the
# pages they open are written beside it (rooms/, groupings/, multirooms/), a genre's charts
# by build_charts_page (charts/<genre>.json).
DEMO_EXPLORE = [('Late-Night Listening', 'room', 'demo.room01'),
                ('Quiet Mornings', 'room', 'demo.room02'),
                ('Sounds of the Coast', 'grouping', 'demo.grouping01'),
                ('Instrumental Worlds', 'multiroom', 'demo.multiroom01'),
                ('Charts', 'charts', 'charts'),
                ('Electronic Charts', 'charts', 'charts', '9002'),
                ('Live Near You', 'link', 'https://example.org/live-near-you')]
DEMO_BANNER_SIZE = 1280  # an invented banner's width; 16:9, as Apple's wide cut is shown


def build_new_page(out_dir, albums, playlists, videos, stations, draw_cover, generated):
    """Write browse.json, the New page's answer (normalize.editorial_shelves()'s shape, kept
    as the engine keeps it, stamped `cached` with the library's date): the featured shelf of
    banners (DEMO_BANNERS: the library's own albums and playlists, so their pages are the
    library's, each with Apple's label, a line and, but the last, a 16:9 banner drawn here,
    on disk as `art` where Apple's would be a URL to fetch; `form: 'banners'`), then New
    Releases, playlists, stations and music videos of the library's, and `links`: More to
    Explore (DEMO_EXPLORE) and an untitled row of the albums' genres. Each link's page is
    written too: rooms/<id>.json (normalize.editorial_room()'s shape), groupings/<id>.json
    (editorial_grouping()'s: the genres' pages too) and multirooms/<id>.json
    (editorial_multiroom()'s)."""
    art_dir = os.path.join(out_dir, 'art')

    def brief(item, **changes):
        return dict(item, groups=[], **changes)

    def write(folder, name, answer):
        os.makedirs(os.path.join(out_dir, folder), exist_ok=True)
        answer = dict(answer, cached=generated,
                      demo=True)  # invented: the demo engine answers only these
        with open(os.path.join(out_dir, folder, f'{name}.json'), 'w', encoding='utf-8') as f:
            json.dump(answer, f, indent=2)

    shown = [playlist for playlist in playlists
             if not (playlist.get('attributes') or {}).get('isFavourites')]
    banners = []
    for number, (badge, tagline, kind, place) in enumerate(DEMO_BANNERS):
        item = (albums if kind == 'album' else shown)[place % len(albums if kind == 'album'
                                                             else shown)]
        extra = {'badge': badge, 'tagline': tagline}
        if number < len(DEMO_BANNERS) - 1:
            palette = PALETTES[(number * 7 + 3) % len(PALETTES)]
            path = os.path.join(art_dir, hashlib.sha1(
                f"banner.new.{item['id']}".encode()).hexdigest() + '.jpg')
            draw_cover(out_path=path, title=item['title'], subtitle=item['subtitle'],
                       badge=None, palette=palette, motif=MOTIFS[number % len(MOTIFS)],
                       is_artist=False, size=DEMO_BANNER_SIZE, wide=True)
            extra['banner'] = {'url': None, 'art': path, 'crop': 'sr',
                               'width': DEMO_BANNER_SIZE,
                               'height': round(DEMO_BANNER_SIZE * 9 / 16),
                               'color': palette[0]}
        banners.append(brief(item, **extra))

    def links(rows):
        found = []
        for label, kind, link_id, *genre in rows:
            link = {'title': label, 'kind': kind, 'id': link_id,
                    'url': link_id if kind == 'link' else None}
            if genre:
                link['genre'] = genre[0]
            found.append(link)
        return found

    genres = sorted({album['genre'] for album in albums})[:9]
    genre_rows = [(genre, 'grouping', f'demo.genre{number:02d}')
                  for number, genre in enumerate(genres)]
    answer = {
        'shelves': [
            {'key': 'new-featured', 'title': '', 'featured': True, 'form': 'banners',
             'items': banners},
            {'key': 'new-releases', 'title': 'New Releases',
             'items': [brief(album) for album in albums[1::2]]},
            {'key': 'new-playlists', 'title': 'Playlists to Try',
             'items': [brief(playlist) for playlist in shown]},
            {'key': 'new-stations', 'title': 'Stations to Tune In',
             'items': [brief(station) for station in stations]},
            {'key': 'new-videos', 'title': 'New Music Videos',
             'items': [brief(video) for video in videos]},
        ],
        'links': [
            {'key': 'new-explore', 'title': 'More to Explore', 'links': links(DEMO_EXPLORE)},
            {'key': 'new-genres', 'title': '', 'links': links(genre_rows)},
        ],
    }
    write('', 'browse', answer)

    write('rooms', 'demo.room01', {'id': 'demo.room01', 'title': 'Late-Night Listening',
                                   'items': [brief(album) for album in albums[::2]]})
    write('rooms', 'demo.room02', {'id': 'demo.room02', 'title': 'Quiet Mornings',
                                   'items': [brief(playlist) for playlist in shown]
                                   + [brief(album) for album in albums[1::3]]})
    write('groupings', 'demo.grouping01', {
        'id': 'demo.grouping01', 'title': 'Sounds of the Coast',
        'shelves': [
            {'key': 'grp-shore', 'title': 'Shoreline Albums',
             'items': [brief(album) for album in albums[2::3]]},
            {'key': 'grp-playlists', 'title': 'Coastal Playlists',
             'items': [brief(playlist) for playlist in shown[::2]]},
        ],
        'links': [{'key': 'grp-more', 'title': 'More Like This',
                   'links': links(DEMO_EXPLORE[:2])}]})
    write('multirooms', 'demo.multiroom01', {
        'id': 'demo.multiroom01', 'title': 'Instrumental Worlds',
        'shelves': [
            {'key': 'mr-quiet', 'title': 'Quiet Instrumentals',
             'items': [brief(album) for album in albums[::3]]},
            {'key': 'mr-videos', 'title': 'Watch and Listen',
             'items': [brief(video) for video in videos]},
        ],
        'links': []})
    for genre, _kind, grouping_id in genre_rows:
        write('groupings', grouping_id, {
            'id': grouping_id, 'title': genre,
            'shelves': [{'key': f'grp-{grouping_id}-albums', 'title': f'Essential {genre}',
                         'items': [brief(album) for album in albums
                                   if album['genre'] == genre]}],
            'links': []})


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description='Generate an invented Apple Music library for demos, screenshots and tests.'
    )
    parser.add_argument(
        '--cache',
        default=str(ROOT / 'build' / 'demo'),
        help='Cache directory to write library.json, art/ and thumb/ into (default: build/demo)',
    )
    parser.add_argument(
        '--albums',
        type=int,
        default=len(ALBUMS_DATA),
        help=f'How many albums (default and minimum {len(ALBUMS_DATA)}); more are generated, '
             'by generated artists, for measuring big libraries',
    )
    parser.add_argument(
        '--playlists',
        type=int,
        default=len(PLAYLISTS_DATA) + 1,
        help=f'How many playlists, Favourite Songs counted (default and minimum '
             f'{len(PLAYLISTS_DATA) + 1}); more are generated, at the top level',
    )
    parser.add_argument(
        '--tracks',
        type=int,
        help='How many songs in all (default: 8 to 16 an album); the generated albums are '
             'sized to reach it',
    )
    parser.add_argument(
        '--videos',
        type=int,
        default=len(VIDEOS_DATA),
        help=f'How many music videos (default and minimum {len(VIDEOS_DATA)}); more are '
             'generated, for scrolling Music Videos at size',
    )
    parser.add_argument(
        '--long-playlist',
        type=int,
        metavar='N',
        help=f'Add a playlist of N songs ({LONG_PLAYLIST_ID}), for scrolling a playlist at size',
    )
    args = parser.parse_args()
    if args.videos < len(VIDEOS_DATA):
        parser.error(f'--videos must be at least {len(VIDEOS_DATA)}')
    if args.long_playlist is not None and args.long_playlist < 1:
        parser.error('--long-playlist must be at least 1')
    if args.albums < len(ALBUMS_DATA):
        parser.error(f'--albums must be at least {len(ALBUMS_DATA)}')
    if args.playlists < len(PLAYLISTS_DATA) + 1:
        parser.error(f'--playlists must be at least {len(PLAYLISTS_DATA) + 1}')
    if args.tracks is not None and args.albums == len(ALBUMS_DATA):
        parser.error('--tracks needs --albums above the hand-written ones')
    return args


def main():
    args = parse_args()
    out_dir = os.path.abspath(args.cache)
    try:
        build_demo_library(out_dir, album_count=args.albums, playlist_count=args.playlists,
                           track_count=args.tracks, video_count=args.videos,
                           long_playlist=args.long_playlist)
    except ValueError as error:
        sys.exit(f'demo_library: {error}')
    # Last: the record of what made it, which the harness and demo.sh compare (demo_stamp.py).
    defaults = {'albums': len(ALBUMS_DATA), 'playlists': len(PLAYLISTS_DATA) + 1, 'tracks': None,
                'videos': len(VIDEOS_DATA), 'long-playlist': None}
    given = {'albums': args.albums, 'playlists': args.playlists, 'tracks': args.tracks,
             'videos': args.videos, 'long-playlist': args.long_playlist}
    demo_stamp.write(out_dir, {key: value for key, value in given.items()
                               if value != defaults[key]})


if __name__ == '__main__':
    main()
