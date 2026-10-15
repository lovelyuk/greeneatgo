import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validSdkMessage} from '../src/kiwoomSdk.js';
const source={};
const event={origin:'https://ssltest-v2.kiwoompay.co.kr',source,data:{TYPE:'FAIL'}};
test('official TYPE-only FAIL is normal ended, without invented 9999',()=>assert.equal(validSdkMessage(event,'DEV',source,'GE-order'),true));
test('optional contradictory ORDERNO cannot authorize an ended return',()=>{
 assert.equal(validSdkMessage({...event,data:{TYPE:'FAIL',ORDERNO:'GE-foreign'}},'DEV',source,'GE-order'),false);
 assert.equal(validSdkMessage({...event,data:{TYPE:'FAIL',ORDERNO:'GE-order'}},'DEV',source,'GE-order'),true);
});
test('merchant bridge is a token-free static artifact with no payment write authority',()=>{
 const html=readFileSync(new URL('../public/payment-return/index.html',import.meta.url),'utf8');
 const script=readFileSync(new URL('../public/payment-return.js',import.meta.url),'utf8');
 assert.match(html,/script-src 'self'/);assert.match(html,/no-referrer/);assert.match(script,/BroadcastChannel/);
 assert.doesNotMatch(script,/fetch\(|XMLHttpRequest|localStorage|sessionStorage|opener\.|access_token/);
 const config=JSON.parse(readFileSync(new URL('../vercel.json',import.meta.url),'utf8'));
 assert.ok(config.rewrites.some(r=>r.source==='/payment-return'&&r.destination==='/payment-return/index.html'));
});
