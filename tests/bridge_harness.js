// SPDX-License-Identifier: GPL-2.0-or-later
// SPDX-FileCopyrightText: 2026 Jack Tully

// A stand-in page for src/backend/bridge.js, run under gjs by tests/test_bridge.py.
//
// `window` is the global object, as in the page. `MusicKit` is a fake whose instance records
// every call the bridge makes on it (`mk.calls`) and answers from what a scenario sets on it;
// `document` answers the selectors a scenario gives it; `DOMParser` is a small XML parser,
// enough for Apple's TTML lyrics (elements, attributes, text, CDATA, the five XML entities and
// character references; anything else is a <parsererror> document, as in a browser).
//
// test_bridge.py appends the bridge's source as BRIDGE and the scenarios as SCENARIOS, then
// calls run(): each scenario gets a fresh page (a new instance, the bridge injected), and
// their outcomes are printed as one JSON object, {name: {value} or {error}}.

globalThis.window = globalThis;

// MusicKit.PlaybackStates as MusicKit v3 numbers them, both ways (0 -> 'none', 'none' -> 0).
const PLAYBACK_STATES = {
    none: 0, loading: 1, playing: 2, paused: 3, stopped: 4, ended: 5, seeking: 6,
    waiting: 8, stalled: 9, completed: 10,
};

function bothWays(names) {
    const map = {};
    for (const [name, number] of Object.entries(names)) {
        map[name] = number;
        map[number] = name;
    }
    return map;
}

// MusicKit v3's queue as the live check saw it: `_queueItems` of {item, isAutoplay}, `items`
// the MediaItems, `position`, and the edits, each recorded on the instance's `calls` and
// posting one queueItemsDidChange: spliceQueueItems, the deprecated remove (which throws for
// the current index), clearAfterCurrent. `new FakeQueue(mk, items, position, autoplay)`:
// `autoplay` the indices of the entries autoplay added. Each edit takes its arguments as
// MusicKit's does (src/backend/README.md, "The queue"), so a call MusicKit would refuse
// fails here too.
class FakeQueue {
    constructor(instance, items, position, autoplay) {
        this.instance = instance;
        this._queueItems = items.map((item, index) => ({
            item, isAutoplay: (autoplay || []).includes(index),
        }));
        this.position = position;
    }

    get items() {
        return this._queueItems.map(entry => entry.item);
    }

    get autoplayItems() {
        return this._queueItems.filter(entry => entry.isAutoplay).map(entry => entry.item);
    }

    get unplayedAutoplayItems() {
        return this._queueItems.slice(this.position + 1)
            .filter(entry => entry.isAutoplay).map(entry => entry.item);
    }

    get isInitiated() {
        return this.position >= 0;
    }

    get isEmpty() {
        return this._queueItems.length === 0;
    }

    get currentQueueItem() {
        return this._queueItems[this.position];
    }

    appendQueueItems(items = []) {
        this.spliceQueueItems(this._queueItems.length, 0, items);
    }

    // MusicKit's: every queue item `predicate(queueItem, index)` accepts, from the end, one
    // splice (and one event) each.
    removeQueueItems(predicate) {
        for (let index = this._queueItems.length - 1; index >= 0; index--) {
            if (predicate(this._queueItems[index], index))
                this.spliceQueueItems(index, 1);
        }
    }

    // MusicKit's own, in the page (playback/AppleMusic-2642.7.0-external):
    //   spliceQueueItems(e, t, r = [], s = !0) { r = r.filter(a => cn(a?.item, …)); … }
    // The entries to put in are one array of queue items ({item, isAutoplay}): spread out as
    // arguments, `items` is the first of them, an object, and its filter() throws the
    // TypeError MusicKit throws; an entry without an `item` (a MediaItem) is dropped, as
    // MusicKit's filter drops it. The fourth argument is not modelled.
    spliceQueueItems(start, deleteCount, items = [], _notify = true) {
        const added = items.filter(entry => Boolean(entry?.item));
        this.instance.calls.push(['queue.spliceQueueItems', start, deleteCount, added.length]);
        const taken = this._queueItems.splice(start, deleteCount, ...added);
        this.instance.fire('queueItemsDidChange', {});
        return taken;
    }

