const test = require('node:test');
const assert = require('node:assert/strict');
const { APP_URL, isAppUrl, popupAction } = require('../src/navigation');

test('the window opens the live admin web', () => {
  assert.equal(APP_URL, 'https://greeneatgo.vercel.app/');
});

test('only the admin origin may load in the main window', () => {
  assert.equal(isAppUrl('https://greeneatgo.vercel.app/?from=2026-10-01'), true);
  assert.equal(isAppUrl('https://greeneatgo.vercel.app.evil.com/'), false);
  assert.equal(isAppUrl('http://greeneatgo.vercel.app/'), false);
  assert.equal(isAppUrl('https://example.com/'), false);
  assert.equal(isAppUrl('not a url'), false);
});

test('popups: app documents stay in-app, other sites go to the browser, odd schemes are blocked', () => {
  assert.equal(popupAction('about:blank'), 'window'); // receipt/PDF preview window the admin opens first
  assert.equal(popupAction('https://greeneatgo.vercel.app/terms.html'), 'window');
  assert.equal(popupAction('blob:https://greeneatgo.vercel.app/1d4e-…'), 'window');
  assert.equal(popupAction('blob:https://evil.example/1'), 'deny');
  assert.equal(popupAction('https://www.popbill.com/x'), 'external');
  assert.equal(popupAction('mailto:greeneat0419@naver.com'), 'external');
  assert.equal(popupAction('file:///C:/Windows/system32'), 'deny');
  assert.equal(popupAction('javascript:alert(1)'), 'deny');
});
