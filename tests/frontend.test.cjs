const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

function scriptFrom(name) {
    const html = fs.readFileSync(path.join(root, 'templates', name), 'utf8');
    const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
    return scripts.map(match => match[1]).findLast(source => source.trim());
}

class TextNode {
    constructor(value) {
        this.nodeType = 3;
        this.textContent = String(value);
    }
}

class Element {
    constructor(tagName) {
        this.tagName = tagName.toUpperCase();
        this.children = [];
        this.style = {};
        this.listeners = new Map();
        this.className = '';
        this.value = '';
        this.disabled = false;
        this.classList = {
            add: value => this.setClass(value, true),
            remove: value => this.setClass(value, false),
            contains: value => this.className.split(/\s+/).includes(value)
        };
        this._text = '';
    }

    setClass(value, add) {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        if (add) values.add(value);
        else values.delete(value);
        this.className = [...values].join(' ');
    }

    append(...nodes) {
        for (const node of nodes) this.children.push(node instanceof Element || node instanceof TextNode ? node : new TextNode(node));
    }

    appendChild(node) {
        this.append(node);
        return node;
    }

    replaceChildren(...nodes) {
        this.children = [];
        this._text = '';
        this.append(...nodes);
    }

    addEventListener(type, listener) {
        if (!this.listeners.has(type)) this.listeners.set(type, []);
        this.listeners.get(type).push(listener);
    }

    click() {
        for (const listener of this.listeners.get('click') || []) listener({ target: this });
    }

    getElementsByTagName(tagName) {
        const wanted = tagName.toUpperCase();
        const matches = [];
        const visit = node => {
            if (!(node instanceof Element)) return;
            if (node.tagName === wanted) matches.push(node);
            for (const child of node.children) visit(child);
        };
        for (const child of this.children) visit(child);
        return matches;
    }

    getContext() {
        return {
            createLinearGradient() {
                return { addColorStop() {} };
            }
        };
    }

    set textContent(value) {
        this.children = [];
        this._text = String(value);
    }

    get textContent() {
        return this._text + this.children.map(child => child.textContent).join('');
    }

    set innerText(value) {
        this.textContent = value;
    }

    get innerText() {
        return this.textContent;
    }
}

class Document {
    constructor() {
        this.elements = new Map();
    }

    getElementById(id) {
        if (!this.elements.has(id)) this.elements.set(id, new Element(id.includes('Chart') ? 'canvas' : 'div'));
        return this.elements.get(id);
    }

    createElement(tagName) {
        return new Element(tagName);
    }
}

function baseHomeData(overrides = {}) {
    return {
        timestamp: Date.now(),
        latency: 1,
        largest_whales: [],
        conviction_plays: [],
        feed: [],
        volume_chart: { whale: 0, retail: 0 },
        velocity_chart: Array(48).fill(0),
        velocity_timestamps: Array.from({ length: 48 }, (_, index) => 1700000000 + index * 1800),
        sentiment: { bulls: 0, bears: 0, avg_size: 0 },
        scanner: { status: 'ok', last_success: Date.now() / 1000, last_trade: null },
        ...overrides
    };
}

function storage(initial, malformed = false) {
    const values = new Map(Object.entries(initial || {}));
    const removed = [];
    return {
        removed,
        getItem(key) {
            if (malformed) return '{broken';
            return values.has(key) ? values.get(key) : null;
        },
        setItem(key, value) {
            values.set(key, String(value));
        },
        removeItem(key) {
            removed.push(key);
            values.delete(key);
        }
    };
}

