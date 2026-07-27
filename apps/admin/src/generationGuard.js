export function captureGeneration(generation, identity, signal) {
  return Object.freeze({ generation, identity, signal });
}

export function generationIsCurrent(capture, generation, identity) {
  return Boolean(capture)
    && !capture.signal?.aborted
    && capture.generation === generation
    && capture.identity === identity;
}
