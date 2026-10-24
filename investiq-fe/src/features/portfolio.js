import { allocationChart } from './charts.js';
import { contestTimeline } from './results-info.js';
import { portfolioApi, contestApi } from '../api/services.js';
import { marketApi } from '../api/market.js';

export function createPortfolioController({ shell, pagehead, esc, link, render, current, getAccount, icon }) {
  let generation = 0, key = '', loading = false, loaded = false, error = '', operationError = '', busy = false;
  let data = null, positions = new Map(), mode = 'weight', dirty = false, reviewed = null, submitKey = '';
  let query = '', sector = '', cap = '', notice = '', operation = 0, view = '', mobilePanel = 'stocks';
  const stamp = value => new Date(value).toLocaleString('en-IN',{ timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short' }) + ' IST';
  // Formatting only: server decimal strings remain the only monetary source.
  const amount = value => { const [whole,decimals] = String(value).split('.'); const fraction=decimals?.replace(/0+$/,''); const prefix=whole.slice(0,-3); return '₹' + (prefix?prefix.replace(/\B(?=(\d{2})+(?!\d))/g,',')+',':'') + whole.slice(-3) + (fraction ? '.'+fraction : ''); };
  const routeKey = () => JSON.stringify([current(),getAccount()?.id]);
  function invalidate() { generation++; key = ''; loading = false; loaded = false; data = null; reviewed = null; error = ''; }
  function reset() { operation++; invalidate(); positions = new Map(); busy = false; dirty = false; operationError = ''; notice = ''; submitKey = ''; }
  const activeId = () => /^(portfolio|build)\/([0-9a-f-]{36})$/i.exec(current())?.[2];
  function button(action,label,attributes = '',disabled = false) {
    const icons={add:'plus',remove:'close',save:'wallet',review:'arrow',confirm:'check',reload:'refresh',example:'spark',equal:'dashboard','use-quantities':'refresh','clear-filters':'close'};
    const primary=action==='confirm'||(action==='save'&&dirty)||(action==='review'&&!dirty);
    return `<button type="button" class="${primary?'primary':'secondary'} portfolio-action" data-portfolio-action="${action}" ${attributes} ${busy || disabled ? 'disabled' : ''}>${icons[action]?icon(icons[action]):''}<span>${label}</span></button>`;
  }
  async function catalogue() {
    const items = []; let cursor;
    do {
      const page = await marketApi.instruments({limit:100,eligible_only:false,...(cursor ? {cursor} : {})});
      items.push(...page.items); cursor = page.next_cursor;
    } while(cursor);
    return items;
  }
  async function load(cursor = '') {
    const expected = routeKey(), token = ++generation, id = activeId();
    if(view !== expected) {view=expected;operationError='';notice='';query='';sector='';cap='';}
    if(key !== expected && busy) { busy=false; operation++; }
    key = expected; loading = true; error = '';
    try {
      let result;
      if (!getAccount()) { result = {}; }
      else if (!id) {
        const page = await contestApi.mine({limit:20,...(cursor ? {cursor} : {})});
        result = {...page,items:cursor ? [...(data?.items || []),...page.items] : page.items};
      } else {
        const [contest,draft,history,items] = await Promise.all([contestApi.get(id),portfolioApi.getDraft(id),portfolioApi.history(id),catalogue()]);
        const eligible = new Set(contest.rules.eligible_instrument_ids);
        result = {contest,draft,history,items:items.filter(i=>eligible.has(i.id)),quotes:new Map(),quoteError:'',quoteMeta:null};
        try {
          const ids = result.items.map(i=>i.id);
          for(let i=0;i<ids.length;i+=100) {
            const batch = await marketApi.quotes(ids.slice(i,i+100),result.quoteMeta?.as_of);
            result.quoteMeta ||= batch;
            for(const quote of batch.items) result.quotes.set(quote.instrument_id,quote);
          }
        } catch(e) { result.quoteError = e.message; }
      }
      if(token !== generation || expected !== routeKey()) return;
      data = result; loaded = true;
      if(id) { mode = data.draft.mode; positions = new Map(data.draft.positions.map(p=>[p.instrument_id,mode === 'quantity' ? String(p.quantity) : String(p.weight_pct)])); dirty = false; reviewed = null; mobilePanel=positions.size?'draft':'stocks'; }
    } catch(e) { if(token === generation && expected === routeKey()) { error = e.message; loaded = true; } }
    finally { if(token === generation && expected === routeKey()) { loading = false; render(); } }
  }
  function ensure() { if(key !== routeKey()) load(); }
  function pending() {
    if(key !== routeKey() || !loaded) return '<section class="panel empty" role="status">Loading your portfolio…</section>';
    if(error) return `<section class="panel" role="alert"><p>${esc(error)}</p>${button('reload','Reload portfolio')}${link('My Contests','my-contests','ghost')}</section>`;
    return '';
  }
  function selection() {
    const wait = pending();
    return shell('portfolio',`${pagehead('Portfolio builder','Choose a contest','Build a separate strategy for each contest. Revisit drafts, manage submissions and track results.')}${wait || `<div class="contest-grid portfolio-memberships">${data.items.map(c=>`<article class="panel"><span class="pill neutral">${esc(c.status)}</span><h2>${esc(c.name)}</h2><div class="portfolio-card-meta"><span class="small">Virtual capital<strong>${amount(esc(c.rules.capital))}</strong></span><span class="small">Holdings<strong>${c.rules.min_holdings}–${c.rules.max_holdings}</strong></span></div><p class="small">${c.status==='open'?'Build and confirm your portfolio before entry closes.':'Review your portfolio and any confirmed submissions.'}</p>${link(icon('wallet')+' Open portfolio','portfolio/'+c.id,'secondary')}</article>`).join('') || '<section class="panel">Join a contest to build a portfolio.</section>'}</div>${data.next_cursor ? button('more','Load more memberships',`data-cursor="${esc(data.next_cursor)}"`) : ''}`}${link('Browse contests','contests','ghost')}`);
  }
  function holdingsTable(snapshot) {
    return `<div class="tablewrap"><table><thead><tr><th>Holding</th><th>Shares</th><th>Sampled price</th><th>Notional</th></tr></thead><tbody>${snapshot.holdings.map(h=>`<tr><td>${esc(h.symbol)}</td><td>${h.quantity}</td><td>${amount(esc(h.price))}</td><td>${amount(esc(h.notional))}</td></tr>`).join('')}</tbody></table></div><p>Holdings ${amount(esc(snapshot.notional))} · Simulated fee ${amount(esc(snapshot.fee))} · Residual cash ${amount(esc(snapshot.cash))}</p><p class="small">Common EOD session ${esc(snapshot.price_session_date)} · pricing evaluated ${esc(stamp(snapshot.pricing_as_of))}. Benchmark ${esc(snapshot.benchmark.symbol)} at ${esc(snapshot.benchmark.price)} points.</p><details><summary>Price evidence</summary>${snapshot.holdings.concat(snapshot.benchmark).map(h=>`<p class="small">${esc(h.symbol)} · ${esc(h.source)} / ${esc(h.dataset_version)}<br>Observed ${esc(stamp(h.observed_at))}, published ${esc(stamp(h.source_published_at))}, ingested ${esc(stamp(h.ingested_at))}<br>Snapshot ${esc(h.price_snapshot_id)}</p>`).join('')}</details>`;
  }
  function steps() {
    const stage=reviewed?2:positions.size?1:0;
    return `<ol class="portfolio-steps" aria-label="Portfolio submission steps">${[['Choose holdings','Explore eligible stocks'],['Save allocations','Set weights or shares'],['Review & confirm','Check the final calculation']].map(([title,description],i)=>`<li ${i===stage?'aria-current="step"':''} class="${i===stage?'is-current':i<stage?'is-complete':''}"><span class="portfolio-step-number">${i<stage?icon('check'):i+1}</span><div><strong>${title}</strong><span>${description}</span></div></li>`).join('')}</ol>`;
  }
  function allocationSummary() {
    const r=data.contest.rules, values=[...positions.values()];
    const total=values.reduce((n,v)=>n+(Number.isFinite(Number(v))?Math.round(Number(v)*10000):0),0)/10000;
    const filled=values.every(v=>v.trim()&&Number.isFinite(Number(v))&&Number(v)>0&&(mode!=='quantity'||Number.isInteger(Number(v))));
    const sectors=new Set([...positions.keys()].map(id=>data.items.find(i=>i.id===id)?.sector?.id).filter(Boolean));
    const countOK=positions.size>=r.min_holdings&&positions.size<=r.max_holdings;
    const fmt=n=>n.toLocaleString('en-IN',{maximumFractionDigits:4});
    const issues=[];
    if(!countOK)issues.push(positions.size<r.min_holdings?`Add ${r.min_holdings-positions.size} more holding${r.min_holdings-positions.size===1?'':'s'} to meet the contest minimum.`:`Keep at most ${r.max_holdings} holdings.`);
    if(!filled)issues.push(mode==='weight'?'Enter a positive weight for every holding.':'Enter positive whole shares for every holding.');
    if(mode==='weight'&&total>100)issues.push(`Reduce total weights by ${fmt(total-100)} percentage points.`);
    return `<div class="portfolio-allocation-head"><div><span class="small">${mode==='weight'?'Target allocation':'Planned shares'}</span><strong>${fmt(total)}${mode==='weight'?'%':''}</strong></div><span class="pill neutral">${sectors.size} sector${sectors.size===1?'':'s'}</span></div>${mode==='weight'?`<div class="portfolio-weight-track" role="img" aria-label="${fmt(total)} percent target allocation"><span class="${total>100?'over-limit':''}" style="width:${Math.max(0,Math.min(100,total))}%"></span></div><p class="small">${total<=100?fmt(100-total)+'% unallocated target · whole-share rounding may leave additional cash.':'Total target weights exceed 100%.'}</p>`:'<p class="small">Exact invested value, fees and remaining cash appear in the server review.</p>'}<ul class="portfolio-checks">${issues.map(message=>`<li>${icon('clock')}${esc(message)}</li>`).join('')||`<li>${icon('check')}Basic allocation checks look good. Save and review to validate prices, costs and position limits.</li>`}</ul>`;
  }
  function stockRows() {
    const {items,quotes,contest:c,draft}=data,r=c.rules;
    const editable=draft.editable&&c.status==='open';
    const matched=items.filter(i=>(!query||(i.name+' '+i.symbol).toLowerCase().includes(query.trim().toLowerCase()))&&(!sector||i.sector?.id===sector)&&(!cap||i.market_cap===cap));
    return `<p class="small portfolio-search-count" role="status">${matched.length} of ${items.length} eligible stocks</p>${matched.length?matched.map(i=>{
      const q=quotes.get(i.id),selected=positions.has(i.id),unavailable=!q?.eligible_for_simulation;
      const reason=selected?'In your draft':!editable?'Entry closed':unavailable?'Current price unavailable':positions.size>=r.max_holdings?'Holding limit reached':q?.session_date?'Close · '+q.session_date:'No common price';
      return `<article class="portfolio-stock ${selected?'is-selected':''}"><span class="stockbadge" aria-hidden="true">${esc(i.symbol.slice(0,2))}</span><div class="portfolio-stock-name"><strong>${esc(i.symbol)}</strong><span>${esc(i.name)}</span><small>${esc(i.sector?.name||'Unclassified')} · ${esc(i.market_cap)} cap</small></div><div class="portfolio-stock-price"><strong>${q?.close?amount(esc(q.close)):'Unavailable'}</strong><small>${esc(reason)}</small></div>${button('add',selected?'Added':'Add',`data-id="${i.id}" aria-label="${selected?'Added':'Add'} ${esc(i.symbol)}"`,!editable||selected||unavailable||positions.size>=r.max_holdings)}</article>`;
    }).join(''):`<div class="empty">${icon('search')}<h3>No matching stocks</h3><p>Try another name, symbol or filter.</p>${button('clear-filters','Clear filters')}</div>`}`;
  }
  function workspace() {
    const wait=pending();if(wait)return shell('portfolio',wait);
    const {contest:c,draft,items,quoteMeta,quoteError,history}=data,r=c.rules;
    const editable=draft.editable&&c.status==='open';
    const sectors=new Map(items.filter(i=>i.sector).map(i=>[i.sector.id,i.sector.name]));
    return shell('portfolio',`<div class="portfolio-workspace">${pagehead('Build your strategy',esc(c.name),'Choose your holdings, shape your allocation, and submit when you’re ready.',link(icon('arrow')+' Switch contest','portfolio','secondary'))}
      <div class="portfolio-overview"><div>${icon('wallet')}<span>Virtual capital<strong>${amount(esc(r.capital))}</strong></span></div><div>${icon('bag')}<span>Holdings allowed<strong>${r.min_holdings}–${r.max_holdings} stocks</strong></span></div><div>${icon('chart')}<span>Position limit<strong>${r.max_position_bps/100}% of capital</strong></span></div><div>${icon('clock')}<span>Entry closes<strong>${esc(stamp(c.entry_closes_at))}</strong></span></div></div>
      <div id="portfolio-step-status">${steps()}</div>
      ${!editable?'<div class="callout"><strong>Portfolio is read-only</strong><p>Entry is closed. You can review your saved draft, submissions and results below.</p></div>':''}
      <details class="page-details portfolio-rules"><summary>Contest rules, schedule &amp; pricing</summary>${contestTimeline(c,{esc,stamp})}<p>Synthetic EOD simulation · ${quoteMeta?'Expected session '+esc(quoteMeta.expected_session_date):'Quote information unavailable.'} · Simulated cost ${r.simulated_cost_bps/100}% · Rule version ${c.rule_version}.</p><p>Weights allocate a fee-reserved budget and round down to whole shares. Unused funds remain as cash. A new confirmed version can replace your submission before entry closes.</p></details>
      ${quoteError?`<p class="callout" role="alert">${esc(quoteError)}. Your draft and history remain available; review needs complete current prices.</p>`:''}
      ${notice?`<p class="portfolio-notice" role="status">${icon('check')}${esc(notice)}</p>`:''}${operationError?`<p class="callout" id="portfolio-operation-error" role="alert" tabindex="-1">${esc(operationError)}</p>`:''}
      <div class="portfolio-builder" data-mobile-view="${mobilePanel}"><div class="portfolio-mobile-tabs" role="group" aria-label="Portfolio workspace"><button type="button" data-portfolio-action="mobile-stocks" aria-pressed="${mobilePanel==='stocks'}">${icon('search')} Explore stocks</button><button type="button" data-portfolio-action="mobile-draft" aria-pressed="${mobilePanel==='draft'}">${icon('wallet')} Your draft <span class="pill neutral">${positions.size}</span></button></div><section class="panel portfolio-catalogue" aria-label="Stock discovery"><div class="row"><div><span class="eyebrow">01 · Discover</span><h2>Choose your stocks</h2></div><span class="pill neutral">${items.length} available</span></div><p class="small">Explore the contest’s eligible stocks and add them to your draft.</p><label class="field portfolio-search">Search eligible stocks<input type="search" id="portfolio-search" placeholder="Search by company or symbol" value="${esc(query)}"></label><div class="portfolio-filters"><label class="field">Sector<select id="portfolio-sector"><option value="">All sectors</option>${[...sectors].map(([id,name])=>`<option value="${esc(id)}" ${sector===id?'selected':''}>${esc(name)}</option>`).join('')}</select></label><label class="field">Market cap<select id="portfolio-cap"><option value="">All market caps</option>${['large','mid','small'].map(x=>`<option value="${x}" ${cap===x?'selected':''}>${x[0].toUpperCase()+x.slice(1)} cap</option>`).join('')}</select></label></div><div id="server-stockrows">${stockRows()}</div></section>
      <section class="panel portfolio-editor" aria-label="Portfolio draft"><div class="row"><div><span class="eyebrow">02 · Allocate</span><h2>Your contest draft</h2></div><span class="pill neutral">${positions.size} / ${r.max_holdings}</span></div><p class="small">Revision ${draft.revision} · <span id="portfolio-dirty">${dirty?'Unsaved changes':'Saved on server'}</span></p><div class="portfolio-modes" role="group" aria-label="Allocation method">${button('mode','Weight %',`data-mode="weight" aria-pressed="${mode==='weight'}"`,!editable||mode==='weight')}${button('mode','Quantity',`data-mode="quantity" aria-pressed="${mode==='quantity'}"`,!editable||mode==='quantity')}</div><div id="portfolio-allocation-summary" aria-live="polite">${allocationSummary()}</div>
      <div class="portfolio-holdings">${positions.size?[...positions].map(([id,value])=>{const i=items.find(i=>i.id===id);return `<div class="portfolio-holding"><div><strong>${esc(i?.symbol||id)}</strong><span class="small">${esc(i?.sector?.name||'Unclassified')}</span></div><div class="portfolio-holding-input"><input name="portfolio-position" aria-label="${esc(i?.symbol||id)} ${mode==='quantity'?'quantity':'weight percent'}" data-position-id="${id}" type="number" min="${mode==='quantity'?'1':'0.0001'}" max="${mode==='quantity'?'1000000000':'100'}" step="${mode==='quantity'?'1':'0.0001'}" placeholder="0" value="${esc(value)}" ${busy||!editable?'disabled':''}><span>${mode==='quantity'?'shares':'%'}</span></div>${button('remove','Remove',`data-id="${id}" aria-label="Remove ${esc(i?.symbol||id)}"`,!editable)}</div>`;}).join(''):`<div class="empty portfolio-empty">${icon('wallet')}<h3>Your strategy starts here</h3><p>Add ${r.min_holdings}–${r.max_holdings} stocks, or use starter weights to explore the builder.</p></div>`}</div>
      <div class="portfolio-tools">${button('example','Use starter weights','',!editable)}${button('equal','Equalize weights','',!editable||mode!=='weight'||!positions.size)}</div><p class="small">Starter weights use the first available stocks; they are a learning shortcut, not a recommendation.</p>
      <div class="portfolio-savebar">${button('save','Save draft','',!editable)}${button('review','Review saved draft','',!editable||dirty||!draft.revision)}<p id="portfolio-next-step" class="small">${dirty?'Save your changes to unlock review.':'A saved draft is not an entry. Review and confirm to participate.'}</p></div><div class="portfolio-reload">${button('reload','Reload portfolio')}<span class="small">Restore the latest saved draft</span></div></section></div>
      ${reviewed?`<section class="panel portfolio-review" id="portfolio-review" tabindex="-1"><span class="eyebrow">03 · Confirm</span><h2>Review server calculation</h2><p>Check your whole shares, simulated fee and remaining cash before submitting.</p>${allocationChart(reviewed.holdings.map(h=>({symbol:h.symbol,value:h.notional})),reviewed.cash,Number(reviewed.notional)+Number(reviewed.cash))}${holdingsTable(reviewed)}<p>${history.items.length?'Confirming replaces your active submission. Earlier versions remain in your history.':'Confirm this portfolio to enter the contest standings after valuation.'}</p><div class="portfolio-review-actions">${button('confirm','Confirm contest submission','',!editable||dirty)}${button('use-quantities','Use reviewed quantities','',!editable||dirty)}</div></section>`:''}
      <section class="panel portfolio-history" id="portfolio-history"><div class="row"><div><span class="eyebrow">Your entries</span><h2>Submission history</h2></div><span class="pill neutral">${history.items.length?'Submitted':'Not submitted'}</span></div>${history.items.length?'<p class="callout"><strong>Submission confirmed.</strong> Your latest confirmed version is the contest entry. Draft edits only become an entry after you confirm again. Rankings appear after published closing prices are processed.</p>':'<p class="callout"><strong>A saved draft is not a submission.</strong> Review your saved draft and confirm before entry closes to enter the rankings.</p>'}${history.items.map(s=>`<details class="page-details"><summary>Version ${s.version} · ${s.is_latest?'Latest submitted version':'Earlier immutable version'} · ${esc(stamp(s.submitted_at))}</summary><p>Draft revision ${s.draft_revision} · submission ${esc(s.id)}</p>${holdingsTable(s)}</details>`).join('')||'<p>No portfolio has been submitted for this contest.</p>'}${history.next_cursor?button('history-more','Load earlier submissions',`data-cursor="${esc(history.next_cursor)}"`):''}<div class="portfolio-review-actions">${link(icon('chart')+' View performance','performance/'+c.id,'secondary')}${link(icon('trophy')+' Leaderboard','leaderboard/'+c.id,'secondary')}</div></section></div>`);
  }
  function page(id) {
    if(!getAccount()) return shell('portfolio',`${pagehead('Portfolio builder','Sign in to build','Contest drafts belong to your verified account.')}${link('Sign in','login')}`);
    if(!getAccount().email_verified) return shell('portfolio','<section class="panel">Verify your email before accessing contest portfolios.</section>');
    if(id && !activeId()) return shell('portfolio','<section class="panel">Choose a valid contest portfolio. '+link('Choose contest','portfolio')+'</section>');
    return id ? workspace() : selection();
  }
  function markDirty() { dirty = true; reviewed = null; submitKey = ''; operationError = ''; notice = ''; }
  function input(element) {
    if(element.id==='portfolio-search'){query=element.value;document.getElementById('server-stockrows').innerHTML=stockRows();return;}
    if(element.dataset.positionId && !busy && data?.draft.editable) {
      positions.set(element.dataset.positionId,element.value); markDirty();
      document.getElementById('portfolio-dirty').textContent = 'Unsaved changes';
      document.querySelector('[data-portfolio-action="review"]')?.setAttribute('disabled','');
      document.getElementById('portfolio-review')?.remove();
      document.querySelector('.portfolio-notice')?.remove();
      document.getElementById('portfolio-operation-error')?.remove();
      document.getElementById('portfolio-allocation-summary').innerHTML=allocationSummary();
      document.getElementById('portfolio-step-status').innerHTML=steps();
      document.getElementById('portfolio-next-step').textContent='Save your changes to unlock review.';
      const save=document.querySelector('[data-portfolio-action="save"]');save?.classList.replace('secondary','primary');
      document.querySelector('[data-portfolio-action="review"]')?.classList.replace('primary','secondary');
    }
  }
  function change(element) {
    if(element.id==='portfolio-search') return;
    else if(element.id==='portfolio-sector') sector=element.value;
    else if(element.id==='portfolio-cap') cap=element.value;
    else return;
    render();
  }
  function body() {
    return {expected_revision:data.draft.revision,mode,positions:[...positions].map(([id,value])=>{
      if(!value.trim()) throw new Error('Enter an allocation for every holding.');
      if(mode==='quantity' && !/^[1-9][0-9]*$/.test(value)) throw new Error('Quantities must be positive whole shares.');
      return {instrument_id:id,...(mode==='quantity'?{quantity:Number(value)}:{weight_pct:value})};
    })};
  }
  async function click(element) {
    if(element.disabled || busy) return;
    const {portfolioAction:action,id,cursor,mode:nextMode} = element.dataset;
    if(action==='mobile-stocks'||action==='mobile-draft'){mobilePanel=action==='mobile-draft'?'draft':'stocks';render();document.querySelector('.portfolio-builder')?.scrollIntoView({block:'start'});return;}
    if(action==='clear-filters'){query='';sector='';cap='';render();document.getElementById('portfolio-search')?.focus();return;}
    if(['mode','add','remove','example','equal','use-quantities'].includes(action)) {
      if(!data?.draft.editable) return;
      if(action==='mode') { if(positions.size&&!window.confirm('Switch allocation method? Your selected stocks will stay, but their allocation values will be cleared.'))return; mode=nextMode; positions = new Map([...positions.keys()].map(id=>[id,''])); }
      else if(action==='add') positions.set(id,mode==='quantity'?'1':'');
      else if(action==='remove') positions.delete(id);
      else if(action==='use-quantities' && reviewed) { mode='quantity'; positions = new Map(reviewed.holdings.map(h=>[h.instrument_id,String(h.quantity)])); }
      else if(action==='equal') {
        const weight=Math.min(data.contest.rules.max_position_bps,Math.floor(10000/positions.size))/100;
        positions=new Map([...positions.keys()].map(id=>[id,String(weight)]));
      }
      else if(action==='example') {
        if(positions.size&&!window.confirm('Replace the current draft holdings with starter weights? Your saved draft stays unchanged until you save.'))return;
        const n=data.contest.rules.min_holdings;
        mode='weight';
        // Integer planning basis points only; monetary allocation happens on the server.
        const bps=Math.min(data.contest.rules.max_position_bps,Math.floor(10000/n));
        positions=new Map(data.items.filter(i=>data.quotes.get(i.id)?.eligible_for_simulation).slice(0,n).map(i=>[i.id,String(bps/100)]));
      }
      if(['add','example','use-quantities'].includes(action))mobilePanel='draft';
      markDirty(); render();
      if(action==='add')document.querySelector(`[data-position-id="${id}"]`)?.focus();
      return;
    }
    if(action==='reload') {
      if(dirty && !window.confirm('Discard unsaved changes and reload the server draft?')) return;
      invalidate(); operationError=''; notice=''; render(); return;
    }
    if(action==='more') { load(cursor); return; }
    const expected=routeKey(),token=generation,contestId=activeId(),ticket=++operation;
    busy=true; operationError=''; element.disabled=true;
    const pendingLabel={save:'Saving draft…',review:'Calculating portfolio…',confirm:'Submitting portfolio…','history-more':'Loading submissions…'}[action];
    if(pendingLabel)element.querySelector('span:last-child').textContent=pendingLabel;
    document.querySelectorAll('[data-portfolio-action]').forEach(x=>x.disabled=true);
    document.querySelectorAll('[name="portfolio-position"]').forEach(x=>x.disabled=true);
    try {
      if(action==='save') {
        const draft=await portfolioApi.saveDraft(contestId,body());
        if(expected!==routeKey() || token!==generation) return;
        data.draft=draft; dirty=false; reviewed=null; notice='Draft saved on the server.';
      } else if(action==='review') {
        const result=await portfolioApi.preview(contestId,data.draft.revision);
        if(expected!==routeKey() || token!==generation) return;
        if(reviewed?.preview_hash!==result.preview_hash) submitKey=crypto.randomUUID();
        reviewed=result; notice='Review whole shares, simulated fee and residual cash before confirming.';
      } else if(action==='confirm' && reviewed && !dirty) {
        const result=await portfolioApi.submit(contestId,{draft_revision:reviewed.draft_revision,preview_hash:reviewed.preview_hash},submitKey);
        if(expected!==routeKey() || token!==generation) return;
        notice=`Submission version ${result.version} accepted. Previous snapshots remain immutable.`;
        invalidate();
      } else if(action==='history-more') {
        const history=await portfolioApi.history(contestId,{cursor});
        if(expected!==routeKey() || token!==generation) return;
        data.history={...history,items:[...data.history.items,...history.items]};
      }
    } catch(e) { if(expected===routeKey() && token===generation) { operationError=e.message; if(e.details?.error?.code==='portfolio_locked'){data.draft.editable=false;reviewed=null;} } }
    finally { if(ticket===operation) { busy=false; if(expected===routeKey()) {render();const target=operationError?document.getElementById('portfolio-operation-error'):action==='review'&&reviewed?document.getElementById('portfolio-review'):null;target?.focus({preventScroll:true});target?.scrollIntoView({block:'start'});} } }
  }
  return {page,ensure,reset,click,input,change,deactivate:()=>{if(loading || busy) {operation++;busy=false;invalidate();}}};
}
