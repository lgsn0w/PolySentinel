const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/funding.js'), 'utf8');
const wallet = '0x' + 'a'.repeat(40);
const peer = '0x' + 'b'.repeat(40);
const token = '0x' + 'c'.repeat(40);
const hash = '0x' + 'd'.repeat(64);

class Element {
    constructor(tag) {
        this.tag = tag;
        this.children = [];
        this.value = '';
        this.hidden = false;
        this.listeners = {};
        this.text = '';
    }
    append(...nodes) { this.children.push(...nodes); }
    appendChild(node) { this.children.push(node); return node; }
    replaceChildren(...nodes) { this.children = nodes; this.text = ''; }
    addEventListener(type, callback) { this.listeners[type] = callback; }
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return this.text + this.children.map(node => node instanceof Element ? node.textContent : String(node)).join(''); }
}

function runtime(fetch) {
    const elements = new Map();
    const timers = new Map();
    let nextTimer = 0;
    const document = {
        getElementById(id) { if (!elements.has(id)) elements.set(id, new Element('div')); return elements.get(id); },
        createElement(tag) { return new Element(tag); }
    };
    const context = vm.createContext({
        document, fetch, window: { location: { search: '' } }, URLSearchParams, Date,
        AbortController, console, setTimeout(fn, delay) { const id = ++nextTimer; timers.set(id, { fn, delay }); return id; },
        clearTimeout(id) { timers.delete(id); }
    });
    vm.runInContext(source, context);
    return { context, document, timers };
}

function report(overrides = {}) {
    return { address: wallet, status: 'partial', configured: true, checked_at: 1700000000,
        edges: [{ sender: peer, receiver: wallet, amount: '9007199254740993.123456789',
            asset: '<img src=x onerror=attack()>', contract: token, timestamp: 1700000000,
            hash, kind: 'erc20', depth: 0, ancestry: true, identity_ambiguous: true }],
        summary: [], warnings: [], limitations: [], coverage: [], relationships: [], behavior: [], ...overrides };
}

function descendants(element, tag) {
    const found = [];
    for (const child of element.children) if (child instanceof Element) {
        if (child.tag === tag) found.push(child);
        found.push(...descendants(child, tag));
    }
    return found;
}

test('funding renders untrusted text safely and keeps decimal strings exact', () => {
    const app = runtime(async () => assert.fail('Unexpected request'));
    app.context.input = report({ warnings: ['<svg onload=attack()>'] });
    app.context.wallet = wallet;
    vm.runInContext('fundingAddress = wallet; renderFunding(input)', app.context);
    const evidence = app.document.getElementById('funding-evidence');
    assert.match(evidence.textContent, /9007199254740993\.123456789/);
    assert.match(evidence.textContent, /<img src=x/);
    assert.match(evidence.textContent, /Event identity incomplete/);
    assert.equal(descendants(evidence, 'img').length, 0);
    assert.equal(descendants(app.document.getElementById('funding-warnings'), 'svg').length, 0);
    assert.equal(app.document.getElementById('funding-export').href, `/api/funding/${wallet}?download=1`);
});

test('ancestry paths exclude unrelated outgoing neighborhood edges', () => {
    const app = runtime(async () => assert.fail('Unexpected request'));
    app.context.input = report({ edges: [{ ...report().edges[0], classification: { category: 'direct_transfer' } }, { ...report().edges[0], sender: peer, receiver: token, ancestry: false, depth: 1, asset: 'UNRELATED', classification: { category: 'direct_transfer' } }] });
    app.context.wallet = wallet;
    vm.runInContext('fundingAddress = wallet; renderFunding(input)', app.context);
    assert.doesNotMatch(app.document.getElementById('funding-graph').textContent, /UNRELATED/);
    assert.match(app.document.getElementById('funding-graph').textContent, /1 of 1/);
    assert.match(app.document.getElementById('funding-evidence').textContent, /UNRELATED/);
});

test('trading-related and stale edges never appear as simple-transfer paths', () => {
    const app = runtime(async () => assert.fail('Unexpected request'));
    app.context.input = report({ edges: [{ ...report().edges[0], classification: { category: 'trade_related' } }, { ...report().edges[0], classification: { category: 'direct_transfer' }, receipt_stale: true }] });
    app.context.wallet = wallet;
    vm.runInContext('fundingAddress = wallet; renderFunding(input)', app.context);
    assert.match(app.document.getElementById('funding-graph').textContent, /0 of 0/);
    assert.match(app.document.getElementById('funding-evidence').textContent, /Trading-related/);
});

