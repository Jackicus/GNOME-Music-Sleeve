# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""src/backend/bridge.js, run under gjs against the fake page in tests/bridge_harness.js.

bridge.js runs in music.apple.com, where no test can reach it; gjs (GNOME's JavaScript, on every
GNOME system) runs it unchanged once `window` is the global object. Each test names a scenario,
an async JavaScript function of {bridge, mk, posted, page, audios, failAudio}: `bridge` the
injected window.__appleMusicLibrary, `mk` the fake MusicKit instance (its `calls`, `listeners`,
`fire()`), `posted` the events the bridge sent through the binding, `page.elements` what
document's selectors find, `audios` every Audio element the page made (each `fire()`s 'ended' or
'error') and `failAudio(error)` what their play() rejects with. All scenarios run in one gjs
process, each on a fresh page, and the test gets what its scenario returned. Skipped without
gjs.
"""

import functools
import json
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from tests import ROOT

from applemusic.engine import lyrics_answer
from applemusic.lyrics import FORMAT

HARNESS = pathlib.Path(__file__).with_name('bridge_harness.js')
BRIDGE = ROOT / 'src' / 'backend' / 'bridge.js'
GJS = shutil.which('gjs')

EVENTS = ('authorizationStatusDidChange', 'playbackStateDidChange', 'nowPlayingItemDidChange',
          'playbackTimeDidChange', 'playbackDurationDidChange', 'queueItemsDidChange',
          'queuePositionDidChange', 'shuffleModeDidChange', 'repeatModeDidChange',
          'playbackVolumeDidChange', 'mediaPlaybackError', 'autoplayEnabledDidChange',
          'capabilitiesChanged')

# What a state or item event says MusicKit allows when the instance has no capabilities.
ALLOWED = {'canSeek': True, 'canPause': True, 'canSkipToNextItem': True,
           'canSkipToPreviousItem': True}

# Apple's TTML lyrics, as the catalog's /lyrics answers carry them (invented words): two
# stanzas, entities, word-timed spans, a <br>, CDATA, the four time formats, a blank line.
TTML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:itunes="http://music.apple.com/lyric-ttml-internal"'
    ' xml:lang="en"><head><metadata/></head><body dur="1:02.500">'
    '<div begin="0.5s" end="20s">'
    '<p begin="00:00.500" end="00:04.250">Rock &amp; Roll &#8217;til dawn</p>'
    '<p begin="4.5s" end="8s"><span begin="4.5s">Harbour</span> <span begin="5s">lights</span>'
    '</p></div>'
    '<div begin="20s" end="1:02.5">'
    '<p begin="0:20.000" end="0:25.100">Out on the<br/>water</p>'
    '<p begin="1:00:01.5" end="1:00:03"><![CDATA[Fish & chips <tonight>]]></p>'
    '<p begin="30s"> </p></div></body></tt>'
)

# The same song's syllable-lyrics answer with its transliterations, as music.apple.com asks
# for it (extend=ttmlLocalizations; invented words): the head's <text for="…"> name the
# lines by their itunes:key, word-timed spans and a background vocal (ttm:role="x-bg", its
# parentheses inside it, as Apple writes them) among them; one line has none, one's is the
# line itself, a <text> names no line. The translations are the same shape. Every line is
# v1's: no duet.
TTML_LOCALIZED = (
    '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:itunes="http://music.apple.com/lyric-ttml-internal"'
    ' xmlns:ttm="http://www.w3.org/ns/ttml#metadata" itunes:timing="Word" xml:lang="ja">'
    '<head><metadata><ttm:agent type="person" xml:id="v1"/>'
    '<iTunesMetadata xmlns="http://music.apple.com/lyric-ttml-internal">'
    '<translations><translation type="subtitle" xml:lang="en-US">'
    '<text for="L1">Fog on the sea <span ttm:role="x-bg">(the sea)</span></text>'
    '<text for="L2">Oh oh</text><text for="L3">Tide</text></translation></translations>'
    '<transliterations><transliteration xml:lang="ja-Latn">'
    '<text for="L1"><span xmlns="http://www.w3.org/ns/ttml" begin="1" end="2">Kiri</span> '
    '<span xmlns="http://www.w3.org/ns/ttml" begin="2" end="3">no</span> '
    '<span xmlns="http://www.w3.org/ns/ttml" begin="3" end="4">umi</span> '
    '<span xmlns="http://www.w3.org/ns/ttml" ttm:role="x-bg">(<span>umi</span>)</span></text>'
    '<text for="L2">Oh oh</text>'
    '<text for="L9">Nobody&#8217;s</text>'
    '</transliteration><transliteration xml:lang="ja-Kana"><text for="L1">きり</text>'
    '</transliteration></transliterations></iTunesMetadata></metadata></head>'
    '<body><div begin="1" end="9" ttm:agent="v1">'
    '<p begin="1" end="4" itunes:key="L1" ttm:agent="v1"><span begin="1" end="3">霧の</span>'
    '<span begin="3" end="4">海</span> <span ttm:role="x-bg">(海)</span></p>'
    '<p begin="5" end="7" itunes:key="L2">Oh oh</p>'
    '<p begin="7" end="9" itunes:key="L3">潮</p>'
    '</div></body></tt>'
)

# A word-timed duet as syllable-lyrics answers it (invented words, the structure of Apple's):
# the head declares the singers (two people and a group); a <p> names its singer, or its
# <div> does. Within a line, whitespace between the timed <span>s parts the words and
# adjacent spans are syllables of one; the background vocals are a <span ttm:role="x-bg">
# of timed spans of their own after the main vocals, their parentheses in the first and the
# last. The transliteration is timed the same way, x-bg and all (with a space inside a span
# and two between spans); the translation's background is an untimed x-bg span. One line is
# all background, one has a <br>, one has words outside any span (no words then), and the
# first line's translation is the line itself.
TTML_DUET = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:itunes="http://music.apple.com/lyric-ttml-internal"'
    ' xmlns:ttm="http://www.w3.org/ns/ttml#metadata" itunes:timing="Word" xml:lang="en">'
    '<head><metadata><ttm:agent type="person" xml:id="v1"/>'
    '<ttm:agent type="person" xml:id="v2"/><ttm:agent type="group" xml:id="v3"/>'
    '<iTunesMetadata xmlns="http://music.apple.com/lyric-ttml-internal" leadingSilence="0">'
    '<translations><translation type="subtitle" xml:lang="en-GB">'
    '<text for="L1">Grey morning, harbour light</text>'
    '<text for="L2">Counting the waves <span ttm:role="x-bg">(counting)</span></text>'
    '</translation></translations>'
    '<transliterations><transliteration xml:lang="ja-Latn">'
    '<text for="L2"><span begin="10.000" end="10.400">Na</span>'
    '<span begin="10.400" end="10.800">mi</span> <span begin="10.800" end="11.200">o</span>  '
    '<span begin="11.200" end="12.000">ka zo e te</span> <span ttm:role="x-bg">'
    '<span begin="12.200" end="12.600">(ka</span><span begin="12.600" end="13.000">zo e te)'
    '</span></span></text>'
    '</transliteration></transliterations></iTunesMetadata></metadata></head>'
    '<body dur="24.000"><div begin="1.000" end="4.000" itunes:songPart="Verse">'
    '<p begin="1.000" end="4.000" itunes:key="L1" ttm:agent="v1">'
    '<span begin="1.000" end="1.500">Grey</span> <span begin="1.500" end="2.000">morn</span>'
    '<span begin="2.000" end="2.400">ing,</span> <span begin="2.400" end="3.000">har</span>'
    '<span begin="3.000" end="3.300">bour</span> <span begin="3.300" end="4.000">light</span>'
    '</p></div>'
    '<div begin="10.000" end="13.000" itunes:songPart="Verse" ttm:agent="v2">'
    '<p begin="10.000" end="13.000" itunes:key="L2">'
    '<span begin="10.000" end="10.800">波の</span>'
    '<span begin="10.800" end="12.000">数え</span> <span ttm:role="x-bg">'
    '<span begin="12.200" end="12.600">(数</span>'
    '<span begin="12.600" end="13.000">え)</span></span></p></div>'
    '<div begin="14.000" end="24.000" itunes:songPart="Chorus">'
    '<p begin="14.000" end="17.000" itunes:key="L3" ttm:agent="v3">'
    '<span begin="14.000" end="15.000">All</span> <span begin="15.000" end="16.000">to</span>'
    '<br/><span begin="16.000" end="17.000">gether</span></p>'
    '<p begin="18.000" end="20.000" itunes:key="L4" ttm:agent="v1"><span ttm:role="x-bg">'
    '<span begin="18.000" end="19.000">(Oh</span> <span begin="19.000" end="20.000">oh)</span>'
    '</span></p>'
    '<p begin="21.000" end="24.000" itunes:key="L5" ttm:agent="v2">Ah '
    '<span begin="21.000" end="24.000">yes</span></p>'
    '</div></body></tt>'
)

# A song as MusicKit's queue and nowPlayingItem hold it (a MediaItem: id, type, attributes).
SONG = """{
    id: 'i.song1', type: 'library-songs',
    attributes: {
        name: 'Harbour Lights', artistName: 'The Invented Band', albumName: 'Tidewater',
        durationInMillis: 216000, trackNumber: 3, discNumber: 1, contentRating: 'explicit',
        artwork: {url: 'https://example.invalid/{w}x{h}bb.jpg'},
        playParams: {id: 'i.song1', kind: 'song', catalogId: '1000000001'},
    },
}"""


def scenario(js):
    """Run the test with what `js` returned: the body of an async function of {bridge, mk,
    posted, page, audios, failAudio}, run on a fresh page. A scenario that throws fails the
    test."""
    def decorate(test):
        @functools.wraps(test)
        def run(self):
            outcome = self.outcomes.get(test.__name__)
            if outcome is None:
                self.fail(f'{test.__name__}: no outcome')
            if 'error' in outcome:
                self.fail(f'{test.__name__}: the scenario threw: {outcome["error"]}')
            return test(self, outcome['value'])
        run.scenario = textwrap.dedent(js)
        return run
    return decorate


def run_scenarios(scenarios):
    """{name: outcome} for each scenario, from one gjs run of the harness, the bridge and them."""
    parts = [HARNESS.read_text(encoding='utf-8'),
             f'const BRIDGE = {json.dumps(BRIDGE.read_text(encoding="utf-8"))};',
             f'const SONG = {SONG};',
             f'const TTML = {json.dumps(TTML)};',
             f'const TTML_LOCALIZED = {json.dumps(TTML_LOCALIZED)};',
             f'const TTML_DUET = {json.dumps(TTML_DUET)};',
             'const SCENARIOS = {']
    for name, body in scenarios.items():
        parts.append(f'{json.dumps(name)}: async ({{bridge, mk, posted, page, audios, failAudio}})'
                     f' => {{\n{body}\n}},')
    parts += ['};', 'run();']
    with tempfile.NamedTemporaryFile('w', suffix='.js', encoding='utf-8') as script:
        script.write('\n'.join(parts))
        script.flush()
        done = subprocess.run([GJS, script.name], capture_output=True, text=True, timeout=60)
    if done.returncode != 0 or not done.stdout.strip():
        raise AssertionError(f'gjs failed ({done.returncode}): {done.stderr.strip()}')
    return json.loads(done.stdout.strip().splitlines()[-1])


class BridgeTest(unittest.TestCase):
    outcomes = {}

    @classmethod
    def setUpClass(cls):
        if GJS is None:
            raise unittest.SkipTest('gjs is not installed')
        scenarios = {name: getattr(cls, name).scenario for name in dir(cls)
                     if name.startswith('test_') and hasattr(getattr(cls, name), 'scenario')}
        cls.outcomes = run_scenarios(scenarios)

    # -- status and events -----------------------------------------------------------------

    @scenario("""
        const signedOut = bridge.status();
        mk.isAuthorized = true;
        const signedIn = bridge.status();
        delete window.MusicKit;
        return {signedOut, signedIn, missing: bridge.status()};
    """)
    def test_status(self, value):
        self.assertEqual(value['signedOut'], {'ready': True, 'engine': True, 'authorized': False,
                                              'storefront': 'gb', 'bitrate': 256})
        self.assertTrue(value['signedIn']['authorized'])
        self.assertEqual(value['missing'], {'ready': False, 'engine': True, 'authorized': False,
                                            'storefront': 'us', 'bitrate': 256})

    @scenario("""
        const granted = await bridge.drm();
        const asked = page.keyRequests.map(request => request[0]);
        const configs = page.keyRequests[0][1];
        page.keySystems = [];   // Chromium without its Widevine module
        const refused = await bridge.drm();
        delete navigator.requestMediaKeySystemAccess;   // no Encrypted Media Extensions
        return {granted, asked, configs, refused, none: await bridge.drm()};
    """)
    def test_drm_asks_for_widevine(self, value):
        self.assertEqual(value['granted'], {'widevine': True})
        self.assertEqual(value['asked'], ['com.widevine.alpha'])
        self.assertEqual(value['configs'][0]['audioCapabilities'][0]['contentType'],
                         'audio/mp4; codecs="mp4a.40.2"')
        self.assertEqual(value['refused'], {
            'widevine': False, 'error': 'Unsupported keySystem or supportedConfigurations.'})
        self.assertEqual(value['none'], {'widevine': False,
                                         'error': 'no Encrypted Media Extensions'})

    @scenario("""
        const first = bridge.subscribe();
        const second = bridge.subscribe();
        return {first, second, listeners: mk.listenerCounts()};
    """)
    def test_subscribe_attaches_once(self, value):
        self.assertTrue(value['first']['attached'])
        self.assertFalse(value['second']['attached'])
        self.assertEqual(sorted(value['first']['events']), sorted(EVENTS))
        self.assertEqual(value['listeners'], dict.fromkeys(EVENTS, 1))

    @scenario("""
        bridge.subscribe();
        inject('v2');   // a changed bridge: client.load_bridge's new version
        const newer = window.__appleMusicLibrary;
        const subscribed = newer.subscribe();
        inject('v2');   // the same one again: nothing happens
        return {replaced: newer !== bridge, kept: window.__appleMusicLibrary === newer,
                version: newer.__version, subscribed, listeners: mk.listenerCounts()};
    """)
    def test_a_new_bridge_replaces_the_old_ones_listeners(self, value):
        self.assertTrue(value['replaced'])
        self.assertTrue(value['kept'])
        self.assertEqual(value['version'], 'v2')
        self.assertTrue(value['subscribed']['attached'])
        self.assertEqual(value['listeners'], dict.fromkeys(EVENTS, 1))

    @scenario("""
        bridge.subscribe();
        const answer = bridge.unsubscribe();
        return {answer, listeners: mk.listenerCounts()};
    """)
    def test_unsubscribe(self, value):
        self.assertEqual(value, {'answer': {'subscribed': False}, 'listeners': {}})

    @scenario("""
        bridge.subscribe();
        mk.isAuthorized = true;
        mk.fire('authorizationStatusDidChange', {authorizationStatus: 3});
        mk.currentPlaybackTime = 3;
        mk.currentPlaybackDuration = 30;
        mk.playbackState = 3;
        mk.fire('playbackStateDidChange', {state: 2});
        mk.fire('playbackStateDidChange', {});   // no state on the event: the instance's
        mk.nowPlayingItem = SONG;
        mk.nowPlayingItemIndex = 1;
        mk.fire('nowPlayingItemDidChange', {});
        mk.fire('playbackTimeDidChange', {});
        mk.fire('playbackDurationDidChange', {});
        mk.queue = {items: [SONG], position: 0};
        mk.fire('queueItemsDidChange', {});
        mk.fire('queuePositionDidChange', {position: 1, oldPosition: 0});
        mk.shuffleMode = 1;
        mk.fire('shuffleModeDidChange', {});
        mk.repeatMode = 2;
        mk.fire('repeatModeDidChange', {});
        mk.volume = 0.5;
        mk.fire('playbackVolumeDidChange', {});
        return posted;
    """)
    def test_event_payloads(self, value):
        events = [(event['name'], event['data']) for event in value]
        track = events[3][1]['track']
        self.assertEqual(events, [
            ('authorizationStatusDidChange', {'authorized': True, 'status': 3}),
            ('playbackStateDidChange', {'state': 'playing', 'position': 3, 'duration': 30,
                                        'capabilities': ALLOWED}),
            ('playbackStateDidChange', {'state': 'paused', 'position': 3, 'duration': 30,
                                        'capabilities': ALLOWED}),
            ('nowPlayingItemDidChange', {'track': track, 'index': 1,
                                         'capabilities': ALLOWED}),
            ('playbackTimeDidChange', {'position': 3, 'duration': 30}),
            ('playbackDurationDidChange', {'duration': 30}),
            ('queueItemsDidChange', {'index': 0, 'items': [dict(track, index=0)],
                                     'editable': True, 'canAutoplay': True,
                                     'autoplay': False}),
            ('queuePositionDidChange', {'index': 1, 'oldIndex': 0}),
            ('shuffleModeDidChange', {'shuffle': 'on'}),
            ('repeatModeDidChange', {'repeat': 'all'}),
            ('playbackVolumeDidChange', {'volume': 0.5}),
        ])
        self.assertEqual(track, {
            'id': 'i.song1', 'type': 'library-songs', 'catalogId': '1000000001',
            'title': 'Harbour Lights',
            'artist': 'The Invented Band', 'album': 'Tidewater', 'trackNumber': 3,
            'discNumber': 1, 'durationMs': 216000, 'durationLabel': '3:36', 'explicit': True,
            'artUrl': 'https://example.invalid/256x256bb.jpg', 'index': 1})

    @scenario("""
        bridge.subscribe();
        mk.fire('mediaPlaybackError', {errorCode: 'CONTENT_UNAVAILABLE', name: 'MKError',
                                       message: 'Content unavailable'});
        mk.fire('mediaPlaybackError', {name: 'NotAllowedError', description: 'No gesture'});
        mk.fire('mediaPlaybackError', 'Playback failed');
        mk.fire('mediaPlaybackError', undefined);
        return posted.map(event => event.data);
    """)
    def test_playback_errors_carry_musickits_code(self, value):
        self.assertEqual(value, [
            {'code': 'CONTENT_UNAVAILABLE', 'message': 'Content unavailable'},
            {'code': 'NotAllowedError', 'message': 'No gesture'},
            {'code': '', 'message': 'Playback failed'},
            {'code': '', 'message': 'unknown error'}])

    @scenario("""
        mk.failures.setQueue = {errorCode: 'CONTENT_UNAVAILABLE', message: 'Content unavailable'};
        const queued = await bridge.play('album', '1000000002');
        delete mk.failures.setQueue;
        mk.failures.play = new Error('The play() request was interrupted');
        const played = await bridge.play('album', '1000000002');
        delete mk.failures.play;
        return {queued, played, fine: await bridge.play('album', '1000000002')};
    """)
    def test_a_refused_play_answers_its_code(self, value):
        self.assertEqual(value, {
            'queued': {'error': 'Content unavailable', 'code': 'CONTENT_UNAVAILABLE'},
            'played': {'error': 'The play() request was interrupted', 'code': 'Error'},
            'fine': {'ok': True}})

    @scenario("""
        bridge.subscribe();
        for (const state of [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 'ended', 99])
            mk.fire('playbackStateDidChange', {state});
        return posted.map(event => event.data.state);
    """)
    def test_playback_states_are_named(self, value):
        self.assertEqual(value, ['none', 'loading', 'playing', 'paused', 'stopped', 'ended',
                                 'seeking', 'waiting', 'stalled', 'completed', 'ended', 'none'])

    @scenario("""
        bridge.subscribe();
        delete window.__amEvent;   // the binding gone with the connection
        mk.fire('playbackStateDidChange', {state: 2});
        return posted.length;
    """)
    def test_no_binding_posts_nothing(self, value):
        self.assertEqual(value, 0)

    # -- the account -----------------------------------------------------------------------

    @scenario("""
        const names = {};
        page.elements = {'.account-menu .user__name': [{textContent: '  Jo \\n Bloggs '}]};
        names.menu = bridge.accountName();
        // Signed out, or the moment after sign-in: the footer's sign-in button, in any
        // language, and the menu's name is not trusted yet.
        page.elements['button.signin'] = [{textContent: 'Anmelden'}];
        names.signingIn = bridge.accountName();
        // Broader elements are never read, whatever they hold.
        page.elements = {'.auth-content span': [{textContent: 'Se connecter'}],
                         'nav footer button[aria-haspopup] span': [{textContent: 'Jo'}]};
        names.footer = bridge.accountName();
        page.elements = {'.user__name': [{textContent: 'x'.repeat(65)}, {textContent: ''}],
                         '.account-name': [{textContent: 'Sam'}]};
        names.fallback = bridge.accountName();
        page.elements = {};
        names.none = bridge.accountName();
        return names;
    """)
    def test_account_name(self, value):
        self.assertEqual(value, {'menu': 'Jo Bloggs', 'signingIn': None, 'footer': None,
                                 'fallback': 'Sam', 'none': None})

    @scenario("""
        const done = await bridge.signout();
        const calls = mk.calls.map(call => call[0]);
        mk.failures.unauthorize = new Error('Network error');
        const refused = await bridge.signout();
        delete window.MusicKit;
        return {done, calls, refused, missing: await bridge.signout()};
    """)
    def test_signout_revokes_the_session(self, value):
        self.assertEqual(value['done'], {'ok': True})
        self.assertEqual(value['calls'], ['unauthorize'])
        self.assertEqual(value['refused'], {'error': 'Network error'})
        self.assertEqual(value['missing'], {'error': 'MusicKit not initialized'})

    # -- playback --------------------------------------------------------------------------

    @scenario("""
        await bridge.play('album', 'l.alb1', {startWith: 2});
        await bridge.play('playlist', 'p.pl1');
        await bridge.play('station', 'ra.1');
        await bridge.play('musicVideo', '1000000009');
        mk.apiAnswers['/v1/catalog/gb/artists/42/view/top-songs'] = {data: [{id: '1'}, {id: '2'}]};
        await bridge.play('artist', '42');
        await bridge.play('artist', '43');   // no top songs: the artist's station
        await bridge.play('songs', 'i.a,i.b,i.c', {startWith: 1});   // a stand-in album
        await bridge.playNext('songs', 'i.d,i.e');
        await bridge.playLater('album', 'l.alb2');
        await bridge.playNext('song', '1000000001');
        return mk.calls.filter(call => ['setQueue', 'playNext', 'playLater'].includes(call[0]))
            .map(call => [call[0], call[1]]);
    """)
    def test_play_queues_each_kind(self, value):
        self.assertEqual(value, [
            ['setQueue', {'startWith': 2, 'startPlaying': True, 'album': 'l.alb1'}],
            ['setQueue', {'startWith': 0, 'startPlaying': True, 'playlist': 'p.pl1'}],
            ['setQueue', {'startWith': 0, 'startPlaying': True, 'station': 'ra.1'}],
            ['setQueue', {'startWith': 0, 'startPlaying': True, 'musicVideo': '1000000009'}],
            ['setQueue', {'startWith': 0, 'startPlaying': True, 'songs': ['1', '2']}],
            ['setQueue', {'startWith': 0, 'startPlaying': True, 'station': '43'}],
            ['setQueue', {'startWith': 1, 'startPlaying': True, 'songs': ['i.a', 'i.b', 'i.c']}],
            ['playNext', {'songs': ['i.d', 'i.e']}],
            ['playLater', {'album': 'l.alb2'}],
            ['playNext', {'song': '1000000001'}],
        ])

    @scenario("""
        const modes = [];
        await bridge.play('album', 'l.alb1', {shuffle: true});
        modes.push(mk.shuffleMode);
        await bridge.play('album', 'l.alb1', {startWith: 3});   // a track row: as it is
        modes.push(mk.shuffleMode);
        await bridge.play('album', 'l.alb1', {startWith: 3, shuffle: null});
        modes.push(mk.shuffleMode);
        await bridge.play('album', 'l.alb1', {shuffle: false});   // Play: in order
        modes.push(mk.shuffleMode);
        await bridge.play('album', 'l.alb1', {startWith: 1});
        modes.push(mk.shuffleMode);
        delete window.MusicKit.PlayerShuffleMode;   // MusicKit's numbers without the names
        await bridge.play('album', 'l.alb1', {shuffle: true});
        modes.push(mk.shuffleMode);
        return modes;
    """)
    def test_play_turns_shuffle_on_off_or_leaves_it(self, value):
        self.assertEqual(value, [1, 1, 1, 0, 0, 1])

    @scenario("""
        // MusicKit's queue for the album holds the row's song one place later than the
        // library's list has it (it left out an entry before it).
        mk.setQueue = async function (options) {
            this.calls.push(['setQueue', options]);
            this.queue = {position: options.startWith, items: [
                {id: 'i.one'}, {id: 'i.three'}, {id: 'i.four',
                 attributes: {playParams: {id: 'i.four', catalogId: '104'}}}]};
        };
        const moved = await bridge.play('album', 'l.alb1', {startWith: 1, startId: 'i.four'});
        const kept = await bridge.play('album', 'l.alb1', {startWith: 1, startId: 'i.three'});
        const catalog = await bridge.play('album', 'l.alb1', {startWith: 0, startId: '104'});
        const missing = await bridge.play('album', 'l.alb1', {startWith: 1, startId: 'i.gone'});
        const plain = await bridge.play('album', 'l.alb1', {startWith: 1});
        return {answers: [moved, kept, catalog, missing, plain],
                changes: mk.calls.filter(call => call[0] === 'changeToMediaAtIndex')};
    """)
    def test_play_starts_at_the_rows_own_item(self, value):
        self.assertEqual(value['answers'], [
            {'ok': True, 'moved': {'from': 1, 'to': 2}},
            {'ok': True},
            {'ok': True, 'moved': {'from': 0, 'to': 2}},
            {'ok': True},   # not in the queue: where startWith put it
            {'ok': True},
        ])
        self.assertEqual(value['changes'], [['changeToMediaAtIndex', 2]] * 2)

    @scenario("""
        // MusicKit's queue for the session: the item where startWith says, or one later.
        mk.setQueue = async function (options) {
            this.calls.push(['setQueue', options]);
            this.queue = {position: options.startWith, items: [
                {id: 'i.one'}, {id: 'i.two'}, {id: 'i.three'}]};
        };
        mk.changeToMediaAtIndex = async function (index) {
            this.calls.push(['changeToMediaAtIndex', index]);
            this.queue.position = index;
        };
        const seeks = () => mk.calls.filter(call => call[0] === 'seekToTime');
        const out = {};
        // MusicKit began the item at 0: the bridge seeks.
        out.ignored = await bridge.play('songs', 'i.one,i.two,i.three',
                                        {startWith: 1, startId: 'i.two', startTime: 83});
        out.ignoredSeeks = seeks();
        out.queued = mk.calls.find(call => call[0] === 'setQueue')[1];
        // MusicKit took the start time: no seek.
        mk.calls = [];
        mk.play = async function () { this.calls.push(['play']); this.currentPlaybackTime = 83; };
        out.taken = await bridge.play('songs', 'i.one,i.two,i.three',
                                      {startWith: 1, startId: 'i.two', startTime: 83});
        out.takenSeeks = seeks();
        // The item moved: the start is still its.
        mk.calls = [];
        mk.currentPlaybackTime = 0;
        delete mk.play;
        out.moved = await bridge.play('album', 'l.alb1',
                                      {startWith: 0, startId: 'i.three', startTime: 40});
        out.movedSeeks = seeks();
        // Not in the queue: the item playing is another, started from the top.
        mk.calls = [];
        out.missing = await bridge.play('album', 'l.alb1',
                                        {startWith: 1, startId: 'i.gone', startTime: 40});
        out.missingSeeks = seeks();
        return out;
    """)
    def test_a_restored_session_starts_at_its_position(self, value):
        self.assertEqual(value['queued'], {'songs': ['i.one', 'i.two', 'i.three'],
                                           'startWith': 1, 'startPlaying': True,
                                           'startTime': 83})
        self.assertEqual(value['ignored'], {'ok': True, 'sought': True})
        self.assertEqual(value['ignoredSeeks'], [['seekToTime', 83]])
        self.assertEqual(value['taken'], {'ok': True})
        self.assertEqual(value['takenSeeks'], [])
        self.assertEqual(value['moved'], {'ok': True, 'moved': {'from': 0, 'to': 2},
                                          'sought': True})
        self.assertEqual(value['movedSeeks'], [['seekToTime', 40]])
        self.assertEqual(value['missing'], {'ok': True})
        self.assertEqual(value['missingSeeks'], [])

    @scenario("""
        mk.setQueue = async function (options) {
            this.calls.push(['setQueue', options]);
            this.queue = {position: options.startWith, items: [{id: 'i.one'}, {id: 'i.two'}]};
        };
        const names = () => mk.calls.map(call => call[0]);
        const out = {};
        // Loaded paused (Play Next before the first Play): queued, not played or moved.
        out.answer = await bridge.play('songs', 'i.one,i.two',
                                       {startWith: 1, startId: 'i.two', startTime: 83,
                                        paused: true});
        out.queued = mk.calls[0][1];
        out.loaded = names();
        await bridge.playNext('song', '1000000005');
        await bridge.control('pause');   // a pause before the first play keeps the start
        mk.calls = [];
        await bridge.control('play');    // the first play: there
        out.first = mk.calls;
        mk.calls = [];
        mk.isPlaying = true;
        await bridge.control('toggle');
        mk.isPlaying = false;
        await bridge.control('toggle');  // played once: the start is spent
        out.again = names();
        // A seek of the user's gives it up.
        await bridge.play('songs', 'i.one,i.two',
                          {startWith: 1, startId: 'i.two', startTime: 83, paused: true});
        await bridge.seek(10);
        mk.calls = [];
        await bridge.control('play');
        out.afterSeek = names();
        return out;
    """)
    def test_a_session_loaded_paused_starts_at_its_position_on_the_first_play(self, value):
        self.assertEqual(value['answer'], {'ok': True})
        self.assertEqual(value['queued'], {'songs': ['i.one', 'i.two'], 'startWith': 1,
                                           'startPlaying': False, 'startTime': 83})
        self.assertEqual(value['loaded'], ['setQueue'])
        self.assertEqual(value['first'], [['play'], ['seekToTime', 83]])
        self.assertEqual(value['again'], ['pause', 'play'])
        self.assertEqual(value['afterSeek'], ['play'])

    @scenario("""
        mk.nowPlayingItem = {id: 'i.video1', type: 'library-music-videos',
                             attributes: {name: 'Harbour Lights (Live)'}};
        const video = bridge.nowPlaying().track;
        mk.nowPlayingItem = {id: 'ra.1', type: 'stations', attributes: {name: 'Harbour Radio'}};
        const station = bridge.nowPlaying().track;
        mk.nowPlayingItem = {id: '1', attributes: {name: 'No type'}};
        return [video.type, station.type, bridge.nowPlaying().track.type];
    """)
    def test_a_track_carries_its_type(self, value):
        self.assertEqual(value, ['library-music-videos', 'stations', ''])

    @scenario("""
        mk.playbackState = 2;
        mk.isPlaying = true;
        mk.nowPlayingItem = SONG;
        mk.nowPlayingItemIndex = 0;
        mk.currentPlaybackTime = 12;
        mk.currentPlaybackDuration = 216;
        const playing = bridge.nowPlaying();
        mk.isPlaying = false;   // as while an item loads
        mk.playbackState = 1;
        const loading = bridge.nowPlaying().state;
        mk.playbackState = 5;
        const ended = bridge.nowPlaying().state;
        delete mk.playbackState;   // an instance without one: the coarse guess
        const coarse = [bridge.nowPlaying().state];
        mk.nowPlayingItem = null;
        coarse.push(bridge.nowPlaying().state);
        mk.isPlaying = true;
        coarse.push(bridge.nowPlaying().state);
        delete window.MusicKit;
        return {playing, loading, ended, coarse, none: bridge.nowPlaying()};
    """)
    def test_now_playing(self, value):
        self.assertEqual((value['loading'], value['ended']), ('loading', 'ended'))
        self.assertEqual(value['coarse'], ['paused', 'stopped', 'playing'])
        playing = value['playing']
        self.assertEqual((playing['state'], playing['track']['id'], playing['position'],
                          playing['duration'], playing['shuffle'], playing['repeat']),
                         ('playing', 'i.song1', 12, 216, 'off', 'none'))
        self.assertEqual(value['none'], {'state': 'stopped', 'track': None, 'position': 0,
                                         'duration': 0, 'shuffle': 'off', 'repeat': 'none',
                                         'volume': 1})

    @scenario("""
        bridge.subscribe();
        // A live station as MusicKit plays it (#343): one item, typed radioStation, live,
        // with no length of its own, and every capability false.
        const live = {id: 'ra.live01', type: 'radioStation', isLiveRadioStation: true,
                      attributes: {name: 'Harbour One', isLive: true, kind: 'streaming'}};
        mk.nowPlayingItem = live;
        mk.nowPlayingItemIndex = 0;
        mk.currentPlaybackTime = 112;
        mk.currentPlaybackDuration = 160;   // the stream's window
        mk.capabilities = {canSeek: false, canPause: false, canSkipToNextItem: false,
                           canSkipToPreviousItem: false, canEditPlaybackQueue: false};
        mk.fire('nowPlayingItemDidChange', {});
        mk.fire('capabilitiesChanged', {});
        const answer = bridge.nowPlaying();
        // Told by the item, not its duration: isLiveRadioStation alone, or the type and
        // isLive; a station that is not live, or a song, is not.
        const told = [
            {id: 'ra.a', type: 'radioStation', attributes: {isLive: true}},
            {id: 'ra.b', type: 'radioStation', attributes: {isLive: false}},
            {id: 'ra.c', type: 'stations', attributes: {isLive: false}},
            {id: 'i.d', type: 'song', attributes: {name: 'Song'}},
        ].map(item => {
            mk.queue = {items: [item], position: 0};
            return bridge.queue().items[0].isLive;
        });
        return {posted, answer, told};
    """)
    def test_a_live_station_is_live_and_allows_nothing(self, value):
        nothing = dict.fromkeys(ALLOWED, False)
        events = [(event['name'], event['data']) for event in value['posted']]
        item = events[0][1]
        self.assertEqual(item['capabilities'], nothing)
        self.assertEqual((item['track']['type'], item['track']['isLive'],
                          item['track']['durationMs'], item['track']['title']),
                         ('radioStation', True, 0, 'Harbour One'))
        self.assertEqual(events[1], ('capabilitiesChanged', {'capabilities': nothing}))
        answer = value['answer']
        self.assertEqual((answer['track']['isLive'], answer['position'], answer['duration'],
                          answer['capabilities']), (True, 112, 160, nothing))
        self.assertEqual(value['told'], [True, None, None, None])  # only when true

    # -- the queue: Up Next's edits and autoplay -------------------------------------------

    @scenario("""
        const song = id => ({id, type: 'song', attributes: {name: id}});
        mk.queue = new FakeQueue(mk, [song('i.a'), song('i.b'), song('i.c'), song('i.d')], 1, [3]);
        mk.autoplayEnabled = true;
        const flagged = bridge.queue();
        // The queue items out of step with the items: the autoplay MediaItems say instead.
        mk.queue._queueItems.push({item: song('i.e'), isAutoplay: false});
        Object.defineProperty(mk.queue, 'items', {value: mk.queue.items.slice(0, 4)});
        const byList = bridge.queue().items.map(track => !!track.autoplay);
        mk.capabilities = {canEditPlaybackQueue: false, canAutoplay: false};
        const station = bridge.queue();
        return {flagged, byList, station: [station.editable, station.canAutoplay]};
    """)
    def test_the_queue_says_what_autoplay_added_and_what_may_be_done(self, value):
        flagged = value['flagged']
        self.assertEqual([track.get('autoplay') for track in flagged['items']],
                         [None, None, None, True])  # only where true: other entries as before
        self.assertEqual((flagged['index'], flagged['editable'], flagged['canAutoplay'],
                          flagged['autoplay']), (1, True, True, True))
        self.assertEqual(value['byList'], [False, False, False, True])
        self.assertEqual(value['station'], [False, False])

    @scenario("""
        bridge.subscribe();
        const song = id => ({id, type: 'song', attributes: {name: id}});
        mk.queue = new FakeQueue(mk, [song('i.a'), song('i.b'), song('i.c'), song('i.d')], 1);
        const out = {};
        out.removed = bridge.queueRemove(2, 'i.c');
        out.after = mk.queue.items.map(item => item.id);
        out.current = bridge.queueRemove(1, 'i.b');
        out.stale = bridge.queueRemove(2, 'i.c');      // i.d is at 2 now
        out.missing = bridge.queueRemove(9, 'i.z');
        out.calls = mk.calls.filter(call => call[0].startsWith('queue.'));
        out.events = posted.filter(event => event.name === 'queueItemsDidChange')
            .map(event => event.data.items.map(track => track.id));
        // Without spliceQueueItems: the deprecated remove.
        mk.queue.spliceQueueItems = undefined;
        out.old = bridge.queueRemove(2, 'i.d');
        out.oldCall = mk.calls[mk.calls.length - 1];
        mk.capabilities = {canEditPlaybackQueue: false};
        out.station = bridge.queueRemove(0, 'i.a');
        return out;
    """)
    def test_queue_remove_takes_the_entry_named_and_no_other(self, value):
        self.assertEqual(value['removed'], {'ok': True})
        self.assertEqual(value['after'], ['i.a', 'i.b', 'i.d'])
        self.assertEqual(value['current']['code'], 'CURRENT')
        self.assertEqual(value['stale']['code'], 'STALE')
        self.assertEqual(value['missing']['code'], 'STALE')
        self.assertEqual(value['calls'], [['queue.spliceQueueItems', 2, 1, 0]])
        self.assertEqual(value['events'], [['i.a', 'i.b', 'i.d']])
        self.assertEqual(value['old'], {'ok': True})
        self.assertEqual(value['oldCall'], ['queue.remove', 2])
        self.assertEqual(value['station']['code'], 'NOT_EDITABLE')

    @scenario("""
        const song = id => ({id, type: 'song', attributes: {name: id}});
        mk.queue = new FakeQueue(mk, [song('i.a'), song('i.b'), song('i.c'), song('i.d')], 1, [3]);
        const out = {};
        out.cleared = bridge.queueClear();
        out.after = mk.queue.items.map(item => item.id);
        out.undone = bridge.queueUndoClear();
        out.back = mk.queue._queueItems.map(entry => [entry.item.id, entry.isAutoplay]);
        out.twice = bridge.queueUndoClear();           // once only
        bridge.queueClear();
        mk.queue.position = 0;                          // another item plays now
        out.moved = bridge.queueUndoClear();
        out.calls = mk.calls.filter(call => call[0].startsWith('queue.'));
        mk.capabilities = {canEditPlaybackQueue: false};
        out.station = bridge.queueClear();
        return out;
    """)
    def test_queue_clear_keeps_what_it_took_for_undo(self, value):
        self.assertEqual(value['cleared'], {'ok': True, 'cleared': 2})
        self.assertEqual(value['after'], ['i.a', 'i.b'])
        self.assertEqual(value['undone'], {'ok': True, 'restored': 2})
        self.assertEqual(value['back'], [['i.a', False], ['i.b', False], ['i.c', False],
                                         ['i.d', True]])
        self.assertEqual(value['twice']['code'], 'STALE')
        self.assertEqual(value['moved']['code'], 'STALE')
        self.assertEqual(value['calls'], [['queue.clearAfterCurrent'],
                                          ['queue.spliceQueueItems', 2, 0, 2],
                                          ['queue.clearAfterCurrent']])
        self.assertEqual(value['station']['code'], 'NOT_EDITABLE')

    @scenario("""
        bridge.subscribe();
        const out = {read: bridge.autoplay(null)};
        out.on = bridge.autoplay(true);
        out.flag = mk.autoplayEnabled;
        mk.fire('autoplayEnabledDidChange', true);
        out.off = bridge.autoplay(false);
        mk.fire('autoplayEnabledDidChange', {});        // no boolean: the instance's
        mk.capabilities = {canAutoplay: false};
        out.station = bridge.autoplay(null);
        out.events = posted.filter(event => event.name === 'autoplayEnabledDidChange')
            .map(event => event.data);
        return out;
    """)
    def test_autoplay_is_set_and_followed(self, value):
        self.assertEqual(value['read'], {'autoplay': False, 'canAutoplay': True})
        self.assertEqual(value['on'], {'autoplay': True, 'canAutoplay': True})
        self.assertIs(value['flag'], True)
        self.assertEqual(value['off'], {'autoplay': False, 'canAutoplay': True})
        self.assertEqual(value['station'], {'autoplay': False, 'canAutoplay': False})
        self.assertEqual(value['events'], [{'autoplay': True}, {'autoplay': False}])

    # -- lyrics ----------------------------------------------------------------------------

    @scenario("""
        const path = '/v1/catalog/gb/songs/1000000001/syllable-lyrics';
        mk.apiAnswers[path] = {data: [{id: '1000000001', attributes: {ttml: TTML}}]};
        const synced = await bridge.lyrics('1000000001');
        mk.apiAnswers[path] = {data: [{attributes: {
            ttml: '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p>One</p><p>Two</p>'
                  + '</div></body></tt>'}}]};
        const unsynced = await bridge.lyrics('1000000001');
        mk.apiAnswers[path] = {data: [{attributes: {ttml: '<tt><p>Rock & Roll</p></tt>'}}]};
        const unreadable = await bridge.lyrics('1000000001');
        mk.apiAnswers[path] = {data: []};
        const none = await bridge.lyrics('1000000001');
        delete mk.apiAnswers[path];   // Apple refuses both requests: no lyrics either
        return {synced, unsynced, unreadable, none, refused: await bridge.lyrics('1000000001')};
    """)
    def test_lyrics_from_ttml(self, value):
        self.assertEqual(value['synced'], {'synced': True, 'lines': [
            {'startMs': 500, 'endMs': 4250, 'text': 'Rock & Roll \u2019til dawn',
             'stanza': True},
            {'startMs': 4500, 'endMs': 8000, 'text': 'Harbour lights'},
            {'startMs': 20000, 'endMs': 25100, 'text': 'Out on the water', 'stanza': True},
            {'startMs': 3601500, 'endMs': 3603000, 'text': 'Fish & chips <tonight>'}]})
        self.assertEqual(value['unsynced'], {'synced': False, 'lines': [
            {'startMs': 0, 'endMs': 0, 'text': 'One', 'stanza': True},
            {'startMs': 0, 'endMs': 0, 'text': 'Two'}]})
        for key in ('unreadable', 'none', 'refused'):
            self.assertEqual(value[key], {'synced': False, 'lines': []}, key)

    @scenario("""
        const song = '/v1/catalog/gb/songs/1000000001';
        mk.apiAnswers[song + '/syllable-lyrics'] = {data: [{attributes: {
            ttmlLocalizations: TTML_LOCALIZED}}]};
        const pronounced = await bridge.lyrics('1000000001', {lyrics: 'en-GB', script: 'en-Latn'});
        const asked = mk.calls.slice();
        // syllable-lyrics refused: the plain lyrics, without pronunciations.
        delete mk.apiAnswers[song + '/syllable-lyrics'];
        mk.apiAnswers[song + '/lyrics'] = {data: [{attributes: {ttml: TTML}}]};
        mk.calls.length = 0;
        const plain = await bridge.lyrics('1000000001');
        return {pronounced, asked, plain: plain.lines.length, fellBack: mk.calls};
    """)
    def test_lyrics_with_pronunciations_and_translations(self, value):
        self.assertEqual(value['asked'], [
            ['api.music', '/v1/catalog/gb/songs/1000000001/syllable-lyrics',
             {'extend': 'ttmlLocalizations', 'l[lyrics]': 'en-GB', 'l[script]': 'en-Latn'}]])
        self.assertEqual(value['pronounced'], {'synced': True, 'lines': [
            {'startMs': 1000, 'endMs': 4000, 'text': '\u9727\u306e\u6d77', 'stanza': True,
             'words': [{'startMs': 1000, 'endMs': 3000, 'text': '\u9727\u306e'},
                       {'startMs': 3000, 'endMs': 4000, 'text': '\u6d77'}],
             'background': '(\u6d77)',          # untimed: no words
             'pronunciation': 'Kiri no umi', 'pronunciationBackground': '(umi)',
             'pronunciationWords': [{'startMs': 1000, 'endMs': 2000, 'text': 'Kiri '},
                                    {'startMs': 2000, 'endMs': 3000, 'text': 'no '},
                                    {'startMs': 3000, 'endMs': 4000, 'text': 'umi'}],
             'translation': 'Fog on the sea', 'translationBackground': '(the sea)'},
            {'startMs': 5000, 'endMs': 7000, 'text': 'Oh oh'},    # the same as the line
            {'startMs': 7000, 'endMs': 9000, 'text': '\u6f6e',
             'translation': 'Tide'}]})                           # no pronunciation
        self.assertEqual(value['plain'], 4)
        self.assertEqual([call[1] for call in value['fellBack']], [
            '/v1/catalog/gb/songs/1000000001/syllable-lyrics',
            '/v1/catalog/gb/songs/1000000001/lyrics'])

    @scenario("""
        mk.apiAnswers['/v1/catalog/gb/songs/1000000001/syllable-lyrics'] = {data: [{attributes: {
            ttmlLocalizations: TTML_DUET}}]};
        return await bridge.lyrics('1000000001', {lyrics: 'en-GB', script: 'en-Latn'});
    """)
    def test_lyrics_words_background_vocals_and_singers(self, value):
        def words(*pieces):
            return [{'startMs': start, 'endMs': end, 'text': text}
                    for start, end, text in pieces]
        self.maxDiff = None
        self.assertEqual(value, {'synced': True, 'lines': [
            # Words parted by spaces, syllables joined; the translation the line itself.
            {'startMs': 1000, 'endMs': 4000, 'text': 'Grey morning, harbour light',
             'stanza': True, 'agent': 'v1',
             'words': words((1000, 1500, 'Grey '), (1500, 2000, 'morn'),
                            (2000, 2400, 'ing, '), (2400, 3000, 'har'),
                            (3000, 3300, 'bour '), (3300, 4000, 'light'))},
            # The singer its <div>'s; background vocals, timed, in each part.
            {'startMs': 10000, 'endMs': 13000, 'text': '\u6ce2\u306e\u6570\u3048',
             'stanza': True, 'agent': 'v2',
             'words': words((10000, 10800, '\u6ce2\u306e'), (10800, 12000, '\u6570\u3048')),
             'background': '(\u6570\u3048)',
             'backgroundWords': words((12200, 12600, '(\u6570'), (12600, 13000, '\u3048)')),
             'pronunciation': 'Nami o ka zo e te',
             'pronunciationWords': words((10000, 10400, 'Na'), (10400, 10800, 'mi '),
                                         (10800, 11200, 'o '), (11200, 12000, 'ka zo e te')),
             'pronunciationBackground': '(kazo e te)',
             'pronunciationBackgroundWords': words((12200, 12600, '(ka'),
                                                   (12600, 13000, 'zo e te)')),
             'translation': 'Counting the waves', 'translationBackground': '(counting)'},
            # A group's line; a <br> is a space.
            {'startMs': 14000, 'endMs': 17000, 'text': 'All to gether', 'stanza': True,
             'agent': 'v3',
             'words': words((14000, 15000, 'All '), (15000, 16000, 'to '),
                            (16000, 17000, 'gether'))},
            # Background vocals alone.
            {'startMs': 18000, 'endMs': 20000, 'text': '', 'agent': 'v1',
             'background': '(Oh oh)',
             'backgroundWords': words((18000, 19000, '(Oh '), (19000, 20000, 'oh)'))},
            # A word outside the spans: no words.
            {'startMs': 21000, 'endMs': 24000, 'text': 'Ah yes', 'agent': 'v2'}]})
        # Every piece joins to its text, and the engine keeps them all.
        kept = lyrics_answer(value, {'lyrics': 'en-GB', 'script': 'en-Latn'}, FORMAT)
        self.assertEqual(kept['lines'], value['lines'])
        # The main and the background vocals together read as the TTML's whole text does.
        self.assertEqual([' '.join(filter(None, (line['text'], line.get('background'))))
                          for line in value['lines']],
                         ['Grey morning, harbour light',
                          '\u6ce2\u306e\u6570\u3048 (\u6570\u3048)',
                          'All to gether', '(Oh oh)', 'Ah yes'])

    # -- search ----------------------------------------------------------------------------

    @scenario("""
        mk.apiAnswers['/v1/catalog/gb/search'] = {results: {}};
        mk.apiAnswers['/v1/catalog/gb/search/suggestions'] = {results: {}};
        const search = await bridge.search('harbour', 5);
        const suggest = await bridge.suggest('harb');
        return {search, suggest, calls: mk.calls};
    """)
    def test_search_and_suggest_ask_the_catalog(self, value):
        self.assertEqual(value['search'], {'results': {}})
        self.assertEqual(value['calls'], [
            ['api.music', '/v1/catalog/gb/search',
             {'term': 'harbour', 'types': 'albums,artists,music-videos,playlists,songs,stations',
              'limit': 5, 'with': 'topResults'}],
            ['api.music', '/v1/catalog/gb/search/suggestions',
             {'term': 'harb', 'kinds': 'terms,topResults',
              'types': 'albums,artists,music-videos,playlists,songs,stations', 'limit': 10}]])

    @scenario("""
        mk.apiAnswers['/v1/catalog/gb/apple-curators/900000901'] = {data: []};
        const answer = await bridge.category('900000901');
        return {answer, calls: mk.calls};
    """)
    def test_a_category_asks_for_its_shelves_contents_and_playlists(self, value):
        # A curator's page as music.apple.com asks for it: a radio show's lists its episodes
        # and playlists (#359, #360).
        self.assertEqual(value['answer'], {'data': []})
        self.assertEqual(value['calls'], [
            ['api.music', '/v1/catalog/gb/apple-curators/900000901',
             {'include': 'grouping,playlists',
              'include[editorial-elements]': 'children,contents,room',
              'extend': 'editorialArtwork', 'platform': 'web'}]])

    @scenario("""
        mk.apiAnswers['/v1/catalog/gb/search'] = {results: {}};
        await bridge.search('harbour', 20, 'albums,apple-curators,curators', 0, true);
        await bridge.search('harbour', 25, 'apple-curators', 50, false);
        return mk.calls;
    """)
    def test_a_search_names_its_types_and_pages_on(self, calls):
        self.assertEqual(calls, [
            ['api.music', '/v1/catalog/gb/search',
             {'term': 'harbour', 'types': 'albums,apple-curators,curators', 'limit': 20,
              'with': 'topResults'}],
            ['api.music', '/v1/catalog/gb/search',
             {'term': 'harbour', 'types': 'apple-curators', 'limit': 25, 'offset': 50}]])

    @scenario("""
        mk.writeStatus = 200;
        mk.writeBody = JSON.stringify({results: {suggested: [{id: '1000000101', type: 'songs'}]}});
        const answer = await bridge.playlistSuggestions('p.pl1');
        mk.writeBody = '';
        const empty = await bridge.playlistSuggestions('p.pl1');
        mk.writeStatus = 404;
        let refused = null;
        try { await bridge.playlistSuggestions('p.pl1'); } catch (error) {
            refused = String(error);
        }
        mk.writeStatus = 200;
        await bridge.playlistSuggestions('p.pl1', 10, ['1000000101', 1000000102], ['1000000102'],
                                         [1000000101]);
        return {answer, empty, refused, calls: mk.calls};
    """)
    def test_playlist_suggestions_post_the_playlist(self, value):
        self.assertEqual(value['answer'],
                         {'results': {'suggested': [{'id': '1000000101', 'type': 'songs'}]}})
        self.assertEqual(value['empty'], {})
        self.assertIn('HTTP 404', value['refused'])
        self.assertEqual(value['calls'][0], [
            'request', '/v1/me/recommendations/suggested',
            {'params': {'platform': 'web', 'omit[resource]': 'autos',
                        'contexts': 'playlist-suggested-songs', 'types': 'songs',
                        'include[songs]': 'artists', 'limit': 20},
             'method': 'POST',
             'body': {'targetContent': {'id': 'p.pl1', 'type': 'library-playlists'}}}])
        # A Refresh's: the songs shown so far offered (those previewed said so), those added
        # selected, a limit.
        request = value['calls'][-1][2]
        self.assertEqual(request['params']['limit'], 10)
        self.assertEqual(request['body'], {
            'targetContent': {'id': 'p.pl1', 'type': 'library-playlists'},
            'offered': {'suggested': [
                {'id': '1000000101', 'type': 'songs',
                 'meta': {'impressed': True, 'previewed': True}},
                {'id': '1000000102', 'type': 'songs',
                 'meta': {'impressed': True, 'previewed': False}}]},
            'selected': [{'id': '1000000102', 'type': 'songs', 'meta': {'source': 'suggested'}}]})

    # -- previews --------------------------------------------------------------------------

    @scenario("""
        mk.isPlaying = true;
        mk.volume = 0.4;
        const first = await bridge.preview('1000000101', 'https://example.invalid/a.m4a');
        const second = await bridge.preview(1000000102, 'https://example.invalid/b.m4a');
        await bridge.volume(0.25);
        const volume = audios[1].volume;
        audios[1].fire('ended');
        const after = await bridge.stopPreview();
        return {first, second, volume, after, posted, calls: mk.calls,
                audios: audios.map(a => ({src: a.src, calls: a.calls}))};
    """)
    def test_a_preview_pauses_musickit_and_plays_one_clip_at_a_time(self, value):
        self.assertEqual(value['first'], {'ok': True, 'id': '1000000101'})
        self.assertEqual(value['second'], {'ok': True, 'id': '1000000102'})
        self.assertIn(['pause'], value['calls'])
        self.assertNotIn(['setQueue'], [call[:1] for call in value['calls']])
        # The first clip stopped for the second, which followed the volume and then ended.
        self.assertEqual(value['audios'][0]['src'], '')
        self.assertEqual(value['audios'][0]['calls'][:2], ['play', 'pause'])
        self.assertEqual(value['volume'], 0.25)
        self.assertEqual(value['posted'], [
            {'name': 'previewDidChange', 'data': {'id': '1000000101'}},
            {'name': 'previewDidChange',
             'data': {'id': None, 'ended': '1000000101', 'reason': 'replaced'}},
            {'name': 'previewDidChange', 'data': {'id': '1000000102'}},
            {'name': 'previewDidChange',
             'data': {'id': None, 'ended': '1000000102', 'reason': 'ended'}}])
        self.assertEqual(value['after'], {'stopped': False})

    @scenario("""
        await bridge.preview('1000000101', 'https://example.invalid/a.m4a');
        const stopped = await bridge.stopPreview();
        await bridge.preview('1000000102', 'https://example.invalid/b.m4a');
        await bridge.play('song', '1000000103');
        await bridge.preview('1000000104', 'https://example.invalid/d.m4a');
        await bridge.control('toggle');
        await bridge.subscribe();
        await bridge.preview('1000000105', 'https://example.invalid/e.m4a');
        mk.isPlaying = true;
        mk.fire('playbackStateDidChange', {state: 2});
        return {stopped, reasons: posted.filter(p => p.name === 'previewDidChange' && !p.data.id)
                                         .map(p => [p.data.ended, p.data.reason])};
    """)
    def test_a_preview_stops_when_asked_or_when_musickit_plays(self, value):
        self.assertEqual(value['stopped'], {'stopped': True})
        self.assertEqual(value['reasons'], [
            ['1000000101', 'stopped'], ['1000000102', 'playback'],
            ['1000000104', 'playback'], ['1000000105', 'playback']])

    @scenario("""
        const none = await bridge.preview('1000000101', '');
        const plain = await bridge.preview('1000000101', 'http://example.invalid/a.m4a');
        const error = new Error('denied');
        error.name = 'NotAllowedError';
        failAudio(error);
        const refused = await bridge.preview('1000000101', 'https://example.invalid/a.m4a');
        const stopped = await bridge.stopPreview();
        failAudio(null);
        await bridge.preview('1000000102', 'https://example.invalid/b.m4a');
        audios[audios.length - 1].fire('error');
        return {none, plain, refused, stopped, posted};
    """)
    def test_a_preview_the_page_cannot_play(self, value):
        self.assertEqual(value['none']['code'], 'NO_PREVIEW')
        self.assertEqual(value['plain']['code'], 'NO_PREVIEW')
        self.assertEqual(value['refused']['code'], 'NotAllowedError')
        self.assertEqual(value['stopped'], {'stopped': False})
        self.assertEqual(value['posted'], [
            {'name': 'previewDidChange', 'data': {'id': '1000000102'}},
            {'name': 'previewDidChange',
             'data': {'id': None, 'ended': '1000000102', 'reason': 'error'}}])

    # -- writes ----------------------------------------------------------------------------

    @scenario("""
        await bridge.rating('library-song', 'i.song1', 1);
        await bridge.rating('album', '1000000002', 0);
        await bridge.addToLibrary('music-video', '1000000009');
        await bridge.addToPlaylist('p.pl1', 'i.song1', 'library-songs');
        await bridge.rating('station', 'ra.1000000003', -1);
        mk.writeStatus = 403;
        let refused = null;
        try { await bridge.rating('song', '1', 1); } catch (error) { refused = String(error); }
        return {calls: mk.calls, refused};
    """)
    def test_writes_go_through_the_request_builder(self, value):
        self.assertEqual(value['calls'][:5], [
            ['request', '/v1/me/ratings/library-songs/i.song1',
             {'params': {}, 'method': 'PUT', 'body': {'type': 'ratings',
                                                      'attributes': {'value': 1}}}],
            ['request', '/v1/me/ratings/albums/1000000002', {'params': {}, 'method': 'DELETE'}],
            ['request', '/v1/me/library', {'params': {'ids[music-videos]': '1000000009'},
                                           'method': 'POST'}],
            ['request', '/v1/me/library/playlists/p.pl1/tracks',
             {'params': {}, 'method': 'POST',
              'body': {'data': [{'id': 'i.song1', 'type': 'library-songs'}]}}],
            # Suggest Less: the rating -1.
            ['request', '/v1/me/ratings/stations/ra.1000000003',
             {'params': {}, 'method': 'PUT', 'body': {'type': 'ratings',
                                                      'attributes': {'value': -1}}}],
        ])
        self.assertIn('HTTP 403', value['refused'])

    @scenario("""
        mk.writeStatus = 204;
        mk.writeBody = '';
        const removed = await bridge.removeFromLibrary('songs', 'i.song1');
        mk.writeStatus = 200;
        mk.writeBody = JSON.stringify({data: [{id: 'l.alb1', type: 'library-albums'}]});
        const there = await bridge.libraryHas('albums', 'l.alb1');
        mk.writeStatus = 404;
        mk.writeBody = '';
        const gone = await bridge.libraryHas('albums', 'l.alb1');
        let refused = null;
        try { await bridge.removeFromLibrary('songs', 'i.song1'); } catch (error) {
            refused = String(error);
        }
        mk.writeStatus = 500;
        let failed = null;
        try { await bridge.libraryHas('songs', 'i.song1'); } catch (error) {
            failed = String(error);
        }
        return {removed, there, gone, refused, failed, calls: mk.calls};
    """)
    def test_removing_from_the_library(self, value):
        self.assertEqual(value['removed'], {'ok': True})
        self.assertEqual((value['there'], value['gone']), ({'has': True}, {'has': False}))
        self.assertIn('HTTP 404', value['refused'])
        self.assertIn('HTTP 500', value['failed'])
        self.assertEqual(value['calls'][:3], [
            ['request', '/v1/me/library/songs/i.song1', {'params': {}, 'method': 'DELETE'}],
            ['request', '/v1/me/library/albums/l.alb1', {'params': {}, 'method': 'GET'}],
            ['request', '/v1/me/library/albums/l.alb1', {'params': {}, 'method': 'GET'}],
        ])

    @scenario("""
        mk.writeStatus = 202;
        mk.writeBody = '';
        const made = await bridge.favourite('artists', '1000000005', true);
        mk.writeStatus = 204;
        const taken = await bridge.favourite('artists', '1000000005', false);
        mk.writeStatus = 200;
        mk.writeBody = JSON.stringify({data: [{id: '1000000005', type: 'artists',
                                               attributes: {inFavorites: true}}]});
        const read = await bridge.apiFresh('/v1/catalog/gb/artists/1000000005',
                                           {extend: 'inFavorites'});
        mk.writeStatus = 404;
        mk.writeBody = JSON.stringify({errors: [{title: 'Resource Not Found'}]});
        let missing = null;
        try {
            await bridge.apiFresh('/v1/catalog/gb/artists/1', {extend: 'inFavorites'});
        } catch (error) {
            missing = String(error);
        }
        mk.writeStatus = 403;
        let refused = null;
        try { await bridge.favourite('artists', '1000000005', true); } catch (error) {
            refused = String(error);
        }
        return {made, taken, read, missing, refused, calls: mk.calls};
    """)
    def test_an_artists_favourite(self, value):
        # The web player's UpdateFavoritesIntent, through the request builder, and the state
        # read the same way (music() may answer from its cache).
        self.assertEqual((value['made'], value['taken']), ({'ok': True}, {'ok': True}))
        self.assertEqual(value['read']['data'][0]['attributes'], {'inFavorites': True})
        self.assertIn('HTTP 404 Resource Not Found', value['missing'])
        self.assertIn('HTTP 403', value['refused'])
        self.assertEqual(value['calls'][:3], [
            ['request', '/v1/me/favorites', {'params': {'ids[artists]': '1000000005'},
                                             'method': 'POST'}],
            ['request', '/v1/me/favorites', {'params': {'ids[artists]': '1000000005'},
                                             'method': 'DELETE'}],
            ['request', '/v1/catalog/gb/artists/1000000005',
             {'params': {'extend': 'inFavorites'}, 'method': 'GET'}],
        ])
        self.assertNotIn('api.music', [call[0] for call in value['calls']])

    @scenario("""
        mk.writeStatus = 201;
        mk.writeBody = JSON.stringify({data: [{id: 'p.new1', type: 'library-playlists'}]});
        const created = await bridge.createPlaylist(
            {name: 'Night Drive', description: 'Late'},
            [{id: 'i.song1', type: 'library-songs'}], 'p.fd1');
        const empty = await bridge.createPlaylist({name: 'Empty'}, [], null);
        mk.writeStatus = 204;
        mk.writeBody = '';
        const updated = await bridge.updatePlaylist('p.pl1', {name: 'Renamed'});
        await bridge.removeFromPlaylist('p.pl1', 'library-songs', 'i.song1');
        await bridge.replacePlaylistTracks('p.pl1', [{id: 'i.song2', type: 'library-songs'}]);
        await bridge.deletePlaylist('p.pl1');
        await bridge.updateFolder('p.fd1', {name: 'Evenings'});
        await bridge.deleteFolder('p.fd1');
        let unnamed = null;
        mk.writeStatus = 201;
        try { await bridge.createPlaylist({name: 'X'}, [], null); } catch (error) {
            unnamed = String(error);
        }
        return {created, empty, updated, calls: mk.calls, unnamed};
    """)
    def test_the_playlist_writes(self, value):
        self.assertEqual(value['created'], {'id': 'p.new1'})
        self.assertEqual(value['empty'], {'id': 'p.new1'})
        self.assertEqual(value['updated'], {'ok': True})
        self.assertIn('without its id', value['unnamed'])  # a 201 with no body
        playlists = '/v1/me/library/playlists'
        self.assertEqual(value['calls'][:8], [
            ['request', playlists, {'params': {}, 'method': 'POST', 'body': {
                'attributes': {'name': 'Night Drive', 'description': 'Late'},
                'relationships': {
                    'tracks': {'data': [{'id': 'i.song1', 'type': 'library-songs'}]},
                    'parent': {'data': [{'id': 'p.fd1',
                                         'type': 'library-playlist-folders'}]}}}}],
            ['request', playlists, {'params': {}, 'method': 'POST',
                                    'body': {'attributes': {'name': 'Empty'}}}],
            ['request', f'{playlists}/p.pl1', {'params': {}, 'method': 'PATCH',
                                               'body': {'attributes': {'name': 'Renamed'}}}],
            ['request', f'{playlists}/p.pl1/tracks', {
                'params': {'mode': 'all', 'ids[library-songs]': 'i.song1'},
                'method': 'DELETE'}],
            ['request', f'{playlists}/p.pl1/tracks', {
                'params': {}, 'method': 'PUT',
                'body': {'data': [{'id': 'i.song2', 'type': 'library-songs'}]}}],
            ['request', f'{playlists}/p.pl1', {'params': {}, 'method': 'DELETE'}],
            ['request', '/v1/me/library/playlist-folders/p.fd1', {
                'params': {}, 'method': 'PATCH', 'body': {'attributes': {'name': 'Evenings'}}}],
            ['request', '/v1/me/library/playlist-folders/p.fd1',
             {'params': {}, 'method': 'DELETE'}],
        ])

    @scenario("""
        mk.writeStatus = 201;
        mk.writeBody = JSON.stringify({data: [{id: 'p.fdnew', type: 'library-playlist-folders'}]});
        const inside = await bridge.createFolder({name: 'Box'}, 'p.fd1');
        const top = await bridge.createFolder({name: 'Top'}, null);
        mk.writeStatus = 204;
        mk.writeBody = '';
        const moved = await bridge.moveToFolder('library-playlists', 'p.pl1', 'p.fdnew');
        await bridge.moveToFolder('library-playlists', 'p.pl1', 'p.playlistsroot');
        await bridge.moveToFolder('library-playlist-folders', 'p.fd2', 'p.fd1');
        let unnamed = null;
        mk.writeStatus = 201;
        try { await bridge.createFolder({name: 'X'}, null); } catch (error) {
            unnamed = String(error);
        }
        return {inside, top, moved, calls: mk.calls, unnamed};
    """)
    def test_the_folder_writes(self, value):
        self.assertEqual(value['inside'], {'id': 'p.fdnew'})
        self.assertEqual(value['top'], {'id': 'p.fdnew'})
        self.assertEqual(value['moved'], {'ok': True})
        self.assertIn('without its id', value['unnamed'])
        folders = '/v1/me/library/playlist-folders'
        into = {'type': 'library-playlist-folders'}
        self.assertEqual(value['calls'][:5], [
            ['request', folders, {'params': {}, 'method': 'POST', 'body': {
                'attributes': {'name': 'Box'},
                'relationships': {'parent': {'data': [dict(into, id='p.fd1')]}}}}],
            ['request', folders, {'params': {}, 'method': 'POST',
                                  'body': {'attributes': {'name': 'Top'}}}],
            ['request', '/v1/me/library/playlists/p.pl1/parent', {
                'params': {}, 'method': 'PUT', 'body': {'data': [dict(into, id='p.fdnew')]}}],
            ['request', '/v1/me/library/playlists/p.pl1/parent', {
                'params': {}, 'method': 'PUT',
                'body': {'data': [dict(into, id='p.playlistsroot')]}}],
            ['request', f'{folders}/p.fd2/parent', {
                'params': {}, 'method': 'PUT', 'body': {'data': [dict(into, id='p.fd1')]}}],
        ])


if __name__ == '__main__':
    unittest.main()
