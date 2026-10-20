import { rewardsApi } from '../api/services.js';

export function createRewardsController({shell,pagehead,esc,link,render,current,getAccount}) {
  let generation=0,key='',loaded=false,loading=false,error='',notice='',wallet=null,item=null,items=[],rows=[],nextCursor=null,review=false,receipt=null,query='',category='';
  const pending=new Map();
  const destination=()=>current().split('/')[1]||'';
  const routeKey=()=>JSON.stringify([current(),getAccount()?.id,query,category]);
  const stamp=value=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  function invalidate(){generation++;key='';loaded=false;loading=false;error='';notice='';wallet=null;item=null;items=[];rows=[];nextCursor=null;review=false;receipt=null;}
  function reset(){invalidate();pending.clear();query='';category='';}
  const button=(action,label,disabled=false)=>`<button class="secondary" data-rewards-action="${action}" ${loading||disabled?'disabled':''}>${label}</button>`;
  async function load(more=false){
    const expected=routeKey(),token=++generation,route=destination(),signed=!!getAccount();
    key=expected;loading=true;error='';
    if(!more){loaded=false;notice='';review=false;receipt=null;}
    try {
      const params=more&&nextCursor?{cursor:nextCursor}:{};
      const [content,w]=await Promise.all([
        route==='history'?(signed?rewardsApi.history(params):null):route==='ledger'?(signed?rewardsApi.ledger(params):null):route?rewardsApi.get(route):rewardsApi.catalogue({...params,query,...(category?{category}:{})}),
        signed?rewardsApi.wallet():null,
      ]);
      if(token!==generation||expected!==routeKey())return;
      wallet=w;
      if(route==='history'||route==='ledger'){rows=more?[...rows,...content.items]:content?.items||[];nextCursor=content?.next_cursor;}
      else if(route)item=content;
      else{items=more?[...items,...content.items]:content.items;nextCursor=content.next_cursor;}
      loaded=true;
    } catch(e){if(token===generation&&expected===routeKey()){error=e.message;loaded=true;}}
    finally{if(token===generation&&expected===routeKey()){loading=false;render();}}
  }
  function ensure(){if(key!==routeKey())load();}
  function summary(){
    if(!wallet&&getAccount())return '<section class="panel"><p>Current coin balance is unavailable. Use Refresh rewards to reload it.</p></section>';
    if(!wallet)return `<section class="panel"><p>${link('Sign in','login','ghost')} to view your virtual coins and sandbox history.</p></section>`;
    return `<div class="grid3"><section class="panel stat"><p class="small">Available coins</p><strong class="num" data-wallet-balance>${wallet.balance}</strong></section><section class="panel stat"><p class="small">Lifetime coins earned</p><strong class="num">${wallet.lifetime_earned}</strong></section><section class="panel stat"><p class="small">Your tier</p><strong class="num">${esc(wallet.tier.name)}</strong><p>${wallet.next_tier?`${wallet.coins_to_next_tier} more earned coins to ${esc(wallet.next_tier.name)}`:'Highest tier reached'}</p></section></div><p class="small">Earn ${wallet.lesson_completion_coins} virtual coins for each first-time lesson completion. Retakes add no extra coins. Tiers use lifetime earnings; spending does not lower your tier.</p>`;
  }
  function navigation(){return `<div class="flex" style="margin:20px 0">${link('Catalogue','marketplace','secondary')}${getAccount()?link('Redemption history','marketplace/history','secondary')+link('Coin ledger','marketplace/ledger','secondary'):''}${link('Earn coins in Academy','academy','secondary')}${button('refresh','Refresh rewards')}</div>`;}
  function catalogue(){return `<div class="grid2"><label class="field">Search rewards<input id="rewards-query" maxlength="100" value="${esc(query)}"></label><label class="field">Reward category<select id="rewards-category"><option value="">All categories</option>${['digital','learning','merchandise'].map(c=>`<option value="${c}" ${category===c?'selected':''}>${c}</option>`).join('')}</select></label></div><div class="grid3">${items.map(i=>`<article class="panel"><span class="pill neutral">Sandbox · ${esc(i.category)}</span><h2>${esc(i.name)}</h2><p>${esc(i.description)}</p><strong>${i.cost} virtual coins</strong><p>${i.remaining} sandbox units remaining</p>${link('View reward','marketplace/'+i.id,'secondary')}</article>`).join('')||'<section class="panel">No rewards match this view.</section>'}</div>${nextCursor?button('more','Load more rewards'):''}`;}
  function detail(){
    const signed=!!getAccount(),verified=!!getAccount()?.email_verified,affordable=wallet&&wallet.balance>=item.cost;
    return `<section class="panel"><span class="pill neutral">Sandbox · ${esc(item.category)}</span><h2>${esc(item.name)}</h2><p>${esc(item.description)}</p><p><strong>${item.cost} virtual coins</strong> · ${item.remaining} sandbox units remaining</p>${!signed?link('Sign in to redeem','login'):!verified?'<p class="callout">Verify your email before redeeming virtual coins.</p>':!wallet?'<p class="callout">Refresh rewards to load your current coin balance.</p>':!item.remaining?'<p class="callout">This sandbox item is sold out.</p>':!affordable?`<p class="callout">You need ${item.cost-wallet.balance} more virtual coins.</p>${link('Complete a lesson','academy','secondary')}`:button('review','Review sandbox redemption')}${review?`<section class="callout" aria-label="Confirm sandbox redemption"><h3>Confirm sandbox redemption</h3><p>Spend ${item.cost} virtual coins for ${esc(item.name)}? One sandbox inventory unit will be used.</p><p>This creates a simulated history record. No gift card, shipment, booking or paid feature will be delivered.</p><button class="primary" data-rewards-action="confirm" ${loading?'disabled':''}>Confirm sandbox redemption</button>${button('cancel','Cancel')}</section>`:''}${receipt?`<section class="callout" aria-label="Sandbox receipt"><h3>Sandbox redemption recorded</h3><p>${esc(receipt.item_name)} · ${receipt.cost} virtual coins spent.</p><p>Recorded balance after this redemption: ${receipt.balance_after} virtual coins.</p><p>No real reward was ordered or fulfilled.</p>${link('View redemption history','marketplace/history','secondary')}</section>`:''}</section>`;
  }
  function history(){return `<section class="panel tablewrap"><h2>Your sandbox redemptions</h2><table><thead><tr><th>Reward</th><th>Coins spent</th><th>Status</th><th>Recorded</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.item_name)}</td><td>${r.cost}</td><td>Sandbox confirmed · no fulfillment</td><td>${esc(stamp(r.created_at))}</td></tr>`).join('')||'<tr><td colspan="4">No sandbox redemptions yet.</td></tr>'}</tbody></table>${nextCursor?button('more','Load earlier redemptions'):''}</section>`;}
  function ledger(){return `<section class="panel tablewrap"><h2>Your coin ledger</h2><table><thead><tr><th>Event</th><th>Change</th><th>Balance after event</th><th>Recorded</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.kind==='lesson_completion'?'First lesson completion':'Sandbox redemption'}</td><td>${r.delta>0?'+':''}${r.delta}</td><td>${r.balance_after}</td><td>${esc(stamp(r.created_at))}</td></tr>`).join('')||'<tr><td colspan="4">No coin events yet. Complete a lesson to earn virtual coins.</td></tr>'}</tbody></table>${nextCursor?button('more','Load earlier coin events'):''}</section>`;}
  function page(){
    const route=destination();
    let body=pagehead('Virtual rewards','Rewards sandbox','Earn virtual coins through learning and try simulated redemptions.');
    body+='<p class="callout"><strong>Sandbox only.</strong> Coins have no cash value. Redemption records do not send real gift cards, shipments, bookings or activate paid features.</p>';
    if(['history','ledger'].includes(route)&&!getAccount())return shell('marketplace',body+link('Sign in to view your history','login'));
    if(key!==routeKey()||!loaded)return shell('marketplace',body+'<section class="panel" role="status">Loading rewards…</section>');
    if(error)return shell('marketplace',body+`<section class="panel" role="alert"><p>${esc(error)}</p>${button('refresh','Retry rewards')}</section>`);
    body+=summary()+navigation()+(notice?`<p class="callout" role="alert">${esc(notice)}</p>`:'');
    return shell('marketplace',body+(route==='history'?history():route==='ledger'?ledger():route?detail():catalogue()));
  }
  async function click(b){
    if(b.disabled||loading)return;
    const action=b.dataset.rewardsAction;
    if(action==='refresh'){load();return;}
    if(action==='more'){load(true);return;}
    if(action==='review'){review=true;receipt=null;notice='';render();return;}
    if(action==='cancel'){review=false;notice='';render();return;}
    if(action!=='confirm')return;
    const expected=routeKey(),token=generation,input={item_id:item.id,item_version:item.version};
    const signature=JSON.stringify([getAccount()?.id,input]);
    if(!pending.has(signature))pending.set(signature,crypto.randomUUID());
    loading=true;notice='';render();
    try {
      const result=await rewardsApi.redeem(input,pending.get(signature));
      pending.delete(signature);
      if(token!==generation||expected!==routeKey())return;
      receipt=result;review=false;
      try {
        const [w,i]=await Promise.all([rewardsApi.wallet(),rewardsApi.get(item.id)]);
        if(token===generation&&expected===routeKey()){wallet=w;item=i;}
      } catch {if(token===generation&&expected===routeKey()){wallet=null;notice='Redemption recorded. Refresh rewards to load your current balance and stock.';}}
    } catch(e){if(token===generation&&expected===routeKey())notice=e.message;}
    finally{if(token===generation&&expected===routeKey()){loading=false;render();}}
  }
  function change(input){if(input.id==='rewards-query')query=input.value;else if(input.id==='rewards-category')category=input.value;else return;load();}
  return {page,ensure,reset,click,change,deactivate(){if(key)invalidate();}};
}