function createRuntime({ localStorage, fetch }) {
    const document = new Document();
    const charts = [];
    let clockNow = Date.now();
    let nextTimerId = 1;
    const timers = new Map();
    class RuntimeDate extends Date {
        constructor(...args) {
            super(...(args.length ? args : [clockNow]));
        }
        static now() {
            return clockNow;
        }
    }
    class Chart {
        constructor(context, config) {
            this.context = context;
            this.data = config.data;
            this.options = config.options;
            charts.push(this);
        }
        update() {}
    }
    const context = vm.createContext({
        AbortController,
        Chart,
        Date: RuntimeDate,
        Element,
        Intl,
        Promise,
        URL,
        clearTimeout(id) { timers.delete(id); },
        console: { error() {}, log() {}, warn() {} },
        document,
        fetch,
        localStorage,
        requestAnimationFrame(callback) { callback(); },
        setTimeout(callback, delay = 0) {
            const id = nextTimerId++;
            timers.set(id, { at: clockNow + Math.max(0, Number(delay) || 0), callback });
            return id;
        },
        getSourceConfig(rawSource) {
            if (!rawSource) return { label: 'UNK', class: 'badge-unk' };
            const source = String(rawSource).toLowerCase();
            if (source.includes('tornado') || source.includes('private')) return { label: 'ANON', class: 'badge-anon' };
            if (source.includes('coinbase') || source.includes('binance') || source.includes('kraken')) return { label: 'CEX', class: 'badge-cex' };
            return { label: 'UNK', class: 'badge-unk' };
        }
    });
    function advanceTimers(milliseconds) {
        const target = clockNow + milliseconds;
        while (true) {
            const due = [...timers.entries()]
                .filter(([, timer]) => timer.at <= target)
                .sort((left, right) => left[1].at - right[1].at || left[0] - right[0])[0];
            if (!due) break;
            const [id, timer] = due;
            timers.delete(id);
            clockNow = timer.at;
            timer.callback();
        }
        clockNow = target;
    }
    return { context, document, charts, advanceTimers };
}

function descendants(element, tagName) {
    return element.getElementsByTagName(tagName);
}

function flush() {
    return new Promise(resolve => setImmediate(resolve));
}

test('home renders malicious API strings as text and rejects unsafe links', () => {
    const cached = storage({ poly_dashboard_data: JSON.stringify(baseHomeData()) });
    const runtime = createRuntime({ localStorage: cached, fetch: async () => assert.fail('unexpected fetch') });
    vm.runInContext(scriptFrom('home.html'), runtime.context);
    const attack = '<img src=x onerror="globalThis.pwned=1">';
    runtime.context.input = baseHomeData({
        largest_whales: [{ market_question: attack, total_size: 10, funding_source: attack, bet_link: 'javascript:alert(1)', whale_address: attack }],
        conviction_plays: [{ market_question: attack, avg_size: 5, link: 'data:text/html,attack' }],
        feed: [{ market_question: attack, position: attack, size_usd: 3 }]
    });
    vm.runInContext('renderDashboard(input)', runtime.context);
    const whaleBody = runtime.document.getElementById('largest-whales');
    const convictionBody = runtime.document.getElementById('conviction-plays');
    const ticker = runtime.document.getElementById('ticker-content');
    assert.match(whaleBody.textContent, /<img src=x onerror=/);
    assert.match(convictionBody.textContent, /<img src=x onerror=/);
    assert.match(ticker.textContent, /<img src=x onerror=/);
    assert.equal(descendants(whaleBody, 'img').length, 0);
    assert.equal(descendants(convictionBody, 'img').length, 0);
    assert.equal(descendants(whaleBody, 'a').length, 0);
    assert.equal(descendants(convictionBody, 'a').length, 0);
    assert.equal(runtime.context.pwned, undefined);
});

test('malformed dashboard cache is removed and startup fetch continues', async () => {
    const cache = storage({}, true);
    let fetches = 0;
    const runtime = createRuntime({
        localStorage: cache,
        fetch: async () => {
            fetches++;
            return { ok: true, json: async () => baseHomeData() };
        }
    });
    assert.doesNotThrow(() => vm.runInContext(scriptFrom('home.html'), runtime.context));
    await flush();
    await flush();
    assert.equal(fetches, 1);
    assert.deepEqual(cache.removed, ['poly_dashboard_data']);
    assert.match(runtime.document.getElementById('global-timer').textContent, /^Last Update:/);
});

