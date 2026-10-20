import test from 'node:test';
import assert from 'node:assert/strict';
import { installCounterManifest, keepScreenAwake, unlockAudio } from '../src/counterKiosk.js';

function fakeDoc() {
  const head = { children: [], appendChild(el) { this.children.push(el); el.remove = () => { this.children = this.children.filter(c => c !== el); }; },
    querySelector(sel) { return this.children.find(c => sel.includes(c.rel ? `rel="${c.rel}"` : `name="${c.name}"`)) || null; } };
  const listeners = {};
  return {
    head, visibilityState: 'visible',
    createElement: () => ({ setAttribute(k, v) { this[k] = v; }, getAttribute(k) { return this[k]; } }),
    addEventListener: (e, f) => { listeners[e] = f; }, removeEventListener: (e) => { delete listeners[e]; }, listeners,
  };
}

test('installCounterManifest adds the /counter manifest once and removes it on cleanup', () => {
  const doc = fakeDoc();
  const cleanup = installCounterManifest(doc);
  assert.equal(doc.head.children.find(c => c.rel === 'manifest').href, '/counter/manifest.webmanifest');
  assert.equal(doc.head.children.length, 2);
  installCounterManifest(doc);
  assert.equal(doc.head.children.length, 2, 'not added twice');
  cleanup();
  assert.equal(doc.head.children.length, 0);
});

test('keepScreenAwake requests a screen wake lock and re-acquires after the tab returns', async () => {
  const doc = fakeDoc(); const states = []; let requests = 0; let release;
  const nav = { wakeLock: { request: async type => { assert.equal(type, 'screen'); requests++; return { addEventListener: (e, f) => { release = f; }, release: async () => {} }; } } };
  const stop = keepScreenAwake({ nav, doc, onChange: s => states.push(s) });
  await new Promise(r => setTimeout(r, 0));
  assert.equal(requests, 1); assert.deepEqual(states, ['on']);
  release(); // OS released it (screen off / tab hidden)
  assert.deepEqual(states, ['on', 'off']);
  doc.listeners.visibilitychange();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(requests, 2); assert.deepEqual(states, ['on', 'off', 'on']);
  stop();
  assert.equal(doc.listeners.visibilitychange, undefined);
});

test('keepScreenAwake reports unsupported browsers without throwing', () => {
  const states = [];
  keepScreenAwake({ nav: {}, doc: fakeDoc(), onChange: s => states.push(s) });
  assert.deepEqual(states, ['unsupported']);
});

test('unlockAudio probes un-muted playback and restores volume', async () => {
  const seen = [];
  const ok = { volume: 0.8, muted: false, currentTime: 3, play: async function () { seen.push([this.muted, this.volume]); }, pause() {} };
  assert.equal(await unlockAudio(ok), true);
  assert.deepEqual(seen, [[false, 0]], 'muted autoplay is always allowed, so it must not be used as the probe');
  assert.equal(ok.volume, 0.8); assert.equal(ok.currentTime, 0);
  const blocked = { volume: 1, muted: false, play: async () => { throw new Error('NotAllowedError'); }, pause() {} };
  assert.equal(await unlockAudio(blocked), false);
  assert.equal(blocked.volume, 1);
  assert.equal(await unlockAudio(null), false);
});
