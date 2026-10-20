import { contestTimeline } from './results-info.js';
import { portfolioApi, contestApi } from '../api/services.js';
import { marketApi } from '../api/market.js';

export function createPortfolioController({ shell, pagehead, esc, link, render, current, getAccount }) {
  let generation = 0, key = '', loading = false, loaded = false, error = '', operationError = '', busy = false;
  let data = null, positions = new Map(), mode = 'weight', dirty = false, reviewed = null, submitKey = '';
  let query = '', sector = '', cap = '', notice = '', operation = 0, view = '';
  const stamp = value => new Date(value).toLocaleString('en-IN',{ timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short' }) + ' IST';
  // Formatting only: server decimal strings remain the only monetary source.
  const amount = value => '₹' + String(value);
  const routeKey = () => JSON.stringify([current(),getAccount()?.id]);
  function invalidate() { generation++; key = ''; loading = false; loaded = false; data = null; reviewed = null; error = ''; }
  function reset() { operation++; invalidate(); positions = new Map(); busy = false; dirty = false; operationError = ''; notice = ''; submitKey = ''; }
  const activeId = () => /^(portfolio|build)\/([0-9a-f-]{36})$/i.exec(current())?.[2];
  function button(action,label,attributes = '',disabled = false) { return `<button type="button" class="secondary" data-portfolio-action="${action}" ${attributes} ${busy || disabled ? 'disabled' : ''}>${label}</button>`; }
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
      if(id) { mode = data.draft.mode; positions = new Map(data.draft.positions.map(p=>[p.instrument_id,mode === 'quantity' ? String(p.quantity) : String(p.weight_pct)])); dirty = false; reviewed = null; }
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
    return shell('portfolio',`${pagehead('Portfolio builder','Choose a contest','Each membership has its own saved draft and immutable submissions.')}${wait || `<div class="contest-grid">${data.items.map(c=>`<article class="panel"><h2>${esc(c.name)}</h2><p>${esc(c.status)} · ${amount(esc(c.rules.capital))} virtual capital</p>${link('Open portfolio','portfolio/'+c.id)}</article>`).join('') || '<section class="panel">Join a contest to build a portfolio.</section>'}</div>${data.next_cursor ? button('more','Load more memberships',`data-cursor="${esc(data.next_cursor)}"`) : ''}`}${link('Browse contests','contests','ghost')}`);
  }
  function holdingsTable(snapshot) {
    return `<div class="tablewrap"><table><thead><tr><th>Holding</th><th>Shares</th><th>Sampled price</th><th>Notional</th></tr></thead><tbody>${snapshot.holdings.map(h=>`<tr><td>${esc(h.symbol)}</td><td>${h.quantity}</td><td>${amount(esc(h.price))}</td><td>${amount(esc(h.notional))}</td></tr>`).join('')}</tbody></table></div><p>Holdings ${amount(esc(snapshot.notional))} · Simulated fee ${amount(esc(snapshot.fee))} · Residual cash ${amount(esc(snapshot.cash))}</p><p class="small">Common EOD session ${esc(snapshot.price_session_date)} · pricing evaluated ${esc(stamp(snapshot.pricing_as_of))}. Benchmark ${esc(snapshot.benchmark.symbol)} at ${esc(snapshot.benchmark.price)} points.</p><details><summary>Price evidence</summary>${snapshot.holdings.concat(snapshot.benchmark).map(h=>`<p class="small">${esc(h.symbol)} · ${esc(h.source)} / ${esc(h.dataset_version)}<br>Observed ${esc(stamp(h.observed_at))}, published ${esc(stamp(h.source_published_at))}, ingested ${esc(stamp(h.ingested_at))}<br>Snapshot ${esc(h.price_snapshot_id)}</p>`).join('')}</details>`;
  }
  function workspace() {
    const wait = pending();
    if(wait) return shell('portfolio',wait);
    const {contest:c,draft,items,quotes,quoteMeta,quoteError,history} = data, r = c.rules;
    const editable = draft.editable && c.status === 'open';
    const matched = items.filter(i=>(!query || (i.name+' '+i.symbol).toLowerCase().includes(query.toLowerCase())) && (!sector || i.sector?.id === sector) && (!cap || i.market_cap === cap));
    const sectors = new Map(items.filter(i=>i.sector).map(i=>[i.sector.id,i.sector.name]));
    return shell('portfolio',`${pagehead('Contest portfolio',esc(c.name),`Rule version ${c.rule_version} · ${amount(esc(r.capital))} virtual capital · ${r.min_holdings}–${r.max_holdings} holdings.`,link('Switch contest','portfolio','ghost'))}${contestTimeline(c,{esc,stamp})}<div class="callout"><strong>Synthetic EOD simulation</strong><p>${quoteMeta ? 'Expected session '+esc(quoteMeta.expected_session_date) : 'Quote information unavailable.'} · Max position ${r.max_position_bps/100}% of starting capital; simulated cost ${r.simulated_cost_bps/100}%.</p><p>Weights allocate a fee-reserved budget, round down to whole shares, and leave residual cash. Prices freeze when submitted; a new version can replace it before entry closes.</p><p>Entry closes ${esc(stamp(c.entry_closes_at))} · ${esc(c.status)}. ${editable ? 'Save changes before switching contests.' : 'Entry is closed. Saved drafts and submissions are read-only.'}</p>${quoteError ? `<p role="alert">${esc(quoteError)}. Draft/history remain available; server review requires complete current prices.</p>` : ''}</div>${notice ? `<p role="status">${esc(notice)}</p>` : ''}${operationError ? `<p class="callout" role="alert">${esc(operationError)}</p>` : ''}<div class="builder"><section class="panel"><div class="grid2"><label class="field">Search eligible stocks<input id="portfolio-search" value="${esc(query)}"></label><label class="field">Sector<select id="portfolio-sector"><option value="">All sectors</option>${[...sectors].map(([id,name])=>`<option value="${esc(id)}" ${sector===id?'selected':''}>${esc(name)}</option>`).join('')}</select></label><label class="field">Market cap<select id="portfolio-cap"><option value="">All market caps</option>${['large','mid','small'].map(x=>`<option ${cap===x?'selected':''}>${x}</option>`).join('')}</select></label></div><div id="server-stockrows">${matched.map(i=>{const q=quotes.get(i.id);return `<div class="stockrow"><div><strong>${esc(i.name)}</strong><p class="small">${esc(i.symbol)} · ${esc(i.sector?.name || '')}</p><p class="small">${esc(q?.freshness || 'missing')} · ${esc(q?.session_date || 'No common price')}</p></div><div>${q?.close ? amount(esc(q.close)) : 'Unavailable'}${button('add',positions.has(i.id)?'Added':'Add',`data-id="${i.id}"`,!editable || positions.has(i.id) || !q?.eligible_for_simulation || positions.size>=r.max_holdings)}</div></div>`;}).join('') || '<p>No eligible instruments match.</p>'}</div></section><section class="portfolio-draft"><div class="row"><h2>Your contest draft</h2><span class="pill neutral">${positions.size} / ${r.max_holdings}</span></div><div class="tabs">${button('mode','Quantity','data-mode="quantity"',!editable || mode==='quantity')}${button('mode','Weight %','data-mode="weight"',!editable || mode==='weight')}</div><p class="small">Saved revision ${draft.revision} · <span id="portfolio-dirty">${dirty ? 'Unsaved changes' : 'Saved on server'}</span></p>${positions.size ? [...positions].map(([id,value])=>{const i=items.find(i=>i.id===id);return `<div class="allocation"><div class="allocname"><strong>${esc(i?.symbol || id)}</strong></div><input name="portfolio-position" aria-label="${esc(i?.symbol || id)} ${mode==='quantity'?'quantity':'weight percent'}" data-position-id="${id}" type="number" min="${mode==='quantity'?'1':'0.0001'}" max="${mode==='quantity'?'1000000000':'100'}" step="${mode==='quantity'?'1':'0.0001'}" value="${esc(value)}" ${busy || !editable ? 'disabled' : ''}><span>${mode==='quantity'?'shares':'%'}</span>${button('remove','Remove',`data-id="${id}"`,!editable)}</div>`;}).join('') : '<div class="empty">Choose eligible stocks or use starter weights.</div>'}<div class="builderfooter">${button('example','Use starter weights','',!editable)}${button('save','Save draft','',!editable)}${button('review','Review saved draft','',!editable || dirty || !draft.revision)}${button('reload','Reload portfolio')}</div><p class="small">Drafts may be incomplete. The server validates all holdings, limits, costs, eligibility and fresh prices before accepting a submission.</p></section></div>${reviewed ? `<section class="panel" id="portfolio-review"><h2>Review server calculation</h2>${holdingsTable(reviewed)}<p>This immutable snapshot will replace your previous version for this contest. Previous snapshots remain in your history.</p>${button('confirm','Confirm contest submission','',!editable || dirty)}${button('use-quantities','Use reviewed quantities','',!editable || dirty)}</section>` : ''}<section class="panel" id="portfolio-history"><h2>Submission history</h2>${history.items.length?'<p class="callout"><strong>Submission confirmed.</strong> Your portfolio is saved. Rankings and performance metrics appear after published contest closing prices are processed.</p>':'<p class="callout"><strong>A saved draft is not a submission.</strong> Review your saved draft and confirm before entry closes to enter the rankings.</p>'}${history.items.map(s=>`<details ${s.is_latest?'open':''}><summary>Version ${s.version} · ${s.is_latest?'Latest submitted version':'Earlier immutable version'} · ${esc(stamp(s.submitted_at))}</summary><p>Draft revision ${s.draft_revision} · submission ${esc(s.id)}</p>${holdingsTable(s)}</details>`).join('') || '<p>No portfolio has been submitted for this contest.</p>'}${history.next_cursor ? button('history-more','Load earlier submissions',`data-cursor="${esc(history.next_cursor)}"`) : ''}<p class="small">Published snapshots show simulated returns and rankings.</p>${link("View performance","performance/"+c.id,"ghost")}${link("Leaderboard","leaderboard/"+c.id,"ghost")}</section>`);
  }
  function page(id) {
    if(!getAccount()) return shell('portfolio',`${pagehead('Portfolio builder','Sign in to build','Contest drafts belong to your verified account.')}${link('Sign in','login')}`);
    if(!getAccount().email_verified) return shell('portfolio','<section class="panel">Verify your email before accessing contest portfolios.</section>');
    if(id && !activeId()) return shell('portfolio','<section class="panel">Choose a valid contest portfolio. '+link('Choose contest','portfolio')+'</section>');
    return id ? workspace() : selection();
  }
  function markDirty() { dirty = true; reviewed = null; submitKey = ''; operationError = ''; notice = ''; }
  function input(element) {
    if(element.dataset.positionId && !busy && data?.draft.editable) {
      positions.set(element.dataset.positionId,element.value); markDirty();
      document.getElementById('portfolio-dirty').textContent = 'Unsaved changes';
      document.querySelector('[data-portfolio-action="review"]')?.setAttribute('disabled','');
      document.getElementById('portfolio-review')?.remove();
    }
  }
  function change(element) {
    if(element.id==='portfolio-search') query=element.value;
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
    if(['mode','add','remove','example','use-quantities'].includes(action)) {
      if(!data?.draft.editable) return;
      if(action==='mode') { mode=nextMode; positions = new Map([...positions.keys()].map(id=>[id,''])); }
      else if(action==='add') positions.set(id,mode==='quantity'?'1':'');
      else if(action==='remove') positions.delete(id);
      else if(action==='use-quantities' && reviewed) { mode='quantity'; positions = new Map(reviewed.holdings.map(h=>[h.instrument_id,String(h.quantity)])); }
      else if(action==='example') {
        const n=data.contest.rules.min_holdings;
        mode='weight';
        // Integer planning basis points only; monetary allocation happens on the server.
        const bps=Math.min(data.contest.rules.max_position_bps,Math.floor(10000/n));
        positions=new Map(data.items.filter(i=>data.quotes.get(i.id)?.eligible_for_simulation).slice(0,n).map(i=>[i.id,String(bps/100)]));
      }
      markDirty(); render(); return;
    }
    if(action==='reload') {
      if(dirty && !window.confirm('Discard unsaved changes and reload the server draft?')) return;
      invalidate(); operationError=''; notice=''; render(); return;
    }
    if(action==='more') { load(cursor); return; }
    const expected=routeKey(),token=generation,contestId=activeId(),ticket=++operation;
    busy=true; operationError=''; element.disabled=true;
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
    finally { if(ticket===operation) { busy=false; if(expected===routeKey()) render(); } }
  }
  return {page,ensure,reset,click,input,change,deactivate:()=>{if(loading || busy) {operation++;busy=false;invalidate();}}};
}
