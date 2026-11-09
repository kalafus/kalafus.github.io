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
