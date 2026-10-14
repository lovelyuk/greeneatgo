import test from 'node:test';
import assert from 'node:assert/strict';
import { checkoutPresentation, validateSdkData, validSdkMessage, SDK_URL, loadSdk } from './kiwoomSdk.js';
const fields = { TYPE: 'P', PAYMETHOD: 'TOTAL', CPID: 'TEST0001', ORDERNO: 'GE-S-fixture', AMOUNT: '1200', KIWOOM_ENC: 'fixture-hash', PRODUCTNAME: 'ticket', USERID: 'fixture' };
test('official fixed script URL', () => assert.equal(SDK_URL, 'https://ssl-v2.kiwoompay.co.kr/sdk/v1/latest/kiwoompayEnc.js'));
for (const ua of ['iPhone', 'iPad', 'Android', 'Windows Phone', 'SAMSUNG']) test(`mobile ${ua} unchanged`, () => assert.equal(checkoutPresentation({ userAgent: ua }, 'TOTAL'), 'popup'));
test('desktop narrow is frame; desktop iPad touch is popup; BANK stays popup', () => {
 assert.equal(checkoutPresentation({userAgent:'Linux desktop', maxTouchPoints:0}, 'TOTAL'), 'frame');
 assert.equal(checkoutPresentation({userAgent:'Macintosh', maxTouchPoints:5}, 'TOTAL'), 'popup');
 assert.equal(checkoutPresentation({userAgent:'Linux'}, 'BANK'), 'popup');
});
test('strict server bound fields/environment and no callback injection', () => {
 assert.equal(validateSdkData({sdk_mode:'DEV', fields}, {order_id:fields.ORDERNO, amount:1200}).fields.TYPE, 'P');
 for (const change of [{TYPE:'W'}, {PAYMETHOD:'BANK'}, {ORDERNO:'other'}, {AMOUNT:'01200'}, {CPID:'bad'}, {KIWOOM_ENC:'bad\n'}, {CALLBACKSUCC:'evil'}])
  assert.throws(() => validateSdkData({sdk_mode:'DEV', fields:{...fields,...change}}, {order_id:fields.ORDERNO,amount:1200}));
 for (const sdk_mode of ['dev','',null,'OTHER']) assert.throws(() => validateSdkData({sdk_mode,fields}, {order_id:fields.ORDERNO,amount:1200}));
});
test('messages require exact environment origin, source, TYPE and structural result', () => {
 const source = {}; const event = {origin:'https://ssltest-v2.kiwoompay.co.kr',source,data:{TYPE:'SUCCESS',RESULTCODE:'0000'}};
 assert.equal(validSdkMessage(event,'DEV',source),true);
 for (const change of [{origin:'https://ssl-v2.kiwoompay.co.kr'}, {origin:'https://ssltest-v2.kiwoompay.co.kr.evil.invalid'}, {source:{}}, {data:null}, {data:{TYPE:'BOGUS',RESULTCODE:'0000'}}, {data:{RESULTCODE:'0000'}}, {data:{TYPE:'SUCCESS',RESULTCODE:0}}, {data:{TYPE:'FAIL',RESULTCODE:'0000'}}]) assert.equal(validSdkMessage({...event,...change},'DEV',source),false);
 assert.equal(validSdkMessage({...event,data:{TYPE:'FAIL'}},'DEV',source),true);
});
test('script loads once with shared promise and failure is not retried', async () => {
 let created=0, appended;
 const win={}; const doc={createElement(){created++; return {};},head:{appendChild(s){appended=s;}}};
 const one=loadSdk(win,doc), two=loadSdk(win,doc); assert.equal(one,two); assert.equal(created,1); assert.equal(appended.src,SDK_URL);
 appended.onerror(); await assert.rejects(one); assert.equal(loadSdk(win,doc),one);
});
test('successful load is shared and validates official functions before any order', async () => {
 let script, count=0; const sdk={f_setInit(){},f_payTotalLink(){},f_closeFrame(){},f_setFrameSize(){}};
 const win={KiwoomPaySDK:sdk},doc={createElement(){count++;return {};},head:{appendChild(s){script=s;}}};
 const one=loadSdk(win,doc);assert.equal(count,1);script.onload();assert.equal(await one,sdk);assert.equal(loadSdk(win,doc),one);
});
test('late script load after timeout cannot turn a failed preload into success', async () => {
 const original=globalThis.setTimeout; let timeout,script;
 globalThis.setTimeout=callback=>{timeout=callback;return 0;};
 const win={},doc={createElement(){return {};},head:{appendChild(s){script=s;}}};
 try {const pending=loadSdk(win,doc);timeout();await assert.rejects(pending,/SDK/);win.KiwoomPaySDK={f_setInit(){},f_payTotalLink(){},f_closeFrame(){},f_setFrameSize(){}};script.onload();await assert.rejects(loadSdk(win,doc));}
 finally {globalThis.setTimeout=original;}
});