test('classification filters preserve evidence and render reasons as inert text', () => {
    const app = runtime(async () => assert.fail('Unexpected request'));
    app.context.input = report({ edges: [{ ...report().edges[0], classification: { category: 'trade_related', reason: '<svg onload=attack()>' } }, { ...report().edges[0], amount: '2', classification: { category: 'unknown', reason: 'not fetched' } }] });
    app.context.wallet = wallet;
    vm.runInContext('fundingAddress = wallet; renderFunding(input)', app.context);
    const container = app.document.getElementById('funding-evidence');
    assert.match(container.textContent, /<svg onload=/);
    assert.equal(descendants(container, 'svg').length, 0);
    app.document.getElementById('funding-category').value = 'unknown';
    vm.runInContext('renderEvidence()', app.context);
    assert.match(container.textContent, /1 of 1/);
    assert.doesNotMatch(container.textContent, /Trading-related/);
});

test('classifying saved data uses an explicit action and polls the classification job', async () => {
    const calls = [];
    const app = runtime(async (url, options) => {
        calls.push({ url, options });
        return { ok: true, json: async () => options.method === 'POST' ? { status: 'queued' } : report({ classification: { status: 'queued', counts: {}, direct_transfers: [] } }) };
    });
    app.context.wallet = wallet;
    await vm.runInContext("loadFunding(wallet, true, 'classify')", app.context);
    assert.equal(JSON.parse(calls[0].options.body).action, 'classify');
    assert.ok([...app.timers.values()].some(timer => timer.delay === 5000));
    assert.match(app.document.getElementById('classification-status').textContent, /queued/);
});

test('invalid wallet and transaction values never become executable links', () => {
    const app = runtime(async () => assert.fail('Unexpected request'));
    app.context.input = report({ edges: [{ ...report().edges[0], sender: 'javascript:alert(1)', hash: 'javascript:alert(1)', contract: 'data:text/html,x' }] });
    app.context.wallet = wallet;
    vm.runInContext('fundingAddress = wallet; renderFunding(input)', app.context);
    const links = descendants(app.document.getElementById('funding-evidence'), 'a');
    assert.ok(links.every(link => link.href.startsWith('https://polygonscan.com/address/') || link.href.startsWith('https://polygonscan.com/tx/')));
    assert.match(app.document.getElementById('funding-evidence').textContent, /Invalid transaction/);
});

test('a newer wallet report wins the race and aborts the old request', async () => {
    const pending = [];
    const app = runtime((url, options) => new Promise(resolve => pending.push({ url, options, resolve })));
    app.context.wallet = wallet;
    app.context.peer = peer;
    const first = vm.runInContext('loadFunding(wallet)', app.context);
    const second = vm.runInContext('loadFunding(peer)', app.context);
    assert.equal(pending[0].options.signal.aborted, true);
    pending[1].resolve({ ok: true, json: async () => report({ address: peer, status: 'complete' }) });
    await second;
    pending[0].resolve({ ok: true, json: async () => report({ address: wallet, status: 'error' }) });
    await first;
    assert.match(app.document.getElementById('funding-status').textContent, /Bounded investigation finished/);
    assert.equal(app.document.getElementById('funding-export').href, `/api/funding/${peer}?download=1`);
});

test('queue action uses JSON POST and only active jobs schedule a refresh', async () => {
    const calls = [];
    const app = runtime(async (url, options) => {
        calls.push({ url, options });
        return { ok: true, json: async () => options.method === 'POST' ? { status: 'queued' } : report({ status: 'queued' }) };
    });
    app.context.wallet = wallet;
    await vm.runInContext('loadFunding(wallet, true)', app.context);
    assert.equal(calls[0].options.method, 'POST');
    assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
    assert.equal(calls.length, 2);
    assert.ok([...app.timers.values()].some(timer => timer.delay === 5000));
});

test('API key failures are clear and do not fabricate an investigation', async () => {
    let count = 0;
    const app = runtime(async () => {
        count++;
        return count === 1 ? { ok: false, json: async () => ({ status: 'no_key', error: 'Configure ETHERSCAN_API_KEY' }) }
            : { ok: true, json: async () => report({ status: 'not_requested', configured: false, checked_at: null, edges: [] }) };
    });
    app.context.wallet = wallet;
    await vm.runInContext('loadFunding(wallet, true)', app.context);
    assert.equal(app.document.getElementById('funding-status').textContent, 'Configure ETHERSCAN_API_KEY');
    assert.equal(app.document.getElementById('funding-export').hidden, true);
    assert.equal(app.timers.size, 0);
});
