import test from 'node:test';
import assert from 'node:assert/strict';
import { validLocalAbandonment } from '../src/paymentClosure.js';
const user='00000000-0000-4000-8000-000000000001';
const pending={order_id:'GE-synthetic-operator',amount:100};
const r={...pending,user_id:user,status:'canceled',recovery_action:'locally_abandoned',resumable:false,checkout_url:null,completion:null,
 local_abandonment:{id:'00000000-0000-4000-8000-000000000002',source:'manual_database_operator',scope:'local_order',outcome:'abandoned',actor_kind:'database_operator',reason:'manual_local_stop_unknown_provider',requested_at:'2026-10-16T00:00:00Z',evidence_sha256:'b'.repeat(64),provider_finality:'unknown',residual_late_approval_possible:true}};
test('operator receipt retires only exact matching local pending; never verified PG finality',()=>{
 assert.equal(validLocalAbandonment(r,pending,user),true);
 for(const change of [{requested_by:user},{source:'owner_request'},{actor_kind:'customer'},{reason:'provider_failed'},{evidence_sha256:'bad'},{provider_finality:'verified'},{acknowledge_provider_uncertainty:true}])
  assert.equal(validLocalAbandonment({...r,local_abandonment:{...r.local_abandonment,...change}},pending,user),false,JSON.stringify(change));
 assert.equal(validLocalAbandonment(r,{...pending,amount:101},user),false);
 assert.equal(validLocalAbandonment(r,{...pending,order_id:'GE-other'},user),false);
 assert.equal(validLocalAbandonment({...r,recovery_action:'reconcile'},pending,user),false);
 assert.equal(validLocalAbandonment({...r,recovery_action:'reconcile'},pending,user,{history:true}),true);
});