    remove(index) {
        this.instance.calls.push(['queue.remove', index]);
        if (index === this.position)
            throw new Error('INVALID_ARGUMENTS');
        this._queueItems.splice(index, 1);
        this.instance.fire('queueItemsDidChange', {});
    }

    clearAfterCurrent() {
        this.instance.calls.push(['queue.clearAfterCurrent']);
        this._queueItems.splice(this.position + 1);
        this.instance.fire('queueItemsDidChange', {});
    }
}
globalThis.FakeQueue = FakeQueue;

// Apple's servers as autoplay meets them: every request answers after `TURNS` turns of the
// job queue, in the order sent (gjs runs no timers here). `paths` records what was asked.
const NETWORK_TURNS = 8;

async function later(value) {
    for (let turn = 0; turn < NETWORK_TURNS; turn++)
        await null;
    return value;
}

// Let what is on its way land: enough turns for a request and what it starts.
async function settle() {
    for (let turn = 0; turn < NETWORK_TURNS * 12; turn++)
        await null;
}
globalThis.settle = settle;

// MusicKit v3's SerialPlaybackController and its autoplay, line for line where it matters,
// from the page's bundle (playback/AppleMusic-2642.7.0-external; src/backend/README.md,
// "Autoplay across queues"). `serialController(mk)` gives an instance one, as
// mk.playbackControllers.serial and mk._playbackController; its setQueue then replaces the
// queue as MusicKit's does. A request to the station (/v1/me/stations/continuous, then
// /v1/me/stations/next-tracks/<id>) answers through later(); `rejections` holds what its
// handlers threw, as the page's unhandled rejections.
class FakeSerialController {
    constructor(instance) {
        this.instance = instance;
        this._autoplayStation = undefined;
        this.loadingAutoplayStation = false;
        this.loadingAutoplayTracks = false;
        this.isActive = true;
        this.paths = [];
        this.log = [];
        this.rejections = [];
        this.stations = 0;
        this.tracks = 0;
        // MusicKit's dispatcher reaches the controller before the page's listeners.
        instance.subscribe('queueItemsDidChange', () => this.onQueueChange());
        instance.subscribe('autoplayEnabledDidChange', on => {
            const run = on === true ? this.startAutoplay() : this.stopAutoplay();
            run.catch(error => this.rejections.push(String(error)));
        });
    }

    get autoplayStation() {
        return this._autoplayStation;
    }

    get queue() {
        return this.instance.queue;
    }

    // MusicKit's replaceQueue: the old item stopped, a new queue (at `startWith`, when
    // given: initiated, as MusicKit's Fl starts it) posted with queueItemsDidChange, then
    // its autoplay stopped and started again.
    async replaceQueue(items, startWith) {
        await null;
        const queue = new FakeQueue(this.instance, items, -1);
        if (startWith !== undefined) {
            const at = parseInt(`${startWith}`, 10);
            queue.position = at >= 0 && at < items.length ? at : -1;
        }
        this.instance.queue = queue;
        this.instance.fire('queueItemsDidChange', {});
        await this.stopAutoplay();
        await this.startAutoplay();
    }

    // onQueueChange: an initiated queue asks for more autoplay songs, one not yet started
    // stops and starts autoplay. Not awaited by the dispatcher.
    onQueueChange() {
        const run = async () => {
            if (this.queue.isInitiated) {
                if (!this.queue.isEmpty) await this.queueAutoplayTracks();
            } else {
                this.stopAutoplay();
                this.startAutoplay();
            }
        };
        run().catch(error => this.rejections.push(String(error)));
    }

