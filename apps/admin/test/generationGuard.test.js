import test from 'node:test';
import assert from 'node:assert/strict';
import { captureGeneration, generationIsCurrent } from '../src/generationGuard.js';

test('generation guard requires generation and account token identity', () => {
  const capture = captureGeneration(7, 'tenant-a-token');
  assert.equal(generationIsCurrent(capture, 7, 'tenant-a-token'), true);
  assert.equal(generationIsCurrent(capture, 8, 'tenant-a-token'), false);
  assert.equal(generationIsCurrent(capture, 7, 'tenant-b-token'), false);
});

test('generation guard rejects aborted reads and writes', () => {
  const controller = new AbortController();
  const capture = captureGeneration(2, 'tenant-a-token', controller.signal);
  assert.equal(generationIsCurrent(capture, 2, 'tenant-a-token'), true);
  controller.abort();
  assert.equal(generationIsCurrent(capture, 2, 'tenant-a-token'), false);
});