test('velocity uses 48 matching timestamps without mutating API arrays', () => {
    const cached = storage({ poly_dashboard_data: JSON.stringify(baseHomeData()) });
    const runtime = createRuntime({ localStorage: cached, fetch: async () => assert.fail('unexpected fetch') });
    vm.runInContext(scriptFrom('home.html'), runtime.context);
    const values = Array.from({ length: 52 }, (_, index) => index);
    const timestamps = Array.from({ length: 52 }, (_, index) => 1700000000 + index * 1800);
    const originalValues = [...values];
    const originalTimestamps = [...timestamps];
    runtime.context.values = values;
    runtime.context.timestamps = timestamps;
    vm.runInContext('renderVelocityChart(values, timestamps)', runtime.context);
    assert.deepEqual(values, originalValues);
    assert.deepEqual(timestamps, originalTimestamps);
    assert.equal(runtime.charts[1].data.datasets[0].data.length, 48);
    assert.equal(runtime.charts[1].data.labels.length, 48);
    assert.deepEqual(runtime.charts[1].data.datasets[0].data, values.slice(-48));
});

test('freshness requires ok scanner status and a success under 90 seconds old', () => {
    const cached = storage({ poly_dashboard_data: JSON.stringify(baseHomeData()) });
    const runtime = createRuntime({ localStorage: cached, fetch: async () => assert.fail('unexpected fetch') });
    vm.runInContext(scriptFrom('home.html'), runtime.context);
    runtime.context.nowSeconds = Date.now() / 1000;
    vm.runInContext("setFreshness({ status: 'ok', last_success: nowSeconds - 30 })", runtime.context);
    assert.equal(runtime.document.getElementById('live-status').textContent, 'LIVE');
    vm.runInContext("setFreshness({ status: 'error', last_success: nowSeconds - 30 })", runtime.context);
    assert.equal(runtime.document.getElementById('live-status').textContent, 'STALE');
    vm.runInContext("setFreshness({ status: 'ok', last_success: nowSeconds - 91 })", runtime.context);
    assert.equal(runtime.document.getElementById('live-status').textContent, 'STALE');
});

test('freshness timers expire both live indicators at the 90 second boundary', async () => {
    const home = createRuntime({
        localStorage: storage({ poly_dashboard_data: JSON.stringify(baseHomeData()) }),
        fetch: async () => assert.fail('unexpected home fetch')
    });
    vm.runInContext(scriptFrom('home.html'), home.context);
    assert.equal(vm.runInContext('UPDATE_INTERVAL', home.context), 15000);
    vm.runInContext("clearTimeout(pollTimer); setFreshness({ status: 'ok', last_success: Date.now() / 1000 })", home.context);
    home.advanceTimers(89999);
    assert.equal(home.document.getElementById('live-status').textContent, 'LIVE');
    home.advanceTimers(1);
    assert.equal(home.document.getElementById('live-status').textContent, 'STALE');

    const insider = createRuntime({
        localStorage: storage({}),
        fetch: async () => ({
            ok: true,
            json: async () => ({ timestamp: Date.now(), roster: [], scanner: { status: 'ok', last_success: Date.now() / 1000 } })
        })
    });
    vm.runInContext(scriptFrom('insider.html'), insider.context);
    assert.equal(vm.runInContext('INSIDER_UPDATE_INTERVAL', insider.context), 15000);
    await flush();
    await flush();
    vm.runInContext("clearTimeout(insiderPollTimer); setInsiderFreshness({ status: 'ok', last_success: Date.now() / 1000 })", insider.context);
    insider.advanceTimers(89999);
    assert.equal(insider.document.getElementById('insider-live-status').textContent, 'LIVE');
    insider.advanceTimers(1);
    assert.equal(insider.document.getElementById('insider-live-status').textContent, 'STALE');
});

