// Same-origin nonce channel, no opener access, tokens, order data or API writes.
'use strict';
const match = /^#(cancel|fail|success)\.([0-9a-f]{32})$/.exec(location.hash);
history.replaceState(null, '', location.pathname);
if (match && !location.search) {
  try {
    const channel = new BroadcastChannel(`greeneat-checkout-return:${match[2]}`);
    channel.postMessage({ type: 'greeneat_checkout_return', kind: match[1], nonce: match[2] });
    setTimeout(() => { channel.close(); window.close(); }, 100);
  } catch { /* Keep the visible manual return instruction; never invent success. */ }
}
