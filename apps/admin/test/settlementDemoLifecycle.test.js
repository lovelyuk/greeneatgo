import test from 'node:test';
import assert from 'node:assert/strict';
import { openDocumentInNewWindow } from '../src/settlementApi.js';
import { createSettlementDemoLifecycle, isLifecycleAbort } from '../src/settlementDemoLifecycle.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test('token generation and unmount reject deferred stale completions and abort reads', async () => {
  const lifecycle = createSettlementDemoLifecycle();
  lifecycle.activate('token-a');
  const tokenARead = lifecycle.beginRead('state');
  const tokenACompletion = deferred();
  const observed = tokenACompletion.promise.then(() => lifecycle.isCurrent(tokenARead.capture));

  lifecycle.activate('token-b');
  assert.equal(tokenARead.signal.aborted, true);
  tokenACompletion.resolve();
  assert.equal(await observed, false);

  const tokenBRead = lifecycle.beginRead('document');
  const tokenBCompletion = deferred();
  const afterUnmount = tokenBCompletion.promise.then(() => lifecycle.isCurrent(tokenBRead.capture));
  lifecycle.invalidate();
  assert.equal(tokenBRead.signal.aborted, true);
  tokenBCompletion.resolve();
  assert.equal(await afterUnmount, false);
});

test('obsolete read in one generation is aborted without invalidating its replacement', () => {
  const lifecycle = createSettlementDemoLifecycle();
  lifecycle.activate('token-a');
  const first = lifecycle.beginRead('state');
  const second = lifecycle.beginRead('state');
  assert.equal(first.signal.aborted, true);
  assert.equal(lifecycle.isCurrent(first.capture), false);
  assert.equal(second.signal.aborted, false);
  assert.equal(lifecycle.isCurrent(second.capture), true);
  // A late finally from the old request must not remove/abort the current read.
  first.finish();
  assert.equal(lifecycle.isCurrent(second.capture), true);
});

test('action gate is synchronous and a stale completion cannot release the current lock', () => {
  const lifecycle = createSettlementDemoLifecycle();
  lifecycle.activate('token-a');
  const staleAction = lifecycle.acquireAction();
  assert.ok(staleAction);
  assert.equal(lifecycle.acquireAction(), null, 'rapid second action is rejected synchronously');

  lifecycle.activate('token-b');
  const currentAction = lifecycle.acquireAction();
  assert.ok(currentAction);
  lifecycle.releaseAction(staleAction);
  assert.equal(lifecycle.locked, true, 'token-a finally cannot clear token-b lock');
  assert.equal(lifecycle.acquireAction(), null);
  lifecycle.releaseAction(currentAction);
  assert.equal(lifecycle.locked, false);
});

test('mutation-style captures are invalidated but are not represented by abortable read signals', () => {
  const lifecycle = createSettlementDemoLifecycle();
  lifecycle.activate('token-a');
  const mutation = lifecycle.acquireAction();
  assert.equal(mutation.signal, undefined);
  lifecycle.activate('token-b');
  assert.equal(lifecycle.isCurrent(mutation), false);
});

test('stale document completion closes its popup and never navigates it', async () => {
  const lifecycle = createSettlementDemoLifecycle();
  lifecycle.activate('token-a');
  const action = lifecycle.acquireAction();
  const request = lifecycle.beginRead('document');
  const response = deferred();
  const handle = {
    opener: {},
    closed: false,
    navigations: [],
    location: { replace(url) { handle.navigations.push(url); } },
    close() { this.closed = true; },
  };

  const opening = openDocumentInNewWindow(() => handle, async () => {
    const url = await response.promise;
    lifecycle.requireCurrent(action);
    lifecycle.requireCurrent(request.capture);
    return url;
  });
  lifecycle.invalidate();
  response.resolve('https://example.test/document');

  await assert.rejects(opening, (error) => isLifecycleAbort(error));
  assert.equal(handle.closed, true);
  assert.deepEqual(handle.navigations, []);
});