    async stopAutoplay() {
        this._autoplayStation = undefined;
        this.queue.hasAutoplayStation = false;
        if (this.queue.isInitiated) {
            this.queue.removeQueueItems((entry, index) =>
                index > this.queue.position && entry.isAutoplay === true);
        }
    }

    async startAutoplay() {
        if (!this.isActive || !this.instance._autoplayEnabled || this.instance.repeatMode !== 0)
            return;
        if (this._autoplayStation !== undefined || this.loadingAutoplayStation)
            return;
        if (this.queue.items.length === 0)
            return;
        this.loadingAutoplayStation = true;
        this.paths.push('/v1/me/stations/continuous');
        const station = await later({ id: 'ra.cp-' + ++this.stations });
        this._autoplayStation = station;
        this.queue.hasAutoplayStation = true;
        this.loadingAutoplayStation = false;
        await this.queueAutoplayTracks();
    }

    async queueAutoplayTracks() {
        if (this._autoplayStation === undefined || this.loadingAutoplayTracks)
            return;
        const current = this.queue.currentQueueItem;
        const wanted = 10 - this.queue.unplayedAutoplayItems.length + (current && current.isAutoplay ? 1 : 0);
        if (wanted <= 0)
            return;
        this.loadingAutoplayTracks = true;
        const from = this._autoplayStation.id;
        this.paths.push('/v1/me/stations/next-tracks/' + from);
        const songs = await later(Array.from({ length: wanted }, () => ({
            id: `${from}.t${++this.tracks}`, type: 'songs', attributes: { name: 'autoplay' },
        })));
        // MusicKit's own next line, a log message: it reads the station's id again, which
        // throws when the station went meanwhile, and loadingAutoplayTracks stays true.
        this.log.push(`Queueing ${songs.length} tracks from Autoplay station ${this._autoplayStation.id}`);
        this.queue.appendQueueItems(songs.map(item => ({ item, isAutoplay: true })));
        this.loadingAutoplayTracks = false;
    }
}

globalThis.serialController = function (mk) {
    const controller = new FakeSerialController(mk);
    mk.playbackControllers = { serial: controller };
    mk._playbackController = controller;
    return controller;
};

// The songs of a queue a fake setQueue makes: `mk.queueLength` of them, named after what
// it was asked to play.
function queueSongs(instance, options) {
    const name = options.album || options.playlist || options.station || 'songs';
    return Array.from({ length: instance.queueLength }, (_, n) => ({
        id: `${name}.${n + 1}`, type: 'songs', attributes: { name: `${name} ${n + 1}` },
    }));
}

class FakeInstance {
    constructor() {
        this.calls = [];        // [method, ...args] of everything the bridge asked
        this.listeners = {};    // event name -> [handler]
        this.subscribers = {};  // event name -> [handler]: MusicKit's own (its controller)
        this.queueLength = 3;   // the songs a setQueue over a controller queues
        this.failures = {};     // method -> what it rejects with
        this.apiAnswers = {};   // path -> the body mk.api.music(path) answers
        this.writeStatus = 204; // what a write's request answers
        this.writeBody = '';    // and the body it answers with (a 201's new resource)
        this.isAuthorized = false;
        this.storefrontId = 'gb';
        this._bitrate = 256;
        this.playbackState = 0;
        this.isPlaying = false;
        this.currentPlaybackTime = 0;
        this.currentPlaybackDuration = 0;
        this.shuffleMode = 0;
        this.repeatMode = 0;
        this.volume = 1;
        this.nowPlayingItem = null;
        this.nowPlayingItemIndex = -1;
        this.queue = { items: [], position: -1 };
        this._autoplayEnabled = false;  // the page started with it off (README, "The queue")
        const instance = this;
        this.api = {
            async music(path, params) {
                instance.calls.push(['api.music', path, params || {}]);
                if (!(path in instance.apiAnswers)) throw new Error('404 Not Found: ' + path);
                return { data: instance.apiAnswers[path] };
            },
            client: {
                createRequest(path, options) {
                    return {
                        async send() {
                            instance.calls.push(['request', path, options]);
                            const status = instance.writeStatus;
                            return {
                                ok: status < 400, status: status, statusText: '',
                                async text() { return instance.writeBody; },
                            };
                        },
                    };
                },
            },
        };
    }

