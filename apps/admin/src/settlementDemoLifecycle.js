function abortError(message = 'Obsolete settlement demo request') {
  const error = new Error(message);
  error.name = 'AbortError';
  return error;
}

export function isLifecycleAbort(error) {
  return error?.name === 'AbortError';
}

/**
 * A small, React-independent lifecycle controller for the settlement demo.
 * Captures are valid only for the mounted token generation that created them.
 */
export function createSettlementDemoLifecycle() {
  let identity;
  let generation = 0;
  let mounted = false;
  let actionLock = null;
  const reads = new Map();

  function isCurrent(capture) {
    return Boolean(capture)
      && mounted
      && capture.identity === identity
      && capture.generation === generation
      && !capture.signal?.aborted;
  }

  function abortReads() {
    for (const controller of reads.values()) controller.abort();
    reads.clear();
  }

  function activate(nextIdentity) {
    abortReads();
    generation += 1;
    identity = nextIdentity;
    mounted = true;
    actionLock = null;
    return Object.freeze({ identity, generation });
  }

  function invalidate() {
    abortReads();
    mounted = false;
    generation += 1;
    actionLock = null;
  }

  function capture(signal) {
    return Object.freeze({ identity, generation, signal });
  }

  function beginRead(channel) {
    reads.get(channel)?.abort();
    const controller = new AbortController();
    reads.set(channel, controller);
    return {
      capture: capture(controller.signal),
      signal: controller.signal,
      finish() {
        if (reads.get(channel) === controller) reads.delete(channel);
      },
    };
  }

  function acquireAction() {
    if (!mounted || actionLock) return null;
    const action = capture();
    actionLock = action;
    return action;
  }

  function releaseAction(action) {
    if (actionLock === action && isCurrent(action)) actionLock = null;
  }

  function requireCurrent(captured) {
    if (!isCurrent(captured)) throw abortError();
  }

  return {
    activate,
    invalidate,
    capture,
    beginRead,
    acquireAction,
    releaseAction,
    requireCurrent,
    isCurrent,
    get locked() { return Boolean(actionLock); },
  };
}
