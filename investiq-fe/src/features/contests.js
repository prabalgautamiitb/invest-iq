import { contestFormIssues, clearContestFormErrors, showContestFormErrors, contestApiIssues } from './contest-validation.js';
import { explorerCard, explorerDetail } from './contest-explorer.js';
import { contestTimeline } from './results-info.js';
import { contestApi, performanceApi } from '../api/services.js';
import { marketApi } from '../api/market.js';

// Account-scoped, memory-only data. Route/request generations discard obsolete responses.
export function createContestController({ shell, pagehead, esc, money, link, icon, toast, render, current, getAccount }) {
  let generation = 0, key = '', loading = false, loaded = false, error = '', data = null;
  let query = '', filter = 'All', status = '', sort = 'name', scope = 'joined';
  let clockTimer=null, clockBase=0;
  const clockReceived=new WeakMap();
  let actionError='', busy = false, lastPayload = '', creationKey = crypto.randomUUID();
  const stamp = value => new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) + ' IST';
  const localTime = value => {
    const d = new Date(new Date(value).getTime() + 330 * 60000);
    return d.toISOString().slice(0, 19);
  };
  const account = () => getAccount();
  const routeKey = () => JSON.stringify([current(), account()?.id, query, filter, status, sort, scope]);
  function invalidate() { stopClock();generation++; key = ''; loaded = false; loading = false; data = null; error = ''; actionError=''; }
  function reset() { invalidate(); busy = false; query = ''; filter = 'All'; status = ''; scope = 'joined'; lastPayload = ''; creationKey = crypto.randomUUID(); }
  const params = () => ({ query, sort, ...(!status?{activity:'active'}:{}), ...(filter === 'InvestIQ' ? { organizer: 'platform' } : {}), ...(filter === 'Public' ? { visibility: 'public' } : filter === 'Private' ? { visibility: 'private' } : ['Beginner', 'Advanced'].includes(filter) ? { level: filter.toLowerCase() } : {}), ...(status ? { status } : {}) });
  function stopClock(){clearInterval(clockTimer);clockTimer=null;}
  function timing(c){
    const info={scheduled:['Opens in',c.entry_opens_at],open:['Entry closes in',c.entry_closes_at],locked:['Starts in',c.starts_at],running:['Ends in',c.ends_at]}[c.status];
    if(!info)return ({draft:'Not published',settling:'Finalizing results',completed:'Completed',cancelled:'Cancelled'})[c.status]||'';
    const now=Date.parse(c.server_time),end=Date.parse(info[1]);
    if(!Number.isFinite(now)||!Number.isFinite(end))return ({scheduled:'Upcoming',open:'Entries open',locked:'Entry closed',running:'Live'})[c.status];
    const minutes=Math.ceil((end-now-Math.max(0,performance.now()-(clockReceived.get(c)??clockBase)))/60000);
    if(minutes<=0)return 'Timing changed · Refresh';
    const days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60),mins=minutes%60;
    return info[0]+' '+(days?`${days}d ${hours}h`:hours?`${hours}h ${mins}m`:`${mins}m`);
  }
  function startClock(){stopClock();if(current()!=='contests'&&!current().startsWith('contests/'))return;
    clockTimer=setInterval(()=>{document.querySelectorAll('[data-contest-clock]').forEach(el=>{
      const c=data?.contest?.id===el.dataset.contestClock?data.contest:data?.items?.find(item=>item.id===el.dataset.contestClock);if(c)el.textContent=timing(c);
    });},30000);
  }
  async function load(more = '') {
    stopClock();
    const route = current(), expected = routeKey();
    const token = ++generation;
    key = expected; loading = true; error = ''; actionError='';
    try {
      let result;
      if (['contests/create','contests/create-platform'].includes(route)) {
        const [template, instruments] = await Promise.all([contestApi.template(), marketApi.instruments({ limit: 100, eligible_only: false })]);
        if(route.endsWith('create-platform')){template.visibility='public';template.name='InvestIQ public simulation';template.capacity=10000;}
        result = { template, instruments: instruments.items };
        result.marketStatus=await marketApi.status().catch(()=>null);
        if(route.endsWith('create-platform'))result.simulationSessions=await contestApi.simulationSessions().catch(e=>{if(e.status===404)return null;throw e;});
      } else if (route === 'contests/admin') {
        result = await contestApi.list({scope:'managed',...(more?{cursor:more}:{})});
        result.marketStatus=await marketApi.status().catch(()=>null);
        result.simulationSessions=await contestApi.simulationSessions().catch(e=>{if(e.status===404)return null;throw e;});
        if(more)result.items=[...(data?.items||[]),...result.items];
      } else if (route.startsWith('contests/')) {
        const id = route.split('/')[1];
        const c = await contestApi.get(id);
        const invites = c.can_manage && c.status !== 'draft' ? await contestApi.hostedInvitations(id, more ? { cursor: more } : {}) : { items: [], next_cursor: null };
        result = { contest: c, invites: more ? { ...invites, items: [...(data?.invites.items || []), ...invites.items] } : invites };
        result.standings=null;result.standingsError='';
        if(account()?.role!=='admin'&&!['draft','cancelled'].includes(c.status)){
          try{result.standings=await performanceApi.leaderboard(id,{limit:5});}catch{result.standingsError='Standings could not be loaded.';}
        }
        if (c.status === 'draft' && c.can_manage) {
          const instruments = await marketApi.instruments({ limit: 100, eligible_only: false, data_kind:c.market_data_kind||'fixture', include_legacy:true });
          result.instruments = instruments.items;
          if(c.organizer==='platform')result.simulationSessions=await contestApi.simulationSessions().catch(e=>{if(e.status===404)return null;throw e;});
        }
      } else if (route === 'my-contests') {
        if (!account()) { result = { items: [], next_cursor: null, invites: { items: [] } }; }
        else {
          const [memberships, invitations, dashboard] = await Promise.allSettled([contestApi.mine({ scope, ...(more ? { cursor: more } : {}) }), contestApi.invitations(), performanceApi.dashboard()]);
          if(memberships.status==='rejected')throw memberships.reason;
          const page=memberships.value,items=more?[...(data?.items||[]),...page.items]:page.items;
          const summaries=new Map((more?data?.summary?.items||[]:[]).map(item=>[item.contest_id,item]));
          if(dashboard.status==='fulfilled')dashboard.value.items.forEach(item=>summaries.set(item.contest_id,item));
          // Home includes only the latest 20 memberships. Older cards need their own result.
          const missing=items.filter(c=>c.joined&&!summaries.has(c.id));
          const extra=await Promise.allSettled(missing.map(c=>performanceApi.performance(c.id)));
          extra.forEach((response,i)=>{if(response.status==='fulfilled'){
            const p=response.value;
            summaries.set(missing[i].id,{contest_id:missing[i].id,has_submission:p.has_submission,session_date:p.metrics?.session_date,is_current:p.is_current,is_final:p.is_final,rank:p.metrics?.rank,total_value:p.metrics?.total_value,pnl:p.metrics?.pnl,return_pct:p.metrics?.return_pct});
          }});
          result={...page,items,invites:invitations.status==='fulfilled'?invitations.value:{items:[]},invitationError:invitations.status==='rejected'?'Invitations could not be loaded.':'',summary:{items:[...summaries.values()]}};
        }
      } else {
        const page = await contestApi.list({ ...params(), ...(more ? { cursor: more } : {}) });
        result = { ...page, items: more ? [...(data?.items || []), ...page.items] : page.items };
      }
      if (token !== generation || expected !== routeKey()) return;
      data = result; loaded = true;clockBase=performance.now();
      for(const item of result.contest?[result.contest]:result.items||[]){if(!clockReceived.has(item))clockReceived.set(item,clockBase);}
    } catch (e) {
      if (token !== generation || expected !== routeKey()) return;
      error = e.message; loaded = true;
    } finally {
      if (token === generation && expected === routeKey()) { loading = false; render();startClock(); }
    }
  }
  function ensure() { if (key !== routeKey()) load();else if(!loading&&!clockTimer)startClock(); }
  function ready() {
    if (key !== routeKey() || (!loaded && !error)) return '<section class="panel empty" role="status">Loading contests…</section>';
    if (error) return `<section class="panel" role="alert"><p>${esc(error)}</p><button class="secondary" data-contest-action="reload">Try again</button></section>`;
    return '';
  }
  const actionLink = (text, route, symbol, primary=false) => link(icon(symbol)+`<span>${text}</span>`,route,`${primary?'primary':'secondary'} contest-action`);
  function controls() { return `<button class="secondary contest-action" data-contest-action="reload" ${loading ? 'disabled' : ''}>${icon('refresh')}<span>Refresh contests</span></button>`; }
  const button = (action, text, id = '', cls = 'primary') => `<button class="${cls} contest-action" data-contest-action="${action}" data-id="${esc(id)}" ${busy ? 'disabled' : ''}>${icon(({join:'users',publish:'check',cancel:'close',accept:'check',decline:'close',revoke:'close',more:'arrow','invite-more':'arrow'})[action]||'arrow')}<span>${text}</span></button>`;
  const statusLabel = status => ({draft:'Draft',scheduled:'Upcoming',open:'Entries open',locked:'Entries closed',running:'Live',settling:'Finalizing results',completed:'Completed',cancelled:'Cancelled'})[status]||status;
  function scheduleTime(value,compact=false) {
    if(!value||!Number.isFinite(new Date(value).getTime()))return '<span class="contest-date-unavailable">To be announced</span>';
    const date=new Date(value),day=date.toLocaleDateString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',year:'numeric'}),time=date.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'numeric',minute:'2-digit'});
    return `<time datetime="${esc(value)}" title="${esc(stamp(value))}">${compact?`${esc(day)} · ${esc(time)}`:`<strong>${esc(day)}</strong><span>${esc(time)}</span>`}</time>`;
  }
  function cardSchedule(c) {
    const cancelled=c.status==='cancelled';
    const opens=['draft','scheduled'].includes(c.status);
    const entryLabel=cancelled?'Entry cancelled':opens?'Entry opens':c.status==='open'?'Entry closes':'Entry closed';
    return `<section class="contest-card-schedule" aria-label="Contest schedule"><div class="contest-schedule-label">${icon('clock')}<span>${cancelled?'Planned schedule':'Schedule'} · IST</span></div><dl class="contest-card-dates"><div><dt>${cancelled?'Planned start':'Starts'}</dt><dd>${scheduleTime(c.starts_at)}</dd></div><div><dt>${cancelled?'Planned end':'Ends'}</dt><dd>${scheduleTime(c.ends_at)}</dd></div></dl><div class="contest-entry-deadline ${c.status==='open'?'is-open':''}"><span>${entryLabel}</span>${cancelled?'':scheduleTime(opens?c.entry_opens_at:c.entry_closes_at,true)}</div></section><details class="contest-schedule-details"><summary>Schedule details</summary><dl><div><dt>${opens?'Entry closes':'Entry opens'}</dt><dd>${scheduleTime(opens?c.entry_closes_at:c.entry_opens_at,true)}</dd></div><div><dt>${cancelled?'Planned first results after':'First results after'}</dt><dd>${scheduleTime(c.first_results_available_at,true)}</dd></div></dl><p>All times in IST. Results may be delayed until closing prices are available.</p></details>`;
  }
  function card(c) {
    if(account()?.role==='admin')return `<article class="panel"><div class="row"><span class="pill neutral">${esc(statusLabel(c.status))}</span><span class="small">${c.member_count} participants</span></div><h2>${esc(c.name)}</h2>${c.joined?`<p class="small">${c.wallet_backed?(c.status==='completed'?'Wallet funds returned':c.status==='cancelled'?'Wallet capital refunded':'Wallet-funded entry'):'Pre-wallet entry · excluded from wallet balance'}</p>`:''}<p>${esc(c.description)}</p><p class="small">${c.rules.eligible_instrument_ids.length} eligible stocks · ${c.market_data_kind==='yahoo'?'Market prices':'Synthetic prices'}</p><dl class="my-contest-dates"><div><dt>Starts · IST</dt><dd>${scheduleTime(c.starts_at,true)}</dd></div><div><dt>Ends · IST</dt><dd>${scheduleTime(c.ends_at,true)}</dd></div></dl>${actionLink('Manage contest','contests/'+c.id,'arrow',true)}</article>`;
    const performance = data?.summary?.items?.find(i=>i.contest_id===c.id);
    return `<article class="panel contestcard contest-scan-card"><header class="contest-card-heading"><span class="contest-source">${c.organizer==='platform'?'InvestIQ · ':''}${esc(c.visibility==='public'?'Public':'Private')}${c.level!=='all'?' · '+esc(c.level):''}</span><span class="contest-state contest-state-${esc(c.status)}"><i aria-hidden="true"></i>${esc(statusLabel(c.status))}</span></header><h3>${esc(c.name)}</h3><p class="contest-card-description">${esc(c.description)}</p>${cardSchedule(c)}<div class="contest-info"><div><span class="small">Virtual capital</span><strong>${money(c.rules.capital)}</strong></div><div><span class="small">Members</span><strong>${c.member_count} / ${c.capacity}</strong></div></div>${performance?.total_value ? `<div class="contest-card-result"><strong>₹${esc(performance.total_value)}</strong><span>${esc(performance.return_pct)}% return · #${performance.rank}</span><small>Snapshot ${esc(performance.session_date)} · ${performance.is_final?'Final':performance.is_current?'Current':'Earlier snapshot'}</small></div>` : ''}<footer class="contest-card-footer"><nav class="contest-actions" aria-label="Actions for ${esc(c.name)}">${actionLink('View contest','contests/'+c.id,'arrow',true)}${c.joined ? actionLink('Portfolio','portfolio/'+c.id,'wallet')+actionLink('Performance','performance/'+c.id,'chart') : ''}${actionLink('Leaderboard','leaderboard/'+c.id,'trophy')}</nav><span class="contest-membership">${icon(c.joined?'check':c.is_owner?'users':'shield')}${c.joined ? (c.wallet_backed?'Wallet funded':'Pre-wallet entry') : c.is_owner ? 'Hosting' : 'Free entry'}</span></footer></article>`;
  }
  function more() { return data?.next_cursor ? button('more', loading ? 'Loading…' : 'Load more contests', data.next_cursor, 'secondary') : ''; }
  function discovery() {
    return shell('contests',`<div class="contest-explorer-page">${pagehead('Compete','Contest explorer','Free entry, virtual capital, and a format for every learning style.',actionLink('Create contest','contests/create','plus',true)+(account()?.role==='admin'?actionLink('Manage InvestIQ contests','contests/admin','shield'):''))}<label class="explorer-search"><span class="sr-only">Search contests</span>${icon('search')}<input type="search" id="server-contest-query" maxlength="100" value="${esc(query)}" placeholder="Search contests by name or description" aria-label="Search contests"></label><div class="tabs explorer-filters" role="group" aria-label="Explore contest formats">${['All','Public','Private','InvestIQ','Beginner','Advanced'].map(x=>`<button data-contest-action="filter" data-id="${x}" aria-pressed="${filter===x}" class="${filter===x?'active':''}">${x}</button>`).join('')}</div><details class="page-details contest-explorer-filters"><summary>More filters</summary><div class="grid2"><label class="field">Contest status<select id="server-contest-status"><option value="">Upcoming &amp; live</option>${['scheduled','open','locked','running','settling','completed','cancelled'].map(x=>`<option value="${x}" ${status===x?'selected':''}>${statusLabel(x)}</option>`).join('')}</select></label><label class="field">Sort contests<select id="server-contest-sort"><option value="name">Name A–Z</option><option value="-name" ${sort==='-name'?'selected':''}>Name Z–A</option></select></label></div></details>${ready()||`<div class="explorer-contest-grid">${data.items.map(c=>explorerCard(c,{esc,money,link,icon,timing,scheduleTime})).join('')||'<section class="panel empty">No contests match. Check another filter or come back for the next public contest.</section>'}</div>${more()}`}${controls()}</div>`);
  }
  function form(template, instruments, edit = false) {
    const r = template.rules;
    const sessions=data?.simulationSessions;
    const sourceKind=template.market_data_kind||data?.marketStatus?.mode;
    const coverage=sourceKind==='yahoo'?'<p class="callout" data-market-source>Yahoo Finance market prices · virtual portfolios. Valuations update after 18:00 IST once complete daily closing prices arrive. Choose trading sessions within the reviewed 2026 calendar.</p>':sessions?.length?`<p class="callout" data-simulation-coverage>Simulation coverage in this environment: ${esc(sessions[0])} – ${esc(sessions.at(-1))}. Choose covered exchange sessions. Coverage follows the active simulation environment.</p>`:'';
    const platform=current()==='contests/create-platform'||template.organizer==='platform';
    const field = (name, label, value, attrs = '') => `<div class="contest-form-field"><label for="contest-field-${name}">${label}</label><input id="contest-field-${name}" name="${name}" value="${esc(value)}" ${attrs} required aria-describedby="contest-error-${name}"><small id="contest-error-${name}" data-contest-field-error="${name}" hidden></small></div>`;
    const select = (name, label, values, chosen) => `<label class="field">${label}<select name="${name}">${values.map(x => `<option ${x === chosen ? 'selected' : ''}>${x}</option>`).join('')}</select></label>`;
    return `<form id="server-contest-form" data-simulation-sessions="${esc(JSON.stringify(sessions||null))}" data-id="${edit ? template.id : ''}"><div class="grid2"><section class="panel profileform"><h2>${edit ? 'Revise draft' : 'Contest details'}</h2>${field('name', 'Contest name', template.name, 'maxlength="80"')}<label class="field">Description<textarea name="description" maxlength="500">${esc(template.description)}</textarea></label>${platform?'<input type="hidden" name="visibility" value="public"><p class="callout">InvestIQ contest · public to everyone. Published contests accept verified learners without invitations.</p>':select('visibility','Visibility',['private','public'],template.visibility)}${select('level','Learning level',['all','beginner','advanced'],template.level)}${field('capacity','Maximum members',template.capacity,'type="number" min="1" max="10000"')}${field('capital','Virtual capital (INR)',r.capital,'type="number" min="1" max="100000000" step="0.01"')}<h3>Schedule · Asia/Kolkata</h3>${coverage}<p class="small">Entry opens → Entry closes → Contest starts → Contest ends. Check AM/PM when selecting times.</p>${['entry_opens_at','entry_closes_at','starts_at','ends_at'].map((x,i) => field(x,['Entry opens (IST)','Entry closes (IST)','Contest starts (IST)','Contest ends (IST)'][i],localTime(template[x]),'type="datetime-local" step="1"')).join('')}<p class="small">Start at an exchange session open, end at a session close. Reviewed 2026 calendar only.</p></section><section class="panel profileform"><h2>Portfolio rules</h2>${field('min_holdings','Minimum holdings',r.min_holdings,'type="number" min="1" max="100"')}${field('max_holdings','Maximum holdings',r.max_holdings,'type="number" min="1" max="100"')}${field('max_position_bps','Maximum position (basis points; 2500 = 25%)',r.max_position_bps,'type="number" min="100" max="10000"')}${field('simulated_cost_bps','Simulated cost (basis points; 10 = 0.1%)',r.simulated_cost_bps,'type="number" min="0" max="1000"')}<p class="small">Benchmark: ${esc(r.benchmark_id)}. Published EOD before entry lock; whole shares rounded down, residual cash allowed, cost once on submission notional, no in-contest trades.</p><fieldset data-contest-eligible-group aria-describedby="contest-error-eligible"><legend>Eligible stocks</legend><small id="contest-error-eligible" data-contest-field-error="eligible_instrument_ids" hidden></small>${instruments.map(i => `<label class="settingsrow"><span>${esc(i.symbol)} · ${esc(i.name)}</span><input type="checkbox" name="eligible" value="${esc(i.id)}" ${r.eligible_instrument_ids.includes(i.id) ? 'checked' : ''}></label>`).join('')}</fieldset><p>No real money, prize pool, XP, or coin issuance. Save a draft, then review and publish to freeze rules. Hosting does not automatically join you.</p><p role="alert" tabindex="-1" data-contest-form-error></p><button class="primary full" ${busy ? 'disabled' : ''}>${edit ? 'Save new rule version' : 'Save contest draft'}</button></section></div></form>`;
  }
  function creation() {
    if (!account()) return shell('contests', `${pagehead('Host', 'Create a contest', 'Sign in and verify your email to host.')}${link('Sign in', 'login')}`);
    if (!account().email_verified) return shell('contests', '<section class="panel">Verify your email before creating a contest.</section>');
    if(current()==='contests/create-platform'&&account().role!=='admin')return shell('contests','<section class="panel">Administrator access is required.</section>');
    return shell('contests', `${pagehead('Host', current()==='contests/create-platform'?'Create an InvestIQ contest':'Create a contest', 'Configure a draft. Published rules are immutable.')}${ready() || form(data.template,data.instruments)}`);
  }
  function inviteCard(i, host = false) {
    return `<article class="panel"><h3>${esc(i.contest_name)}</h3><p>${esc(i.email)} · ${esc(i.status)}</p><p class="small">Expires ${esc(stamp(i.expires_at))}</p>${!host&&i.status==='pending'?`<p class="small">Accepting reserves this contest’s capital from your virtual wallet.</p>${actionLink('Review contest','contests/'+i.contest_id,'arrow',false)}`:''}${i.status === 'pending' ? host ? button('revoke','Revoke invitation',i.id,'secondary') : button('accept','Accept invitation',i.id) + button('decline','Decline invitation',i.id,'ghost') : ''}</article>`;
  }
  function detail() {
    const wait = ready();
    if (wait) return shell('contests',wait);
    const c = data.contest, r = c.rules;
    const editable = c.can_manage && c.status === 'draft';
    if(account()?.role==='admin')return shell('contests',`${pagehead('InvestIQ public contest',esc(c.name),esc(c.description),actionLink('Back to contests','contests/admin','arrow'))}${!c.can_manage?'<section class="panel" role="alert">You cannot manage this contest.</section>':`${actionError?`<section class="callout" role="alert"><h2>Contest could not be updated</h2><p>${esc(actionError)}</p></section>`:''}<section class="panel"><div class="row"><h2>Contest overview</h2><span class="pill neutral">${esc(statusLabel(c.status))}</span></div><p>${c.member_count} / ${c.capacity} participants · ${c.rules.eligible_instrument_ids.length} eligible stocks · ${money(c.rules.capital)} virtual capital</p>${contestTimeline(c,{esc,stamp})}<div class="admin-editor-actions">${editable?button('publish','Publish and freeze rules',c.id):''}${['draft','scheduled','open'].includes(c.status)?button('cancel','Cancel contest',c.id,'secondary'):''}</div></section>${editable?form(c,data.instruments,true):'<p class="small">Published contest rules are fixed. Create a new contest to use different rules.</p>'}`}${controls()}`);
    const inviteable = c.can_manage && c.organizer!=='platform' && ['scheduled','open'].includes(c.status);
    const full=c.member_count>=c.capacity;
    const short=c.wallet_available!=null&&Number(c.wallet_available)<Number(r.capital);
    const joinAction=editable?button('publish','Publish and freeze rules',c.id):c.joined?actionLink('My Contests','my-contests','users',true):c.status==='open'&&!full?(account()?(short?'<button class="secondary" disabled>Insufficient wallet balance</button>':button('join','Reserve '+money(r.capital)+' &amp; join',c.id)):actionLink('Sign in to join','login','user',true)):`<span class="explorer-entry-state">${full&&c.status==='open'?'Contest full':statusLabel(c.status)}</span>`;
    return shell('contests',`${actionError?`<section class="panel" role="alert"><h2>Contest could not be updated</h2><p>${esc(actionError)}</p>${editable?'<p>Review the draft schedule below. Keep its start and end within this environment’s simulation coverage.</p>':''}</section>`:''}${explorerDetail(c,data,{esc,money,link,icon,pagehead,scheduleTime,timeline:contestTimeline(c,{esc,stamp}),joinAction,controls,timing})}${c.can_manage&&['draft','scheduled','open'].includes(c.status)?`<div class="explorer-host-controls">${button('cancel','Cancel contest',c.id,'ghost')}</div>`:''}${editable ? form(c,data.instruments,true) : ''}${inviteable ? `<form id="server-invitation-form" data-id="${c.id}" class="panel profileform"><h2>Invite a learner</h2><p>In-app invitation addressed to this email. It can be accepted after registering and verifying that address. No email is sent.</p><label class="field">Invite email<input name="email" type="email" required maxlength="320"></label><p data-contest-form-error role="alert"></p><button class="primary">Create invitation</button></form>` : ''}${c.can_manage && data.invites.items.length ? `<h2>Invitations</h2><div class="contest-grid">${data.invites.items.map(i => inviteCard(i,true)).join('')}</div>${data.invites.next_cursor ? button('more','Load more invitations',data.invites.next_cursor,'secondary') : ''}` : ''}`);
  }
  const knownNumber = value => value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
  const resultMoney = value => knownNumber(value)?'₹'+Number(value).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const resultChange = (value,currency=false) => !knownNumber(value)?'—':(Number(value)>0?'+':Number(value)<0?'−':'')+(currency?resultMoney(Math.abs(Number(value))):Math.abs(Number(value)).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})+'%');
  const changeTone = value => knownNumber(value)&&Number(value)!==0?(Number(value)>0?'is-gain':'is-loss'):'';
  function myContestCard(c) {
    const p=data.summary?.items.find(item=>item.contest_id===c.id),valued=c.joined&&knownNumber(p?.total_value);
    const submitted=p?.has_submission===true,unsubmitted=p?.has_submission===false;
    const cancelled=c.status==='cancelled',open=c.status==='open';
    let guidance='';
    if(c.joined){
      if(!p)guidance='Your results could not be loaded. Refresh to try again.';
      else if(valued)guidance=`Snapshot ${p.session_date} · ${cancelled?'Last recorded result · contest cancelled':p.is_final?'Final result':p.is_current?'Current · daily close':'Earlier snapshot · awaiting a newer valuation'}`;
      else if(cancelled)guidance='Contest cancelled. No further valuations will be published.';
      else if(submitted)guidance='Submission confirmed · Awaiting the first published valuation.';
      else guidance=open?'No confirmed submission · Save, review and confirm your portfolio before entry closes.':['running','locked','settling','completed'].includes(c.status)?'No confirmed submission · Entry is closed for this contest.':'No confirmed submission · Prepare your portfolio when entry opens.';
    }else guidance='Host overview · Join the contest to build your own portfolio.';
    const metric=(label,value,cls='',note='')=>`<div class="my-contest-metric ${cls}"><dt>${label}</dt><dd>${value}</dd>${note?`<span class="my-contest-metric-note">${note}</span>`:''}</div>`;
    const metrics=c.joined&&!valued?metric('Portfolio value','—','my-contest-value',`Starting capital ${money(c.rules.capital)}`)+metric('Submission',submitted?'Confirmed':unsubmitted?'Not confirmed':'Unavailable','my-contest-submission'):c.joined?
      metric('Portfolio value',resultMoney(valued?p.total_value:null),'my-contest-value',`Starting capital ${money(c.rules.capital)}`)+metric('Net P&amp;L',resultChange(valued?p.pnl:null,true),valued?changeTone(p.pnl):'')+metric('Net return',resultChange(valued?p.return_pct:null),valued?changeTone(p.return_pct):'')+metric('Your rank',valued&&knownNumber(p.rank)?'#'+esc(p.rank):'—'):
      metric('Members',String(c.member_count),'my-contest-value')+metric('Capacity',Number(c.capacity).toLocaleString('en-IN'))+metric('Virtual capital',money(c.rules.capital))+metric('Holdings',`${c.rules.min_holdings}–${c.rules.max_holdings}`);
    return `<article class="panel my-contest-card" data-contest-id="${esc(c.id)}" aria-label="${esc(c.name)}"><header class="my-contest-heading"><div><div class="my-contest-identity"><span>${c.organizer==='platform'?'InvestIQ · ':''}${esc(c.visibility==='public'?'Public':'Private')}</span><span class="contest-membership">${icon(c.joined?'check':'users')}${c.joined?'Joined':'Hosting'}</span>${c.joined?`<span class="my-contest-member-count">Members <span>${c.member_count} / ${c.capacity}</span></span>`:''}</div><h2>${esc(c.name)}</h2>${c.joined?`<p class="small">${c.wallet_backed?(c.status==='completed'?'Wallet funds returned':c.status==='cancelled'?'Wallet capital refunded':'Wallet-funded entry'):'Pre-wallet entry · excluded from wallet balance'}</p>`:''}</div><span class="contest-state contest-state-${esc(c.status)}"><i aria-hidden="true"></i>${esc(statusLabel(c.status))}</span></header>
      <dl class="my-contest-metrics ${c.joined&&!valued?'is-awaiting':''}" aria-label="${c.joined?'Your contest results':'Host overview'}">${metrics}</dl>
      <p class="my-contest-guidance ${unsubmitted&&open?'needs-action':''}" ${!p&&c.joined?'role="alert"':''}>${icon(valued?'chart':submitted?'check':unsubmitted&&open?'clock':'shield')}<span>${esc(guidance)}</span></p>
      <dl class="my-contest-dates" aria-label="Contest dates in IST"><div><dt>${cancelled?'Planned start':'Starts'} · IST</dt><dd>${scheduleTime(c.starts_at,true)}</dd></div><div><dt>${cancelled?'Planned end':'Ends'} · IST</dt><dd>${scheduleTime(c.ends_at,true)}</dd></div><div><dt>${open?'Entry closes':['draft','scheduled'].includes(c.status)?'Entry opens':cancelled?'Entry cancelled':'Entry closed'}</dt><dd>${cancelled?'—':scheduleTime(['draft','scheduled'].includes(c.status)?c.entry_opens_at:c.entry_closes_at,true)}</dd></div></dl>
      <footer class="my-contest-footer"><nav class="contest-actions" aria-label="Actions for ${esc(c.name)}">${c.joined?((valued||!['open','scheduled'].includes(c.status))?actionLink('Performance','performance/'+c.id,'chart',true)+actionLink('Portfolio','portfolio/'+c.id,'wallet'):actionLink('Portfolio','portfolio/'+c.id,'wallet',true)+actionLink('Performance','performance/'+c.id,'chart')):''}${actionLink('Leaderboard','leaderboard/'+c.id,'trophy')}${actionLink('View contest','contests/'+c.id,'arrow',!c.joined)}</nav><details class="my-contest-details"><summary>Schedule &amp; details</summary><p>${esc(c.description)}</p>${contestTimeline(c,{esc,stamp})}</details></footer></article>`;
  }
  function mine() {
    if (!account()) return shell('my-contests',`${pagehead('Contest dashboard','My Contests','Sign in to see your memberships and invitations.')}${link('Sign in','login')}`);
    const wait=ready();
    const body=wait||`<div class="my-contest-list ${data.items.length>1?'has-many':''}">${data.items.map(myContestCard).join('')||'<section class="panel empty">No contests in this view.</section>'}</div>${more()}<section class="my-contest-invitations" aria-label="My invitations"><h2>My invitations</h2>${data.invitationError?`<p role="alert">${esc(data.invitationError)} Refresh contests to retry.</p>`:`<div class="contest-grid">${data.invites.items.map(i=>inviteCard(i)).join('')||'<p>No invitations.</p>'}</div>`}${data.invites.next_cursor?button('invite-more','Load more invitations',data.invites.next_cursor,'secondary'):''}</section>`;
    return shell('my-contests',`${pagehead('Your contest workspace','My Contests','Review your results and pick up where you left off.',actionLink('Find contests','contests','search',true))}<div class="tabs my-contest-scopes" role="group" aria-label="Contest membership view">${['joined','hosted'].map(x=>`<button data-contest-action="scope" data-id="${x}" aria-pressed="${scope===x}" class="${scope===x?'active':''}">${x==='joined'?'Joined contests':'Hosted contests'}</button>`).join('')}</div>${body}${controls()}`);
  }
  function administration() {
    if(!account()||account().role!=='admin')return shell('contests','<section class="panel">Administrator access is required.</section>');
    return shell('contests',`${pagehead('Administration','InvestIQ contests','Create public contests for all learners. Review drafts and publish to open participation.',actionLink('Add InvestIQ contest','contests/create-platform','plus',true))}<p class="callout">${data?.marketStatus?.mode==='yahoo'?'Yahoo Finance end-of-day prices · Nifty 50 benchmark. Contests follow the reviewed 2026 trading calendar.':data?.simulationSessions?.length?`Simulation coverage: ${esc(data.simulationSessions[0])} – ${esc(data.simulationSessions.at(-1))}, on covered exchange sessions.`:'Simulation coverage follows the active environment.'} Prices are processed after 18:00 IST when available. Publication requires current submission prices and a supported schedule. No real trades or payouts.</p>${ready()||`<div class="contest-grid">${data.items.map(card).join('')||'<section class="panel">No InvestIQ contests yet.</section>'}</div>${more()}`}${controls()}`);
  }
  async function click(element) {
    const { contestAction: action, id } = element.dataset;
    if (busy || element.disabled) return;
    if(action==='copy-link'){
      try{await navigator.clipboard.writeText(new URL('#/contests/'+id,location.href).href);toast('Contest link copied.');}catch{toast('Copy the contest URL from your address bar.');}return;
    }
    if (action === 'filter') { filter = id; invalidate(); render(); return; }
    if (action === 'scope') { scope = id; invalidate(); render(); return; }
    if (action === 'reload') { invalidate(); render(); return; }
    if (action === 'more') { load(id); return; }
    if (action === 'join' && data?.contest && !window.confirm('Reserve '+money(data.contest.rules.capital)+' from your virtual wallet to join this contest? These funds stay invested until final results.')) return;
    if (action === 'cancel' && !window.confirm('Cancel this contest? It cannot be reopened. Membership history will be retained.')) return;
    const expected = account()?.id, token = generation;
    busy = true; actionError=''; element.disabled = true;
    try {
      if (action === 'invite-more') {
        const page = await contestApi.invitations({ cursor:id });
        if (token === generation && expected === account()?.id) data.invites = { ...page, items:[...data.invites.items,...page.items] };
      } else {
        if(action==='accept'){
          const invitation=data?.invites?.items.find(i=>i.id===id);
          if(!invitation)throw new Error('Refresh invitations before accepting.');
          const contest=await contestApi.get(invitation.contest_id);
          if(expected!==account()?.id||token!==generation)return;
          if(contest.wallet_available!=null&&Number(contest.wallet_available)<Number(contest.rules.capital))throw new Error('This contest requires '+money(contest.rules.capital)+', but your available wallet balance is '+money(contest.wallet_available)+'.');
          if(!window.confirm('Reserve '+money(contest.rules.capital)+' from your virtual wallet and accept this invitation? Funds return after final results.'))return;
        }
        if (['publish','cancel'].includes(action)) await contestApi.transition(id,action);
        else if (action === 'join') await contestApi.join(id);
        else await contestApi.invitationAction(id,action);
        document.dispatchEvent(new CustomEvent('investiq:wallet-changed'));
        if (expected !== account()?.id) return;
        invalidate();
        if (action === 'join' || action === 'accept') location.hash = '/my-contests';
        toast('Contest updated.');
      }
    } catch (e) { if (expected === account()?.id) {actionError=e.message;toast(e.message);} }
    finally { busy = false; if (expected === account()?.id) render(); }
  }
  function change(element) {
    const form=element.closest('#server-contest-form');
    if(form){showContestFormErrors(form,contestFormIssues(new FormData(form),JSON.parse(form.dataset.simulationSessions||'null')),{focus:false});return;}
    if (element.id === 'server-contest-query') query = element.value;
    else if (element.id === 'server-contest-status') status = element.value;
    else if (element.id === 'server-contest-sort') sort = element.value;
    else return;
    invalidate(); render();
  }
  async function submit(formElement) {
    if (busy) return;
    const expected = account()?.id, values = new FormData(formElement);
    if(formElement.id==='server-contest-form'){
      clearContestFormErrors(formElement);
      const issues=contestFormIssues(values,JSON.parse(formElement.dataset.simulationSessions||'null'));
      if(issues.length){showContestFormErrors(formElement,issues);return;}
    }
    let succeeded = false;
    const button = formElement.querySelector('button');
    busy = true; button.disabled = true;
    try {
      if (formElement.id === 'server-invitation-form') {
        await contestApi.invite(formElement.dataset.id, String(values.get('email')));
        if (expected !== account()?.id) return;
        invalidate(); render(); toast('In-app invitation created.');
      } else {
        const template = data.contest || data.template;
        const input = Object.fromEntries(['name','description','visibility','level'].map(x => [x,String(values.get(x))]));
        input.capacity = Number(values.get('capacity'));
        for (const x of ['entry_opens_at','entry_closes_at','starts_at','ends_at']) input[x] = new Date(String(values.get(x)) + '+05:30').toISOString();
        input.rules = { ...template.rules, capital:String(values.get('capital')), eligible_instrument_ids:values.getAll('eligible') };
        for (const x of ['min_holdings','max_holdings','max_position_bps','simulated_cost_bps']) input.rules[x] = Number(values.get(x));
        const serialized = JSON.stringify(input);
        if (lastPayload && lastPayload !== serialized) creationKey = crypto.randomUUID();
        lastPayload = serialized;
        const c = formElement.dataset.id ? await contestApi.revise(formElement.dataset.id,input) : current()==='contests/create-platform'?await contestApi.createPlatform(input,creationKey):await contestApi.create(input,creationKey);
        if (expected !== account()?.id) return;
        creationKey = crypto.randomUUID(); invalidate(); location.hash = '/contests/' + c.id; render(); toast('Draft saved. Review before publishing.');
      }
      succeeded = true;
    } catch (e) { if (expected === account()?.id && formElement.isConnected) showContestFormErrors(formElement,contestApiIssues(e),{message:contestApiIssues(e).length?'':e.message}); }
    finally { busy = false; button.disabled = false; if(succeeded && expected === account()?.id) render(); }
  }
  return { deactivate: () => { stopClock();if(loading || data?.summary) invalidate(); }, page: id => ['create','create-platform'].includes(id) ? creation() : id==='admin'?administration():id ? detail() : discovery(), mine, ensure, reset, click, change, submit };
}