    // MusicKit's autoplay switch, a property: set to another value, it posts
    // autoplayEnabledDidChange with the new boolean.
    get autoplayEnabled() {
        return this._autoplayEnabled;
    }

    set autoplayEnabled(on) {
        on = Boolean(on);
        if (on === this._autoplayEnabled)
            return;
        this._autoplayEnabled = on;
        this.fire('autoplayEnabledDidChange', on);
    }

    // MusicKit's streaming bitrate (kbps, a PlaybackBitrate), a property: set to another
    // value, it posts playbackBitrateDidChange with {bitrate}, as MusicKit's bitrate
    // calculator does (src/backend/README.md, "Streaming quality").
    get bitrate() {
        return this._bitrate;
    }

    set bitrate(kbps) {
        if (kbps === this._bitrate)
            return;
        this._bitrate = kbps;
        this.fire('playbackBitrateDidChange', { bitrate: kbps });
    }

    addEventListener(name, handler) {
        (this.listeners[name] = this.listeners[name] || []).push(handler);
    }

    removeEventListener(name, handler) {
        this.listeners[name] = (this.listeners[name] || []).filter(h => h !== handler);
    }

    // MusicKit's dispatcher, inside MusicKit: its subscribers hear an event first.
    subscribe(name, handler) {
        (this.subscribers[name] = this.subscribers[name] || []).push(handler);
    }

    // MusicKit firing `name` at its own subscribers, then every listener.
    fire(name, event) {
        for (const handler of (this.subscribers[name] || []).slice())
            handler(event);
        for (const handler of (this.listeners[name] || []).slice())
            handler(event);
    }

    // How many listeners each event has, the events without any left out.
    listenerCounts() {
        const counts = {};
        for (const [name, handlers] of Object.entries(this.listeners)) {
            if (handlers.length)
                counts[name] = handlers.length;
        }
        return counts;
    }

    async _call(method, args) {
        this.calls.push([method, ...args]);
        if (this.failures[method])
            throw this.failures[method];
    }

    // With a controller (serialController()), MusicKit's setQueue: the songs loaded, the
    // queue replaced, then played when `startPlaying`.
    async setQueue(...args) {
        await this._call('setQueue', args);
        const controller = this._playbackController;
        if (!controller)
            return;
        const options = args[0] || {};
        await controller.replaceQueue(queueSongs(this, options), options.startWith);
        if (options.startPlaying === true)
            await this.play();
    }
    play(...args) { return this._call('play', args); }
    pause(...args) { return this._call('pause', args); }
    stop(...args) { return this._call('stop', args); }
    skipToNextItem(...args) { return this._call('skipToNextItem', args); }
    skipToPreviousItem(...args) { return this._call('skipToPreviousItem', args); }
    seekToTime(...args) { return this._call('seekToTime', args); }
    playNext(...args) { return this._call('playNext', args); }
    playLater(...args) { return this._call('playLater', args); }
    changeToMediaAtIndex(...args) { return this._call('changeToMediaAtIndex', args); }
    authorize(...args) { return this._call('authorize', args); }
    unauthorize(...args) { return this._call('unauthorize', args); }
}

// The page's Audio: an element that records what it is asked (`audios`, every one made), whose
// play() resolves, or rejects with `audioFailure` when a scenario sets one; fire(name) sends it
// an event ('ended', 'error') as the browser would.
const audios = [];
let audioFailure = null;

class FakeAudio {
    constructor(src) {
        this.src = src;
        this.volume = 1;
        this.paused = true;
        this.listeners = {};
        this.calls = [];
        audios.push(this);
    }

    addEventListener(name, handler) {
        (this.listeners[name] = this.listeners[name] || []).push(handler);
    }

