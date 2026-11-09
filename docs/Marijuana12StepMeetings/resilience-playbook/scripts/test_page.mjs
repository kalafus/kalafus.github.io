import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../page.js', import.meta.url), 'utf8');
const node = (properties = {}) => Object.assign({
  hidden: true, events: {},
  addEventListener(name, callback) { this.events[name] = callback; },
}, properties);
const storage = () => {
  const values = new Map();
  return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
};
function visit({ hash = '', session = storage() } = {}) {
  const events = {};
  const principles = [1,2,3,4].map(index => node({
    id: `principle-${index}`, open: false, scrolled: false,
    summary: { focus() { this.focused = true; } },
    querySelector(selector) { assert.equal(selector, 'summary'); return this.summary; },
    scrollIntoView() { this.scrolled = true; },
  }));
  const button = node({ textContent: 'Expand all' });
  const appearance = node({ value: 'system', parentElement: { hidden: true } });
  const document = {
    documentElement: { dataset: {} }, querySelectorAll: () => principles,
    querySelector: () => button, getElementById: () => appearance,
  };
  const window = { location: { hash }, addEventListener: (name, callback) => { events[name] = callback; } };
  runInNewContext(source, { document, window, sessionStorage: session });
  return { principles, button, appearance, document, window, events };
}

test('links between reading views open and focus the matching section', () => {
  const page = visit({ hash: '#principle-3' });
  assert.deepEqual(page.principles.map(p => p.open), [false, false, true, false]);
  assert.equal(page.principles[2].summary.focused, true);
  assert.equal(page.principles[2].scrolled, true);
  page.window.location.hash = '#principle-1';
  page.events.hashchange();
  assert.equal(page.principles[0].open, true);
  assert.equal(page.principles[0].summary.focused, true);
});

test('expand all and print restoration preserve the chosen sections', () => {
  const page = visit();
  page.button.events.click();
  assert(page.principles.every(p => p.open));
  assert.equal(page.button.textContent, 'Collapse all');
  page.button.events.click();
  assert(page.principles.every(p => !p.open));
  page.principles[1].open = page.principles[3].open = true;
  const original = page.principles.map(p => p.open);
  page.events.beforeprint(); page.events.beforeprint();
  assert(page.principles.every(p => p.open));
  page.events.afterprint();
  assert.deepEqual(page.principles.map(p => p.open), original);
  assert.equal(page.button.textContent, 'Expand all');
});

test('appearance survives navigation and can return to system appearance', () => {
  const session = storage();
  const quick = visit({ session });
  quick.appearance.value = 'dark'; quick.appearance.events.change();
  const full = visit({ session });
  assert.equal(full.appearance.value, 'dark');
  assert.equal(full.document.documentElement.dataset.theme, 'dark');
  full.appearance.value = 'system'; full.appearance.events.change();
  assert.equal(full.document.documentElement.dataset.theme, undefined);
  assert.equal(visit({ session }).appearance.value, 'system');
});

test('disabled browser storage leaves controls usable', () => {
  const fail = () => { throw new Error('Storage disabled'); };
  const page = visit({ session: { getItem: fail, setItem: fail, removeItem: fail } });
  assert.equal(page.appearance.parentElement.hidden, false);
  page.appearance.value = 'light'; page.appearance.events.change();
  assert.equal(page.document.documentElement.dataset.theme, 'light');
  page.button.events.click(); assert(page.principles.every(p => p.open));
});

const forwardingSource = readFileSync(new URL('../../page-forward.js', import.meta.url), 'utf8');
const legacyPages = new URL('../../openhearted-not-unguarded/', import.meta.url);
const routes = ['', 'full-guide/', 'light/', 'dark/', 'quick-reference/light/', 'quick-reference/dark/'];

function followOldAddress(route, base, filename = '') {
  const html = readFileSync(new URL(`${route}index.html`, legacyPages), 'utf8');
  const href = html.match(/id="page-destination" href="([^"]+)"/)[1];
  const original = new URL(`openhearted-not-unguarded/${route}${filename}?source=saved%20link#principle-3`, base);
  const link = { href: new URL(href, original).href };
  let replaced;
  runInNewContext(forwardingSource, {
    URL,
    document: { getElementById(id) { assert.equal(id, 'page-destination'); return link; } },
    window: { location: { search: original.search, hash: original.hash, replace(href) { replaced = href; } } },
  });
  assert.equal(replaced, new URL(`resilience-playbook/${route}${original.search}${original.hash}`, base).href);
  assert.equal(link.href, replaced);
  const fallback = html.match(/<noscript><meta http-equiv="refresh" content="0; url=([^"]+)"><\/noscript>/)[1];
  assert.equal(new URL(fallback, original).href, new URL(`resilience-playbook/${route}`, base).href);
  return replaced;
}

test('every old reading and download address forwards with its query and section intact', () => {
  for (const route of routes) {
    for (const filename of ['', 'index.html']) followOldAddress(route, 'https://kalafus.github.io/Marijuana12StepMeetings/', filename);
  }
  const destination = followOldAddress('full-guide/', 'https://kalafus.github.io/Marijuana12StepMeetings/');
  const guide = visit({ hash: new URL(destination).hash });
  assert.equal(guide.principles[2].open, true);
  assert.equal(guide.principles[2].summary.focused, true);
});

test('old file addresses also forward when previewing the site locally', () => {
  for (const route of routes) followOldAddress(route, new URL('../../', import.meta.url).href, 'index.html');
});
