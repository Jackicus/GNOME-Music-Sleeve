# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's wide artwork as the app's headers and banners: an artist's, a
curator's, and New's hero row.

An artwork URL template cut with a crop code (banner_template(), wide_artwork()), or kept
whole when Apple composed it with an effect (template_effect()); artist_banner(),
curator_banner(), and featured_extras() for the banners of New's hero row. README.md has
how Apple makes each. The standard library only.
"""

import re

from .normalize import format_color


# An artist's wide header, as music.apple.com makes it (src/backend/README.md, "An artist's
# banner"): the editorial background where Apple has one, cut with its own crop code, else
# the artist's hero portrait cut with the crop Apple recommends for a wide header; else none.
BANNER_EDITORIAL = 'centeredFullscreenBackground'
BANNER_EDITORIAL_CROP = 'sr'
BANNER_HERO_CROP = 'vf'
# The size and crop part of an artwork URL template ("{w}x{h}bb.jpg", "{w}x{h}{c}.{f}").
_TEMPLATE_TAIL = re.compile(r'\{w\}x\{h\}(?:\{c\}|[a-z]{2})?\.(?:\{f\}|[A-Za-z]+)$')
# The size and effect part of a template Apple composes (README.md, "New's banners"): an
# effect code, upper case, then the format and maybe a query ("{w}x{h}SH.FPESS04.jpg?l=en-GB",
# an Essentials playlist's banner, its source picture placed on a colour beside a word).
_EFFECT_TAIL = re.compile(r'\{w\}x\{h\}([A-Z]{2,4}\.[A-Z0-9]{2,16})\.[A-Za-z]+(?:\?[^/#]*)?$')


def template_effect(url):
    """The effect code of an https artwork template Apple composes ("SH.FPESS04"), or None
    for any other URL."""
    if not isinstance(url, str) or not url.startswith('https://'):
        return None
    tail = _EFFECT_TAIL.search(url)
    return tail.group(1) if tail is not None else None


def banner_template(url, crop):
    """An artwork URL template cut with `crop` (Apple's crop code: `vf`, `sr`), its size left
    as {w}x{h} for the app to fill: "…/{w}x{h}bb.jpg" is "…/{w}x{h}vf.jpg". A template with
    an effect (template_effect: Apple's composite of its source, made for that shape) is kept
    as it is, query and all: a crop of its source would cut the picture. None for a URL that
    is not an https template."""
    if not isinstance(url, str) or not url.startswith('https://'):
        return None
    if template_effect(url) is not None:
        return url
    tail = _TEMPLATE_TAIL.search(url)
    if tail is None:
        return None
    return f'{url[:tail.start()]}{{w}}x{{h}}{crop}.jpg'


def wide_artwork(artwork, crop):
    """An Apple artwork dict ({url, width, height, bgColor}) as a wide image to fetch, {url,
    crop, width, height, color}: `url` its template cut with `crop` (banner_template), {w}x{h}
    left to fill, and `crop` that crop, or the template's effect code when it has one (it is
    asked at its source's shape, as an `sr` cut is: remote.banner_aspect); `width` and
    `height` the source's pixels; `color` its background colour (#rrggbb) or None. None
    without an https template and a size."""
    if not isinstance(artwork, dict):
        return None
    url = banner_template(artwork.get('url'), crop)
    width, height = artwork.get('width'), artwork.get('height')
    if (url is None or not isinstance(width, int) or not isinstance(height, int)
            or width <= 0 or height <= 0):
        return None
    color = artwork.get('bgColor')
    return {'url': url, 'crop': template_effect(url) or crop, 'width': width,
            'height': height, 'color': format_color(color) if isinstance(color, str) else None}


def artist_banner(attrs):
    """An artist's wide header from its attributes (`editorialArtwork` and `hero` extended),
    as {url, crop, width, height, color}, or None: `url` the template cut with the crop
    (banner_template), {w}x{h} left to fill; `width` and `height` the source's pixels (no
    bigger is worth asking for; an `sr` cut keeps the source's shape, a `vf` one is cut to
    whatever shape is asked); `color` Apple's background colour for it (#rrggbb) or None.

    The editorial background (BANNER_EDITORIAL) when Apple has one, else the artwork of the
    first hero entry's first content when its `recommendedCropCodes` list BANNER_HERO_CROP
    (some entries have no content), else None: the page keeps the round portrait."""
    attrs = attrs if isinstance(attrs, dict) else {}
    banner = wide_artwork
    editorial = attrs.get('editorialArtwork')
    if isinstance(editorial, dict):
        found = banner(editorial.get(BANNER_EDITORIAL), BANNER_EDITORIAL_CROP)
        if found is not None:
            return found
    hero = attrs.get('hero')
    first = hero[0] if isinstance(hero, list) and hero and isinstance(hero[0], dict) else {}
    content = first.get('content')
    entry = content[0] if isinstance(content, list) and content else None
    artwork = entry.get('artwork') if isinstance(entry, dict) else None
    crops = artwork.get('recommendedCropCodes') if isinstance(artwork, dict) else None
    if isinstance(crops, list) and BANNER_HERO_CROP in crops:
        return banner(artwork, BANNER_HERO_CROP)
    return None


# A curator's banner (README.md, "A radio show's banner"): the first of these its
# editorialArtwork has, cut at its source's shape.
CURATOR_BANNER_KEYS = ('bannerUber', 'subscriptionCover', 'subscriptionHero')
CURATOR_BANNER_CROP = 'sr'


def curator_banner(attrs):
    """A curator's wide header from its attributes (`editorialArtwork` extended), as
    wide_artwork() makes it ({url, crop, width, height, color}, {w}x{h} left to fill): the
    first of CURATOR_BANNER_KEYS it has with an https template and a size, whatever the
    curator's kind; else None (the page keeps its plain title)."""
    editorial = attrs.get('editorialArtwork') if isinstance(attrs, dict) else None
    if not isinstance(editorial, dict):
        return None
    for key in CURATOR_BANNER_KEYS:
        found = wide_artwork(editorial.get(key), CURATOR_BANNER_CROP)
        if found is not None:
            return found
    return None


# A banner's artwork (README.md, "The editorial groupings"): the hero row's wide children
# (320) carry an editorial artwork of their own, the others (317, 383) show their content's;
# the first of these cuts either has is the banner, cut at its source's shape.
BANNER_ARTWORK_KEYS = ('subscriptionHero', 'superHeroWide')
BANNER_ARTWORK_CROP = 'sr'
# The kind of item each resource type a banner holds is (_shelf_item's), the key
# featured_extras answers by.
_RESOURCE_KINDS = {'albums': 'album', 'playlists': 'playlist', 'artists': 'artist',
                   'stations': 'station', 'songs': 'song', 'music-videos': 'video',
                   'apple-curators': 'category'}


def featured_extras(element):
    """What the hero row's banners show beyond their item, by the (kind, id) of the item each
    holds: `badge`, the child's `designBadge` ("NEW ALBUM": Apple's words, in the account's
    language), `banner`, a wide artwork (the child's own editorialArtwork, else its
    content's: the first of BANNER_ARTWORK_KEYS, as wide_artwork() makes it), and
    `tagline`, the content's short editorial line (`plainEditorialNotes`' `tagline`, else
    its `short`; else the child's). Each key only where Apple gives it."""
    extras = {}
    children = ((element.get('relationships') or {}).get('children') or {}).get('data') or []
    for child in children:
        if not isinstance(child, dict):
            continue
        child_attrs = child.get('attributes') or {}
        contents = ((child.get('relationships') or {}).get('contents') or {}).get('data') or []
        for content in contents:
            kind = _RESOURCE_KINDS.get(content.get('type')) if isinstance(content, dict) else None
            if kind is None:
                continue
            attrs = content.get('attributes') or {}
            found = {}
            badge = ' '.join(str(child_attrs.get('designBadge') or '').split())
            if badge:
                found['badge'] = badge
            banner = (_editorial_banner(child_attrs.get('editorialArtwork'))
                      or _editorial_banner(attrs.get('editorialArtwork')))
            if banner is not None:
                found['banner'] = banner
            tagline = (_tagline(attrs.get('plainEditorialNotes'))
                       or _tagline(child_attrs.get('plainEditorialNotes')))
            if tagline:
                found['tagline'] = tagline
            extras.setdefault((kind, str(content.get('id') or '')), found)
    return extras


def _editorial_banner(editorial):
    """The first of BANNER_ARTWORK_KEYS an editorialArtwork has, as wide_artwork() makes it,
    or None."""
    if not isinstance(editorial, dict):
        return None
    for key in BANNER_ARTWORK_KEYS:
        found = wide_artwork(editorial.get(key), BANNER_ARTWORK_CROP)
        if found is not None:
            return found
    return None


def _tagline(notes):
    if not isinstance(notes, dict):
        return ''
    return ' '.join(str(notes.get('tagline') or notes.get('short') or '').split())