    fire(name) {
        for (const handler of (this.listeners[name] || []).slice())
            handler({});
    }

    async play() {
        this.calls.push('play');
        if (audioFailure)
            throw audioFailure;
        this.paused = false;
    }

    pause() {
        this.calls.push('pause');
        this.paused = true;
    }

    removeAttribute(name) {
        this.calls.push('removeAttribute ' + name);
        if (name === 'src')
            this.src = '';
    }

    load() {
        this.calls.push('load');
    }
}

globalThis.Audio = FakeAudio;

// The page's MusicKit global over `instance`.
function fakeMusicKit(instance) {
    return {
        PlaybackStates: bothWays(PLAYBACK_STATES),
        PlayerShuffleMode: bothWays({ off: 0, songs: 1 }),
        PlaybackBitrate: { HIGH: 256, STANDARD: 64 },
        getInstance() { return instance; },
    };
}

// The page's document: `elements` maps a selector to the elements it finds ({textContent}).
const page = { elements: {} };
globalThis.document = {
    querySelectorAll(selectors) {
        const found = [];
        for (const selector of selectors.split(','))
            found.push(...(page.elements[selector.trim()] || []));
        return found;
    },
    querySelector(selectors) {
        return this.querySelectorAll(selectors)[0] || null;
    },
};

// The page's navigator: requestMediaKeySystemAccess() grants the key systems in
// `page.keySystems` (Widevine, as Google Chrome's page does) and rejects the rest with the
// NotSupportedError a browser without the module throws; `page.keyRequests` records each
// request as [keySystem, configs].
globalThis.navigator = {};

function resetNavigator() {
    page.keySystems = ['com.widevine.alpha'];
    page.keyRequests = [];
    navigator.requestMediaKeySystemAccess = async function (keySystem, configs) {
        page.keyRequests.push([keySystem, configs]);
        if (!page.keySystems.includes(keySystem)) {
            const error = new Error('Unsupported keySystem or supportedConfigurations.');
            error.name = 'NotSupportedError';
            throw error;
        }
        return { keySystem };
    };
}

// -- DOMParser ---------------------------------------------------------------------------------

const XML_ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };

function decodeXml(text) {
    return text.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[A-Za-z]+);|&/g, (whole, name) => {
        if (name === undefined)
            throw new Error('a bare &');
        if (name[0] === '#') {
            const hex = name[1] === 'x';
            return String.fromCodePoint(parseInt(name.slice(hex ? 2 : 1), hex ? 16 : 10));
        }
        if (!(name in XML_ENTITIES))
            throw new Error('undefined entity ' + whole);
        return XML_ENTITIES[name];
    });
}

class XmlNode {
    constructor(nodeType, nodeName, nodeValue) {
        this.nodeType = nodeType;     // 1 element, 3 text, 4 CDATA, 9 document
        this.nodeName = nodeName;
        this.nodeValue = nodeValue === undefined ? null : nodeValue;
        this.childNodes = [];
        this.parentNode = null;
        this.attributes = {};
    }

    get localName() {
        return this.nodeType === 1 ? this.nodeName.split(':').pop() : null;
    }

    get tagName() {
        return this.nodeName;
    }

    get textContent() {
        if (this.nodeType === 3 || this.nodeType === 4)
            return this.nodeValue;
        return this.childNodes.map(child => child.textContent).join('');
    }

    append(child) {
        child.parentNode = this;
        this.childNodes.push(child);
    }

    getAttribute(name) {
        return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
    }

    _elements(match) {
        const found = [];
        const walk = node => {
            for (const child of node.childNodes) {
                if (child.nodeType !== 1)
                    continue;
                if (match(child))
                    found.push(child);
                walk(child);
            }
        };
        walk(this);
        return found;
    }

    getElementsByTagName(name) {
        return this._elements(element => name === '*' || element.nodeName === name);
    }

    // Namespaces are not modelled: any namespace, matched by the local name.
    getElementsByTagNameNS(_namespace, name) {
        return this._elements(element => name === '*' || element.localName === name);
    }
}

