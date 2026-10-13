import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as safety from '../src/purchaseSafety.js';

test('published documents allow access independently of disclosure completeness', () => {
  const docs = ['terms', 'privacy'].map(name => readFileSync(new URL(`../public/${name}.html`, import.meta.url), 'utf8'));
  assert.equal(typeof safety.publishedLegalAvailable, 'function');
  assert.equal(safety.publishedLegalAvailable(docs), true);
  assert.equal(safety.legalDocumentsReady(docs), false, 'access is not compliance certification');
});

test('missing or wrong legal documents still fail closed', () => {
  assert.equal(typeof safety.publishedLegalAvailable, 'function');
  for (const docs of [null, [], ['', ''], ['이용약관', '개인정보'], ['wrong document'.repeat(5), 'wrong document'.repeat(5)]]) {
    assert.equal(safety.publishedLegalAvailable(docs), false);
  }
});
