import { contestTimeline } from './results-info.js';
import { performanceApi, contestApi } from '../api/services.js';

export function createPerformanceController({shell,pagehead,esc,link,render,current,getAccount}) {
  let key='',generation=0,loaded=false,loading=false,error='',data=null;
  const routeKey=()=>JSON.stringify([current(),getAccount()?.id]);
  const amount=x=>x===null||x===undefined?'Awaiting valuation':'₹'+esc(String(x));
  const percent=x=>x===null||x===undefined?'—':esc(String(x).replace(/(\.\d*?[1-9])0+$|\.0+$/,'$1'))+'%';
  const stamp=x=>new Date(x).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  const kind=()=>({home:'dashboard'}[current().split('/')[0]]||current().split('/')[0]);
  const contestId=()=>current().split('/')[1];
  function reset(){key='';generation++;loaded=false;loading=false;error='';data=null;}
  function button(action,label,cursor=''){return `<button class="secondary" data-performance-action="${action}" data-cursor="${esc(cursor)}" ${loading?'disabled':''}>${label}</button>`;}
  async function load(more='') {
    const expected=routeKey(),token=++generation,id=contestId(),page=kind();
    key=expected;loading=true;error='';
    try {
      let result;
      if(page==='dashboard') result=await performanceApi.dashboard();
      else if(page==='contest-history') {
        result=await performanceApi.history(more?{cursor:more}:{});
        if(more) result.items=[...(data?.items||[]),...result.items];
      } else if(!id) {
        result=page==='performance'?await contestApi.mine(more?{cursor:more}:{}):await contestApi.list(more?{cursor:more}:{});
        if(more) result.items=[...(data?.items||[]),...result.items];
      } else if(page==='leaderboard') {
        result=await performanceApi.leaderboard(id,more?{cursor:more,run_id:data.run_id}:{});
        if(more) result.items=[...data.items,...result.items];
      } else {
        result=await performanceApi.performance(id,more?{cursor:more}:{});
        if(more) result.series=[...data.series,...result.series];
      }
      if(token!==generation || expected!==routeKey()) return;
      data=result;loaded=true;
    } catch(e) {if(token===generation&&expected===routeKey()){error=e.message;loaded=true;}}
    finally {if(token===generation&&expected===routeKey()){loading=false;render();}}
  }
  function ensure(){if(key!==routeKey())load();}
  function pending(){if(key!==routeKey()||!loaded)return '<section class="panel empty" role="status">Loading simulation results…</section>';if(error)return `<section class="panel" role="alert"><p>${esc(error)}</p>${button('refresh','Retry results')}</section>`;return '';}
  function explanation(code){return {market_data_incomplete:'Waiting for a complete set of published closing prices.',calendar_unavailable:'The exchange calendar needs review before results can be calculated.',unsupported_session:'A changed or special exchange session needs review.'}[code]||'Results are waiting for a review of price and portfolio evidence.';}
  function status(d){
    const t=d.timing,session=d.session_date||d.metrics?.session_date;
    const titles={draft:'Contest draft',cancelled:'Contest cancelled',not_started:'Contest has not started',awaiting_close:'Waiting for the session close',awaiting_data:'Waiting for complete valuation data',processing:'Valuation is being prepared',current:'Current published snapshot',final:'Final simulated results',unavailable:'Valuation schedule unavailable'};
    const messages={draft:'Publish the contest to open participation.',cancelled:'No further valuations will be calculated for this cancelled contest.',not_started:'Rankings and portfolio metrics appear after the first published contest close. A confirmed submission is saved while you wait.',awaiting_close:'The contest is running. Results will appear after its next closing prices are published and processed.',awaiting_data:'The valuation is delayed while complete price and portfolio evidence is checked.',processing:'The scheduled publication time has passed. Results will appear when complete closing prices have been processed.',current:'These results use the latest complete published closing prices.',final:'The final simulated standings have been recorded.',unavailable:'The exchange schedule needs review before a valuation time can be confirmed.'};
    const title=session&&!d.is_current&&!d.is_final&&t?.state==='current'?'Earlier published snapshot':titles[t?.state]||'Awaiting valuation';
    return `${contestTimeline(t,{esc,stamp})}<section class="callout" aria-label="Results status"><strong>${title}</strong><p>${messages[t?.state]||''}</p>${t?.next_results_available_at&&!['cancelled','final','draft','awaiting_data','processing'].includes(t.state)?`<p>Next results expected after <strong>${esc(stamp(t.next_results_available_at))}</strong>.</p>`:''}${d.error_code?`<p>${esc(explanation(d.error_code))}</p>`:''}${d.expected_session_date?`<p>Latest due session: ${esc(d.expected_session_date)}.</p>`:''}${session?`<p>Displayed snapshot ${esc(session)}${d.valued_at?' · '+esc(stamp(d.valued_at)):''}. ${!d.is_current?'These results are from an earlier snapshot.':''}</p>`:''}<p class="small">Synthetic prices and virtual portfolios. Refresh this page’s results after the expected publication time to check for updates.</p>${button('refresh','Refresh results')}</section>`;
  }
  function submissionInfo(d){
    if(d.has_submission&&d.contest_status==='cancelled')return '<section class="panel" aria-label="Your submission"><h2>Submission confirmed</h2><p>Your confirmed portfolio is retained in history. This contest was cancelled, so no further results will be calculated.</p></section>';
    if(d.has_submission)return `<section class="panel" aria-label="Your submission"><h2>Submission confirmed</h2><p>${d.metrics||d.session_date?'Your confirmed portfolio is saved. Recorded results are shown below.':'Your confirmed portfolio is saved. Your rank and performance metrics will appear after a complete contest valuation.'}</p></section>`;
    const editable=d.contest_status==='open';
    return `<section class="panel" aria-label="Your submission"><h2>No confirmed submission</h2><p>${editable?'Save your portfolio draft, review the calculation, then confirm your submission before the entry deadline.':d.contest_status==='scheduled'?'Entries have not opened yet. Confirm a portfolio during the entry window to participate.':'Entry is closed. Your account has no confirmed portfolio for this contest.'} Saved drafts are not ranked.</p>${link(editable?'Open portfolio builder':'View saved portfolio','portfolio/'+contestId(),'secondary')}</section>`;
  }
  function metricGuide(){return `<section class="panel" style="margin-top:20px"><h2>What will appear after valuation</h2><ul><li><strong>Portfolio value and return:</strong> holdings plus residual cash, with the submission fee already included.</li><li><strong>Benchmark comparison:</strong> your return, benchmark return and excess return in percentage points.</li><li><strong>Concentration and diversification:</strong> largest position, equity concentration and sector count.</li><li><strong>Drawdown:</strong> the largest decline from an earlier peak across recorded daily closes.</li><li><strong>Holding contributions:</strong> each holding’s price gain or loss, with the portfolio fee shown separately.</li></ul><p class="small">Detailed portfolio performance belongs to the participating account. Administrators can view public standings; another learner’s holdings and private metrics remain private.</p></section>`;}
  function contestCards(items,destination){return `<div class="contest-grid">${items.map(c=>`<article class="panel"><h2>${esc(c.name)}</h2><p>${esc(c.status==='settling'?'finalizing results':c.status)}</p>${link('View '+(destination==='leaderboard'?'leaderboard':'performance'),destination+'/'+(c.contest_id||c.id))}</article>`).join('')||'<section class="panel empty">No contests in this view.</section>'}</div>`;}
  function summaryCards(items){return `<div class="grid4">${items.map(([label,value])=>`<section class="panel stat"><p class="small">${label}</p><div class="num">${value}</div></section>`).join('')}</div>`;}
  function dashboard(){
    const wait=pending();
    if(wait)return shell('dashboard',wait);
    return shell('dashboard',`${pagehead('Your simulation workspace','Hi, '+esc(getAccount()?.name||''),'Your recorded contest activity and latest available simulated results.',link('Contest history','contest-history','secondary'))}${summaryCards([['Contests joined',data.joined_count],['Active contests',data.active_count],['Completed contests',data.completed_count],['Contest wins',data.wins]])}<div class="grid2" style="margin-top:22px"><section class="panel"><h2>Latest valued portfolios</h2><p>${amount(data.latest_snapshot_value)} across ${data.valued_count} valued contests.</p><p>Net simulated P&amp;L ${amount(data.latest_snapshot_pnl)}</p><p class="small">${data.submitted_count} contests have an accepted submission. Totals exclude unvalued and cancelled contests. Each contest uses its own latest snapshot date; this is not a common-time global return.</p>${!data.all_valued_current?'<p class="callout">Some results are pending or out of date. Review each contest’s snapshot date.</p>':''}</section><section class="panel"><h2>Build and compete</h2>${link('Find a contest','contests')}${link('Portfolio builder','portfolio','secondary')}${button('refresh','Refresh results')}</section></div><div class="section-heading"><h2>Your contests</h2>${link('My Contests','my-contests','ghost')}</div>${contestTable(data.items)}`);
  }
  function contestTable(items){return `<div class="panel tablewrap"><table><thead><tr><th>Contest</th><th>Status</th><th>Snapshot</th><th>Value</th><th>Return</th><th>Rank</th><th></th></tr></thead><tbody>${items.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.status==='settling'?'finalizing results':c.status)}${c.is_final?' · final':''}</td><td>${esc(c.session_date||'Not valued')}${c.session_date&&!c.is_current?' · older snapshot':''}</td><td>${amount(c.total_value)}</td><td>${percent(c.return_pct)}</td><td>${c.rank??'—'}</td><td>${link('Performance','performance/'+c.contest_id,'ghost')}${link('Leaderboard','leaderboard/'+c.contest_id,'ghost')}</td></tr>`).join('')||'<tr><td colspan="7">No recorded contest activity.</td></tr>'}</tbody></table></div>`;}
  function leaderboard(){
    const wait=pending();if(wait)return shell('leaderboard',wait);
    if(!contestId())return shell('leaderboard',`${pagehead('Compete','Contest leaderboards','Rankings are calculated within each contest at a common market close. Choose a contest to view its published rankings.')}${contestCards(data.items,'leaderboard')}${data.next_cursor?button('more','Load more contests',data.next_cursor):''}`);
    return shell('leaderboard',`${pagehead('Contest leaderboard',esc(data.contest_name),'Net simulated return, then lower drawdown, earlier submission, and entry ID break ties.',link('Choose another contest','leaderboard','ghost'))}${status(data)}<p>Members: ${data.member_count} · Confirmed portfolios: ${data.submitted_count} · Ranked portfolios: ${data.participant_count}. Rankings appear after valuation; saved drafts are not counted as submissions.</p>${data.has_joined?submissionInfo(data):'<p class="small">Detailed portfolio metrics are private to each participating account. Administrators can follow public standings here.</p>'}<section class="panel tablewrap"><table><thead><tr><th>Rank</th><th>Learner</th><th>Virtual value</th><th>Return</th><th>Benchmark</th><th>Excess (pp)</th><th>Max drawdown</th></tr></thead><tbody>${data.items.map(r=>`<tr><td>#${r.rank}</td><td>${esc(r.label)}${r.is_you?' · you':''}</td><td>${amount(r.total_value)}</td><td>${percent(r.return_pct)}</td><td>${percent(r.benchmark_return_pct)}</td><td>${percent(r.excess_return_pct).replace(/%$/,'')}</td><td>${percent(r.max_drawdown_pct)}</td></tr>`).join('')||'<tr><td colspan="7">No published ranking yet.</td></tr>'}</tbody></table>${data.next_cursor?button('more','Load more ranks',data.next_cursor):''}</section>${getAccount()&&data.has_joined?link('My performance','performance/'+contestId(),'secondary'):link('View contest','contests/'+contestId(),'secondary')}`);
  }
  function performance(){
    const wait=pending();if(wait)return shell('my-contests',wait);
    if(!contestId())return shell('my-contests',`${pagehead('Your results','Contest performance','Choose one of your contest memberships.')}${contestCards(data.items,'performance')}${data.next_cursor?button('more','Load more contests',data.next_cursor):''}`);
    const m=data.metrics;
    return shell('my-contests',`${pagehead('Your contest performance',esc(data.contest_name),'Metrics from your immutable accepted portfolio.',link('Leaderboard','leaderboard/'+contestId(),'secondary'))}${status(data)}${m?`${summaryCards([['Portfolio value',amount(m.total_value)],['Net return',percent(m.return_pct)],['Benchmark return',percent(m.benchmark_return_pct)],['Rank','#'+m.rank]])}<div class="grid2" style="margin-top:22px"><section class="panel"><h2>Portfolio metrics</h2><p>Starting virtual capital ${amount(m.capital)}.</p><p>Net P&amp;L ${amount(m.pnl)} · residual cash ${amount(m.cash)} · one simulated fee ${amount(m.fee)}</p><p>${m.holding_count} holdings across ${m.sector_count} sectors. Largest position ${percent(m.largest_position_pct)} of portfolio value.</p><p>Equity concentration HHI ${esc(m.concentration_hhi)} (lower means more spread across equities; cash is excluded).</p><p>Maximum daily-close drawdown ${percent(m.max_drawdown_pct)}. Excess return ${percent(m.excess_return_pct).replace(/%$/,'')} percentage points.</p><p class="small">Drawdown includes the initial simulated fee; intraday movements are not measured.</p></section><section class="panel"><h2>Holding contributions</h2><div class="tablewrap"><table><thead><tr><th>Holding</th><th>Shares</th><th>Value</th><th>Price P&amp;L</th></tr></thead><tbody>${m.positions.map(p=>`<tr><td>${esc(p.symbol)}</td><td>${p.quantity}</td><td>${amount(p.value)}</td><td>${amount(p.pnl)}</td></tr>`).join('')}</tbody></table></div><p class="small">Holding contributions exclude the single portfolio-level simulated fee.</p></section></div>`:`${submissionInfo(data)}${metricGuide()}`}<section class="panel" style="margin-top:22px"><h2>Daily snapshots</h2><div class="tablewrap"><table><thead><tr><th>Close</th><th>Virtual value</th><th>Return</th><th>Benchmark</th><th>Drawdown</th></tr></thead><tbody>${data.series.map(s=>`<tr><td>${esc(s.session_date)}</td><td>${amount(s.total_value)}</td><td>${percent(s.return_pct)}</td><td>${percent(s.benchmark_return_pct)}</td><td>${percent(s.max_drawdown_pct)}</td></tr>`).join('')||'<tr><td colspan="5">No successful daily snapshots.</td></tr>'}</tbody></table></div>${data.next_cursor?button('more','Load earlier snapshots',data.next_cursor):''}</section>${link('Submission history','portfolio/'+contestId(),'ghost')}`);
  }
  function page(){
    const k=kind();
    if(k!=='leaderboard'&&!getAccount())return shell('my-contests',`${pagehead('Your results','Sign in to view your results','Contest performance belongs to your account.')}${link('Sign in','login')}`);
    if(k==='dashboard')return dashboard();
    if(k==='leaderboard')return leaderboard();
    if(k==='contest-history'){const wait=pending();return shell('my-contests',`${pagehead('Your history','Completed contests','Finalized simulations and cancelled contests.')}${wait||contestTable(data.items)}${!wait&&data.next_cursor?button('more','Load more contests',data.next_cursor):''}${button('refresh','Refresh results')}`);}
    return performance();
  }
  function click(buttonEl){if(buttonEl.disabled)return;if(buttonEl.dataset.performanceAction==='more')load(buttonEl.dataset.cursor);else{reset();render();}}
  return {page,ensure,reset,click,deactivate:()=>{if(loading)reset();}};
}