const XML_TOKEN = new RegExp([
    /<!\[CDATA\[([\s\S]*?)\]\]>/.source,                         // 1 CDATA
    /<!--[\s\S]*?-->|<\?[\s\S]*?\?>/.source,                     // a comment, a declaration
    /<\/([^\s>]+)\s*>/.source,                                   // 2 a closing tag
    /<([^\s/>!?]+)((?:\s+[^\s=/>]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>/.source,  // 3-5 a tag
    /([^<]+)/.source,                                            // 6 text
].join('|'), 'g');

globalThis.DOMParser = class DOMParser {
    parseFromString(text, _type) {
        try {
            return this._parse(String(text));
        } catch (error) {
            // As a browser answers XML it cannot read: a document with a <parsererror>.
            const failed = new XmlNode(9, '#document');
            const root = new XmlNode(1, 'parsererror');
            root.append(new XmlNode(3, '#text', String(error.message)));
            failed.append(root);
            return failed;
        }
    }

    _parse(text) {
        const document = new XmlNode(9, '#document');
        const open = [document];
        let at = 0;
        XML_TOKEN.lastIndex = 0;
        let match;
        while ((match = XML_TOKEN.exec(text)) !== null) {
            if (match.index !== at)
                throw new Error('not well-formed at ' + at);
            at = XML_TOKEN.lastIndex;
            const parent = open[open.length - 1];
            if (match[1] !== undefined) {
                parent.append(new XmlNode(4, '#cdata-section', match[1]));
            } else if (match[2] !== undefined) {
                if (open.length < 2 || parent.nodeName !== match[2])
                    throw new Error('</' + match[2] + '> closes nothing');
                open.pop();
            } else if (match[3] !== undefined) {
                const element = new XmlNode(1, match[3]);
                for (const attribute of match[4].matchAll(/([^\s=]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g))
                    element.attributes[attribute[1]] = decodeXml(attribute[2] ?? attribute[3]);
                parent.append(element);
                if (!match[5])
                    open.push(element);
            } else if (match[6] !== undefined) {
                if (open.length > 1)
                    parent.append(new XmlNode(3, '#text', decodeXml(match[6])));
                else if (match[6].trim())
                    throw new Error('text outside the root element');
            }
        }
        if (at !== text.length || open.length !== 1)
            throw new Error('the document ends inside an element');
        return document;
    }
};

// -- running the scenarios ---------------------------------------------------------------------

const posted = [];  // the events the bridge posted through the binding, parsed

// A page with a fresh MusicKit instance, the bridge at `version` injected into it (as
// client.load_bridge's source is: its version set, then the file evaluated globally).
function newPage(version) {
    delete window.__appleMusicLibrary;
    delete window.__appleMusicListeners;
    posted.length = 0;
    audios.length = 0;
    audioFailure = null;
    page.elements = {};
    resetNavigator();
    const mk = new FakeInstance();
    window.MusicKit = fakeMusicKit(mk);
    window.__amEvent = json => posted.push(JSON.parse(json));
    inject(version || 'v1');
    return mk;
}

function inject(version) {
    window.__appleMusicLibraryWanted = version;
    (0, eval)(BRIDGE);  // eslint-disable-line no-eval
}

async function run() {
    const outcomes = {};
    for (const [name, scenario] of Object.entries(SCENARIOS)) {
        try {
            const mk = newPage();
            const value = await scenario({
                bridge: window.__appleMusicLibrary, mk, posted, page, audios,
                failAudio(error) { audioFailure = error; },
            });
            // As JSON now: the next page empties `posted`, which a scenario may return.
            outcomes[name] = JSON.parse(JSON.stringify({ value: value === undefined ? null : value }));
        } catch (error) {
            outcomes[name] = { error: String(error && error.stack ? `${error}\n${error.stack}` : error) };
        }
    }
    print(JSON.stringify(outcomes));
}
