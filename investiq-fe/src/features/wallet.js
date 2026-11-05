import { walletApi } from '../api/services.js';

export function createWalletController({ getAccount, current, render, shell, pagehead, link, esc, icon }) {
  let owner='', generation=0, data=null, loading=false, error='', attempted=false, refreshed=0, timer=null;
  const amount=value=>'₹'+Number(value).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const tone=value=>Number(value)>0?'wallet-gain':Number(value)<0?'wallet-loss':'';
  const signed=value=>(Number(value)>0?'+':Number(value)<0?'−':'')+amount(Math.abs(Number(value)));
  const active=()=>getAccount()?.role!=='admin'&&getAccount()&&Boolean(document.querySelector('[data-wallet-shortcut]'));
  function reset(){clearTimeout(timer);timer=null;owner='';generation++;data=null;loading=false;error='';attempted=false;refreshed=0;}
  async function load(){
    if(!active()||loading)return;
    const id=getAccount().id,token=++generation;
    owner=id;loading=true;error='';
    try{const result=await walletApi.get();if(token!==generation||id!==getAccount()?.id)return;data=result;}
    catch(e){if(token===generation&&id===getAccount()?.id)error=e.status===404?'Your wallet is temporarily unavailable. Please try again shortly.':e.message||'Wallet could not be loaded.';}
    finally{if(token===generation&&id===getAccount()?.id){loading=false;attempted=true;refreshed=Date.now();if(active()){if(current().split('/')[0]==='wallet')render();else{const shortcutNode=document.querySelector('[data-wallet-shortcut]');if(shortcutNode)shortcutNode.outerHTML=shortcut();}}}}
  }
  function ensure(){
    clearTimeout(timer);timer=null;
    if(!active())return;
    if(owner&&owner!==getAccount().id)reset();
    if(!loading&&(!attempted||Date.now()-refreshed>=60000))load();
    timer=setTimeout(()=>{if(active())load();},60000);
  }
  const refresh=()=>`<button type="button" class="secondary" data-wallet-action="refresh" ${loading?'disabled':''}>${icon('refresh')}<span>Refresh wallet</span></button>`;
  function shortcut(){
    if(!getAccount()||getAccount().role==='admin')return '';
    const full=data?amount(data.available):error?'Unavailable':'Loading…';
    const compact=data?new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',notation:'compact',maximumFractionDigits:2}).format(Number(data.available)):error?'—':'…';
    const label=error&&data?'Last available':'Available';
    const description=data?full+' available virtual funds'+(error?' · Balance refresh failed; open wallet to retry':''):'Virtual wallet · '+full;
    return `<a href="#/wallet" class="header-wallet ${error?'is-stale':''}" data-wallet-shortcut aria-label="${esc(description)}" title="${esc(description)}">${icon('wallet')}<span class="header-wallet-copy"><span class="header-wallet-label">${label}</span><strong><span class="header-wallet-full">${esc(full)}</span><span class="header-wallet-compact" aria-hidden="true">${esc(compact)}</span></strong></span></a>`;
  }
  function summary(compact=false){
    if(!getAccount()||getAccount().role==='admin')return '';
    if(!data)return `<section class="panel wallet-loading" ${error?'role="alert"':'role="status"'}>${error?`${esc(error)} ${refresh()}`:'Loading your virtual wallet…'}</section>`;
    return `<section class="panel wallet-summary ${compact?'wallet-compact':''}" aria-label="Virtual wallet"><header><div><span class="eyebrow">YOUR VIRTUAL WALLET</span><h2>${compact?'Available to compete':'One wallet. Every new contest.'}</h2></div>${current()==='wallet'?'<span class="pill neutral">Virtual INR</span>':link('View wallet '+icon('arrow'),'wallet','ghost')}</header>${error?`<p class="wallet-notice" role="alert">${esc(error)} Showing the last loaded balance.</p>`:''}<div class="wallet-balance-grid"><div class="wallet-total"><span>Total wallet value</span><strong>${amount(data.total_value)}</strong><small class="${tone(data.pnl)}">${signed(data.pnl)} · ${Number(data.return_pct).toFixed(2)}% since starting</small></div><div><span>Available to enter contests</span><strong>${amount(data.available)}</strong><small>Spendable virtual funds</small></div><div><span>Value in active contests</span><strong>${amount(data.invested_value)}</strong><small>${data.positions.length} active ${data.positions.length===1?'entry':'entries'} · updates after daily valuation</small></div></div><p class="wallet-caption">Joining reserves the contest’s capital. Final portfolio value returns to your available balance when results are finalized.${data.legacy_contest_count?` ${data.legacy_contest_count} pre-wallet ${data.legacy_contest_count===1?'contest is':'contests are'} tracked separately and excluded here.`:''}</p></section>`;
  }
  function page(){
    if(!getAccount())return shell('wallet',`${pagehead('Virtual capital','Your wallet','Sign in to manage your virtual funds.')}${link('Sign in','login')}`);
    const labels={opening:'Starting capital',reservation:'Contest capital reserved',settlement:'Final portfolio returned',cancellation:'Cancelled contest refund',no_submission:'Unsubmitted entry refunded'};
    return shell('wallet',`${pagehead('Virtual capital','Your wallet','Track your available funds, active investments, and realized contest results.',refresh())}${summary()}${data?`<div class="wallet-details-grid"><section class="panel"><h2>Funds in contests</h2><p class="small">Reserved starting capital: ${amount(data.reserved_capital)}. Gains and losses here become spendable after final results.</p><div class="wallet-positions">${data.positions.map(p=>`<a href="#/performance/${esc(p.contest_id)}" class="wallet-position"><div><strong>${esc(p.name)}</strong><span>${p.session_date?'Valued '+esc(p.session_date):'Reserved · awaiting first valuation'}</span></div><div><strong>${amount(p.current_value)}</strong><span class="${tone(p.pnl)}">${signed(p.pnl)}</span></div>${icon('arrow')}</a>`).join('')||'<div class="wallet-empty">No funds are reserved. Explore contests to put your virtual capital to work.</div>'}</div>${link('Explore contests','contests','secondary')}</section><section class="panel"><h2>How your wallet works</h2><ol class="wallet-explanation"><li>Start with ₹10,00,000 in virtual funds.</li><li>Reserve a contest’s full capital when you join. The same funds cannot enter two contests.</li><li>Published daily valuations change the value invested, while your available balance stays separate.</li><li>Final results release the portfolio’s value. Cancelled contests and entries without a confirmed portfolio return the reserved capital.</li></ol>${data.legacy_contest_count?`<p class="wallet-notice">${data.legacy_contest_count} ${data.legacy_contest_count===1?'contest was':'contests were'} joined before wallets launched. Those results stay visible but do not change this wallet.</p>`:''}<p class="small">Simulation only · no deposits, withdrawals, top-ups, or real money.</p></section></div><section class="panel wallet-history"><h2>Recent transactions</h2><p class="small">Latest 30 changes to your available balance. Market movements are reflected in your active contest values.</p><div class="wallet-transactions">${data.recent_entries.map(e=>`<article class="wallet-transaction"><span class="wallet-transaction-icon">${icon(e.kind==='reservation'?'trophy':'wallet')}</span><div><strong>${labels[e.kind]||esc(e.kind)}</strong><span>${e.contest_name?esc(e.contest_name)+' · ':''}${esc(new Date(e.created_at).toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'}))}</span></div><div><strong class="${tone(e.amount)}">${signed(e.amount)}</strong><span>Available ${amount(e.available_after)}</span></div></article>`).join('')}</div></section>`:''}`);
  }
  document.addEventListener('click',e=>{if(e.target.closest('[data-wallet-action="refresh"]'))load();});
  document.addEventListener('investiq:wallet-changed',()=>{reset();if(active())load();});
  return {ensure,reset,page,summary,shortcut};
}
