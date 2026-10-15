import test from 'node:test';
import assert from 'node:assert/strict';
import * as local from '../src/paymentClosure.js';
const owner='11111111-1111-4111-8111-111111111111', pending={order_id:'GE-synthetic-local',amount:1100};
const good=()=>({...pending,user_id:owner,status:'canceled',recovery_action:'locally_abandoned',resumable:false,checkout_url:null,completion:null,local_abandonment:{id:'22222222-2222-4222-8222-222222222222',source:'owner_request',scope:'local_order',outcome:'abandoned',requested_by:owner,requested_at:'2026-10-15T01:02:03.123456+09:00',provider_finality:'unknown',residual_late_approval_possible:true}});
test('local abandonment has its own owner receipt, never verified provider closure',()=>{
 assert.equal(typeof local.validLocalAbandonment,'function');
 assert.equal(local.validLocalAbandonment(good(),pending,owner),true);
 assert.equal(local.verifiedOrderClosure(good(),pending,owner),false);
});
for(const change of [{user_id:'other'},{order_id:'GE-other'},{amount:1101},{status:'done'},{recovery_action:'closed'},{resumable:true},{checkout_url:'https://fixture.invalid'},{completion:{}},{closure:{finality:'verified'}}]) test(`invalid local envelope ${JSON.stringify(change)}`,()=>{assert.equal(local.validLocalAbandonment?.({...good(),...change},pending,owner),false);});
for(const change of [{id:'invalid'},{source:'trusted_provider'},{scope:'order'},{outcome:'canceled'},{requested_by:'other'},{provider_finality:'verified'},{residual_late_approval_possible:false},{requested_at:'2026-02-30T01:02:03Z'},{requested_at:'2026-10-15T01:02:03+99:00'},{requested_at:'2026-10-15T01:02:03'}])test(`invalid local receipt ${JSON.stringify(change)}`,()=>{const v=good();Object.assign(v.local_abandonment,change);assert.equal(local.validLocalAbandonment?.(v,pending,owner),false);});
test('late approval history keeps local receipt but is not permission to retire an active intent',()=>{const v={...good(),recovery_action:'reconcile'};assert.equal(local.validLocalAbandonment?.(v,pending,owner),false);assert.equal(local.validLocalAbandonment?.(v,pending,owner,{history:true}),true);});
