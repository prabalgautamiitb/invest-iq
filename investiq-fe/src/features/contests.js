import { contestTimeline } from './results-info.js';
import { contestApi, performanceApi } from '../api/services.js';
import { marketApi } from '../api/market.js';

// Account-scoped, memory-only data. Route/request generations discard obsolete responses.
export function createContestController({ shell, pagehead, esc, money, link, toast, render, current, getAccount }) {
  let generation = 0, key = '', loading = false, loaded = false, error = '', data = null;
  let query = '', filter = 'All', status = '', sort = 'name', scope = 'joined';
  let selected = '', busy = false, lastPayload = '', creationKey = crypto.randomUUID();
  const stamp = value => new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) + ' IST';
  const localTime = value => {
    const d = new Date(new Date(value).getTime() + 330 * 60000);
    return d.toISOString().slice(0, 19);
  };
  const account = () => getAccount();
  const routeKey = () => JSON.stringify([current(), account()?.id, query, filter, status, sort, scope]);
  function invalidate() { generation++; key = ''; loaded = false; loading = false; data = null; error = ''; }
  function reset() { invalidate(); busy = false; selected = ''; query = ''; filter = 'All'; status = ''; scope = 'joined'; lastPayload = ''; creationKey = crypto.randomUUID(); }
  const params = () => ({ query, sort, ...(filter === 'InvestIQ' ? { organizer: 'platform' } : {}), ...(filter === 'Public' ? { visibility: 'public' } : filter === 'Private' ? { visibility: 'private' } : ['Beginner', 'Advanced'].includes(filter) ? { level: filter.toLowerCase() } : {}), ...(status ? { status } : {}) });
  async function load(more = '') {
    const route = current(), expected = routeKey();
    const token = ++generation;
    key = expected; loading = true; error = '';
    try {
      let result;
      if (['contests/create','contests/create-platform'].includes(route)) {
        const [template, instruments] = await Promise.all([contestApi.template(), marketApi.instruments({ limit: 100, eligible_only: false })]);
        if(route.endsWith('create-platform')){template.visibility='public';template.name='InvestIQ public simulation';template.capacity=10000;}
        result = { template, instruments: instruments.items };
      } else if (route === 'contests/admin') {
        result = await contestApi.list({scope:'managed',...(more?{cursor:more}:{})});
        if(more)result.items=[...(data?.items||[]),...result.items];
      } else if (route.startsWith('contests/')) {
        const id = route.split('/')[1];
        const c = await contestApi.get(id);
        const invites = c.can_manage && c.status !== 'draft' ? await contestApi.hostedInvitations(id, more ? { cursor: more } : {}) : { items: [], next_cursor: null };
        result = { contest: c, invites: more ? { ...invites, items: [...(data?.invites.items || []), ...invites.items] } : invites };
        if (c.status === 'draft' && c.can_manage) {
          const instruments = await marketApi.instruments({ limit: 100, eligible_only: false });
          result.instruments = instruments.items;
        }
      } else if (route === 'my-contests') {
        if (!account()) { result = { items: [], next_cursor: null, invites: { items: [] } }; }
        else {
          const [page, invites, summary] = await Promise.all([contestApi.mine({ scope, ...(more ? { cursor: more } : {}) }), contestApi.invitations(), performanceApi.dashboard()]);
          result = { ...page, items: more ? [...(data?.items || []), ...page.items] : page.items, invites, summary };
        }
      } else {
        const page = await contestApi.list({ ...params(), ...(more ? { cursor: more } : {}) });
        result = { ...page, items: more ? [...(data?.items || []), ...page.items] : page.items };
      }
      if (token !== generation || expected !== routeKey()) return;
      data = result; loaded = true;
    } catch (e) {
      if (token !== generation || expected !== routeKey()) return;
      error = e.message; loaded = true;
    } finally {
      if (token === generation && expected === routeKey()) { loading = false; render(); }
    }
  }
  function ensure() { if (key !== routeKey()) load(); }
  function ready() {
    if (key !== routeKey() || (!loaded && !error)) return '<section class="panel empty" role="status">Loading contests…</section>';
    if (error) return `<section class="panel" role="alert"><p>${esc(error)}</p><button class="secondary" data-contest-action="reload">Try again</button></section>`;
    return '';
  }
  function controls() { return `<button class="ghost" data-contest-action="reload" ${loading ? 'disabled' : ''}>Refresh contests</button>`; }
  const button = (action, text, id = '', cls = 'primary') => `<button class="${cls}" data-contest-action="${action}" data-id="${esc(id)}" ${busy ? 'disabled' : ''}>${text}</button>`;
  function card(c) {
    const performance = data?.summary?.items?.find(i=>i.contest_id===c.id);
    return `<article class="panel contestcard"><div class="row"><span class="pill neutral">${c.organizer==='platform'?'InvestIQ · ':''}${esc(c.visibility)} · ${esc(c.status==='settling'?'finalizing results':c.status)}</span><span class="small">${esc(c.level)}</span></div><h3>${esc(c.name)}</h3><p>${esc(c.description)}</p><div class="contest-info"><div><span class="small">Virtual capital</span><strong>${money(c.rules.capital)}</strong></div><div><span class="small">Members</span><strong>${c.member_count} / ${c.capacity}</strong></div></div><p class="small">Entry closes ${esc(stamp(c.entry_closes_at))}<br>Starts ${esc(stamp(c.starts_at))}${c.first_results_available_at?'<br>First results expected after '+esc(stamp(c.first_results_available_at)):''}</p>${performance?.total_value ? `<p>Virtual value ₹${esc(performance.total_value)} · return ${esc(performance.return_pct)}% · rank #${performance.rank}</p><p class="small">Snapshot ${esc(performance.session_date)} · ${performance.is_final?'final':performance.is_current?'current':'earlier snapshot'}</p>` : ''}<div class="row">${link('View contest →', 'contests/' + c.id)}${c.joined ? link('Portfolio','portfolio/'+c.id,'ghost')+link('Performance','performance/'+c.id,'ghost') : ''}${link('Leaderboard','leaderboard/'+c.id,'ghost')}<span>${c.joined ? 'Joined' : c.is_owner ? 'Hosting' : 'Free entry'}</span></div></article>`;
  }
  function more() { return data?.next_cursor ? button('more', loading ? 'Loading…' : 'Load more contests', data.next_cursor, 'secondary') : ''; }
  function discovery() {
    return shell('contests', `${pagehead('Compete', 'Contest explorer', 'Join an InvestIQ public contest or explore community leagues. Submit a portfolio before entry closes, then follow its standings.', link('Create contest →', 'contests/create')+(account()?.role==='admin'?link('Manage InvestIQ contests','contests/admin','secondary'):''))}<label class="field">Search contests<input id="server-contest-query" maxlength="100" value="${esc(query)}" placeholder="Search name or description"></label><div class="tabs">${['All', 'InvestIQ', 'Public', 'Private', 'Beginner', 'Advanced'].map(x => `<button data-contest-action="filter" data-id="${x}" class="${filter === x ? 'active' : ''}">${x}</button>`).join('')}</div><details class="page-details"><summary>More filters</summary><div class="grid2"><label class="field">Contest status<select id="server-contest-status"><option value="">All statuses</option>${['draft','scheduled','open','locked','running','settling','completed','cancelled'].map(x => `<option ${status === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label><label class="field">Sort contests<select id="server-contest-sort"><option value="name">Name A–Z</option><option value="-name" ${sort === '-name' ? 'selected' : ''}>Name Z–A</option></select></label></div></details>${ready() || `<div class="contest-grid">${data.items.map(card).join('') || '<section class="panel empty">No contests match. Check another filter or come back for the next public contest.</section>'}</div>${more()}`}${controls()}`);
  }
  function form(template, instruments, edit = false) {
    const r = template.rules;
    const platform=current()==='contests/create-platform'||template.organizer==='platform';
    const field = (name, label, value, attrs = '') => `<label class="field">${label}<input name="${name}" value="${esc(value)}" ${attrs} required></label>`;
    const select = (name, label, values, chosen) => `<label class="field">${label}<select name="${name}">${values.map(x => `<option ${x === chosen ? 'selected' : ''}>${x}</option>`).join('')}</select></label>`;
    return `<form id="server-contest-form" data-id="${edit ? template.id : ''}"><div class="grid2"><section class="panel profileform"><h2>${edit ? 'Revise draft' : 'Contest details'}</h2>${field('name', 'Contest name', template.name, 'maxlength="80"')}<label class="field">Description<textarea name="description" maxlength="500">${esc(template.description)}</textarea></label>${platform?'<input type="hidden" name="visibility" value="public"><p class="callout">InvestIQ contest · public to everyone. Published contests accept verified learners without invitations.</p>':select('visibility','Visibility',['private','public'],template.visibility)}${select('level','Learning level',['all','beginner','advanced'],template.level)}${field('capacity','Maximum members',template.capacity,'type="number" min="1" max="10000"')}${field('capital','Virtual capital (INR)',r.capital,'type="number" min="1" max="100000000" step="0.01"')}<h3>Schedule · Asia/Kolkata</h3>${['entry_opens_at','entry_closes_at','starts_at','ends_at'].map((x,i) => field(x,['Entry opens (IST)','Entry closes (IST)','Contest starts (IST)','Contest ends (IST)'][i],localTime(template[x]),'type="datetime-local" step="1"')).join('')}<p class="small">Start at an exchange session open, end at a session close. Reviewed 2026 calendar only.</p></section><section class="panel profileform"><h2>Portfolio rules</h2>${field('min_holdings','Minimum holdings',r.min_holdings,'type="number" min="1" max="100"')}${field('max_holdings','Maximum holdings',r.max_holdings,'type="number" min="1" max="100"')}${field('max_position_bps','Maximum position (basis points; 2500 = 25%)',r.max_position_bps,'type="number" min="100" max="10000"')}${field('simulated_cost_bps','Simulated cost (basis points; 10 = 0.1%)',r.simulated_cost_bps,'type="number" min="0" max="1000"')}<p class="small">Benchmark: ${esc(r.benchmark_id)}. Published EOD before entry lock; whole shares rounded down, residual cash allowed, cost once on submission notional, no in-contest trades.</p><fieldset><legend>Eligible fixture equities</legend>${instruments.map(i => `<label class="settingsrow"><span>${esc(i.symbol)} · ${esc(i.name)}</span><input type="checkbox" name="eligible" value="${esc(i.id)}" ${r.eligible_instrument_ids.includes(i.id) ? 'checked' : ''}></label>`).join('')}</fieldset><p>No real money, prize pool, XP, or coin issuance. Save a draft, then review and publish to freeze rules. Hosting does not automatically join you.</p><p role="alert" data-contest-form-error></p><button class="primary full" ${busy ? 'disabled' : ''}>${edit ? 'Save new rule version' : 'Save contest draft'}</button></section></div></form>`;
  }
  function creation() {
    if (!account()) return shell('contests', `${pagehead('Host', 'Create a contest', 'Sign in and verify your email to host.')}${link('Sign in', 'login')}`);
    if (!account().email_verified) return shell('contests', '<section class="panel">Verify your email before creating a contest.</section>');
    if(current()==='contests/create-platform'&&account().role!=='admin')return shell('contests','<section class="panel">Administrator access is required.</section>');
    return shell('contests', `${pagehead('Host', current()==='contests/create-platform'?'Create an InvestIQ contest':'Create a contest', 'Configure a draft. Published rules are immutable.')}${ready() || form(data.template,data.instruments)}`);
  }
  function inviteCard(i, host = false) {
    return `<article class="panel"><h3>${esc(i.contest_name)}</h3><p>${esc(i.email)} · ${esc(i.status)}</p><p class="small">Expires ${esc(stamp(i.expires_at))}</p>${i.status === 'pending' ? host ? button('revoke','Revoke invitation',i.id,'secondary') : button('accept','Accept invitation',i.id) + button('decline','Decline invitation',i.id,'ghost') : ''}</article>`;
  }
  function detail() {
    const wait = ready();
    if (wait) return shell('contests',wait);
    const c = data.contest, r = c.rules;
    const editable = c.can_manage && c.status === 'draft';
    const inviteable = c.can_manage && c.organizer!=='platform' && ['scheduled','open'].includes(c.status);
    return shell('contests', `${pagehead((c.organizer==='platform'?'InvestIQ public':c.visibility) + ' contest', esc(c.name), esc(c.description))}${contestTimeline(c,{esc,stamp})}<div class="grid2"><section class="panel"><div class="row"><span class="pill">${esc(c.status==='settling'?'finalizing results':c.status)}</span><span>Rule version ${c.rule_version}</span></div><p>${c.member_count} / ${c.capacity} members · ${money(r.capital)} virtual capital</p><ul class="rules"><li>${r.min_holdings}–${r.max_holdings} holdings; maximum position ${r.max_position_bps / 100}%.</li><li>Simulated cost ${r.simulated_cost_bps / 100}% on submitted notional once.</li><li>${r.eligible_instrument_ids.length} eligible fixture equities. Benchmark ${esc(r.benchmark_id)}.</li><li>Published EOD before lock; floor to whole shares; residual cash allowed.</li><li>Portfolios lock before the start. No in-contest trades.</li></ul><p>Entry opens ${esc(stamp(c.entry_opens_at))}<br>Entry closes ${esc(stamp(c.entry_closes_at))}<br>Starts ${esc(stamp(c.starts_at))}<br>Ends ${esc(stamp(c.ends_at))}</p>${c.joined ? '<p class="positive">You joined this contest.</p>' : c.status === 'open' ? account() ? button('join','Join contest',c.id) : link('Sign in to join','login') : ''}${editable ? button('publish','Publish and freeze rules',c.id) : ''}${c.can_manage && ['draft','scheduled','open'].includes(c.status) ? button('cancel','Cancel contest',c.id,'ghost') : ''}</section><section class="panel"><h2>Contest progress</h2><p>Membership is saved on the server. Portfolio drafts and immutable submissions are available for joined members. Join, open your portfolio, save a draft, then review and confirm your submission before entry closes. A saved draft does not enter the rankings. Published EOD snapshots determine simulated returns and standings. Use the Performance and Leaderboard pages to follow results.</p>${c.joined ? link('Open contest portfolio','portfolio/'+c.id) : ''}${link('Leaderboard','leaderboard/'+c.id,'secondary')}${link('My Contests','my-contests','secondary')+(c.joined?link('My performance','performance/'+c.id,'secondary'):'')}${controls()}</section></div>${editable ? form(c,data.instruments,true) : ''}${inviteable ? `<form id="server-invitation-form" data-id="${c.id}" class="panel profileform"><h2>Invite a learner</h2><p>In-app invitation addressed to this email. It can be accepted after registering and verifying that address. No email is sent.</p><label class="field">Invite email<input name="email" type="email" required maxlength="320"></label><p data-contest-form-error role="alert"></p><button class="primary">Create invitation</button></form>` : ''}${c.can_manage && data.invites.items.length ? `<h2>Invitations</h2><div class="contest-grid">${data.invites.items.map(i => inviteCard(i,true)).join('')}</div>${data.invites.next_cursor ? button('more','Load more invitations',data.invites.next_cursor,'secondary') : ''}` : ''}`);
  }
  function mine() {
    if (!account()) return shell('my-contests',`${pagehead('Contest dashboard','My Contests','Sign in to see your memberships and invitations.')}${link('Sign in','login')}`);
    const wait = ready();
    let body = wait;
    if (!wait) {
      const c = data.items.find(x => x.id === selected) || data.items[0];
      body = `<div class="tabs">${data.items.map(x => `<button data-contest-action="select" data-id="${x.id}" class="${x.id === c?.id ? 'active' : ''}">${esc(x.name)}</button>`).join('')}</div>${c ? card(c) : '<section class="panel empty">No contests in this view.</section>'}<div class="contest-grid">${data.items.filter(x => x.id !== c?.id).map(card).join('')}</div>${more()}<h2>My invitations</h2><div class="contest-grid">${data.invites.items.map(i => inviteCard(i)).join('') || '<p>No invitations.</p>'}</div>${data.invites.next_cursor ? button('invite-more','Load more invitations',data.invites.next_cursor,'secondary') : ''}`;
    }
    return shell('my-contests',`${pagehead('Contest dashboard','My Contests','Server memberships, hosted contests, and private invitations.',link('Find contests →','contests'))}<div class="tabs">${['joined','hosted'].map(x => `<button data-contest-action="scope" data-id="${x}" class="${scope === x ? 'active' : ''}">${x === 'joined' ? 'Joined contests' : 'Hosted contests'}</button>`).join('')}</div>${body}${controls()}`);
  }
  function administration() {
    if(!account()||account().role!=='admin')return shell('contests','<section class="panel">Administrator access is required.</section>');
    return shell('contests',`${pagehead('Administration','InvestIQ contests','Create public contests for all learners. Review drafts and publish to open participation.',link('Add InvestIQ contest','contests/create-platform'))}<p class="callout">Fixed synthetic EOD scenario: October 14–November 6, 2026, on covered exchange sessions. Prices are released at 18:00 IST. Publication requires current submission prices and a supported schedule. No real trades or payouts.</p>${ready()||`<div class="contest-grid">${data.items.map(card).join('')||'<section class="panel">No InvestIQ contests yet.</section>'}</div>${more()}`}${controls()}`);
  }
  async function click(element) {
    const { contestAction: action, id } = element.dataset;
    if (busy || element.disabled) return;
    if (action === 'select') { selected = id; render(); return; }
    if (action === 'filter') { filter = id; invalidate(); render(); return; }
    if (action === 'scope') { scope = id; invalidate(); render(); return; }
    if (action === 'reload') { invalidate(); render(); return; }
    if (action === 'more') { load(id); return; }
    if (action === 'cancel' && !window.confirm('Cancel this contest? It cannot be reopened. Membership history will be retained.')) return;
    const expected = account()?.id, token = generation;
    busy = true; element.disabled = true;
    try {
      if (action === 'invite-more') {
        const page = await contestApi.invitations({ cursor:id });
        if (token === generation && expected === account()?.id) data.invites = { ...page, items:[...data.invites.items,...page.items] };
      } else {
        if (['publish','cancel'].includes(action)) await contestApi.transition(id,action);
        else if (action === 'join') await contestApi.join(id);
        else await contestApi.invitationAction(id,action);
        if (expected !== account()?.id) return;
        invalidate();
        if (action === 'join' || action === 'accept') location.hash = '/my-contests';
        toast('Contest updated.');
      }
    } catch (e) { if (expected === account()?.id) toast(e.message); }
    finally { busy = false; if (expected === account()?.id) render(); }
  }
  function change(element) {
    if (element.id === 'server-contest-query') query = element.value;
    else if (element.id === 'server-contest-status') status = element.value;
    else if (element.id === 'server-contest-sort') sort = element.value;
    else return;
    invalidate(); render();
  }
  async function submit(formElement) {
    if (busy) return;
    const expected = account()?.id, values = new FormData(formElement);
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
    } catch (e) { if (expected === account()?.id && formElement.isConnected) formElement.querySelector('[data-contest-form-error]').textContent = e.message; }
    finally { busy = false; button.disabled = false; if(succeeded && expected === account()?.id) render(); }
  }
  return { deactivate: () => { if(loading) invalidate(); }, page: id => ['create','create-platform'].includes(id) ? creation() : id==='admin'?administration():id ? detail() : discovery(), mine, ensure, reset, click, change, submit };
}