test('insider freshness stays stale for stopped or error scanner states', async () => {
    const runtime = createRuntime({
        localStorage: storage({}),
        fetch: async () => ({
            ok: true,
            json: async () => ({
                timestamp: Date.now(),
                roster: [],
                scanner: { status: 'stopped', last_success: Date.now() / 1000, last_trade: null }
            })
        })
    });
    vm.runInContext(scriptFrom('insider.html'), runtime.context);
    await flush();
    await flush();
    assert.equal(runtime.document.getElementById('insider-live-status').textContent, 'STALE');
    runtime.context.nowSeconds = Date.now() / 1000;
    vm.runInContext("setInsiderFreshness({ status: 'error', last_success: nowSeconds - 10 })", runtime.context);
    assert.equal(runtime.document.getElementById('insider-live-status').textContent, 'STALE');
    vm.runInContext("setInsiderFreshness({ status: 'ok', last_success: nowSeconds - 10 })", runtime.context);
    assert.equal(runtime.document.getElementById('insider-live-status').textContent, 'LIVE');
});

test('insider polling errors mark freshness stale', async () => {
    const runtime = createRuntime({
        localStorage: storage({}),
        fetch: async () => { throw new Error('offline'); }
    });
    vm.runInContext(scriptFrom('insider.html'), runtime.context);
    await flush();
    await flush();
    assert.equal(runtime.document.getElementById('insider-live-status').textContent, 'STALE');
    assert.equal(runtime.document.getElementById('error-state').style.display, 'block');
});

test('insider text is inert and a newer dossier request wins the race', async () => {
    const pending = [];
    const fetch = async (url, options = {}) => {
        if (url === '/api/insider_data') return { ok: true, json: async () => ({ timestamp: Date.now(), roster: [] }) };
        return new Promise(resolve => pending.push({ url, signal: options.signal, resolve }));
    };
    const runtime = createRuntime({ localStorage: storage({}), fetch });
    vm.runInContext(scriptFrom('insider.html'), runtime.context);
    await flush();
    const attack = '<svg onload="globalThis.pwned=1">';
    runtime.context.roster = [{
        address: '0x1111111111111111111111111111111111111111',
        top_market: attack,
        funding_source: attack,
        last_active_ts: Date.now() / 1000,
        max_bet: 2,
        total_scanned_volume: 4
    }];
    vm.runInContext('renderRoster(roster)', runtime.context);
    const rosterBody = runtime.document.getElementById('roster-body');
    assert.match(rosterBody.textContent, /<svg onload=/);
    assert.equal(descendants(rosterBody, 'svg').length, 0);
    assert.equal(runtime.context.pwned, undefined);

    const first = {
        address: '0x1111111111111111111111111111111111111111',
        source: attack,
        lastTs: 1700000000,
        maxBet: 1,
        scanVol: 2
    };
    const second = { ...first, address: '0x2222222222222222222222222222222222222222', source: 'safe' };
    runtime.context.first = first;
    runtime.context.second = second;
    const firstPromise = vm.runInContext('openDossier(first)', runtime.context);
    assert.equal(runtime.document.getElementById('d-source').textContent, attack);
    assert.equal(descendants(runtime.document.getElementById('d-source'), 'svg').length, 0);
    const secondPromise = vm.runInContext('openDossier(second)', runtime.context);
    assert.equal(pending.length, 2);
    assert.equal(pending[0].signal.aborted, true);
    pending[1].resolve({ ok: true, json: async () => ({ history: [{ market_question: 'new dossier', position: 'Yes', size_usd: 9 }] }) });
    await secondPromise;
    pending[0].resolve({ ok: true, json: async () => ({ history: [{ market_question: 'stale dossier', position: 'No', size_usd: 99 }] }) });
    await firstPromise;
    assert.match(runtime.document.getElementById('d-history').textContent, /new dossier/);
    assert.doesNotMatch(runtime.document.getElementById('d-history').textContent, /stale dossier/);
    assert.equal(runtime.document.getElementById('d-source').textContent, 'safe');
    assert.equal(descendants(runtime.document.getElementById('d-history'), 'svg').length, 0);
});
