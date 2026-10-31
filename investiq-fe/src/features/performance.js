import { returnChart, comparisonBars, allocationChart, portfolioValueChart } from './charts.js';
import { contestTimeline } from './results-info.js';
import { performanceApi, contestApi, coachApi } from '../api/services.js';
import { marketApi } from '../api/market.js';
import { newsPlaceholder } from './market-news.js';
import { homeContestCards } from './home-contests.js';

export function createPerformanceController({shell,pagehead,esc,link,icon,render,current,getAccount}) {
  let key='',generation=0,loaded=false,loading=false,error='',data=null,homeId='',pollTimer=null;
  const homeRequests=new Map();
  function stop(){clearTimeout(pollTimer);pollTimer=null;}
  function poll(){
    stop();
    if(kind()!=='dashboard'||!getAccount()||!data?.home)return;
    const pending=data.home.jobs?.items?.some(j=>['queued','running','retry'].includes(j.status));
    const expected=routeKey(),token=generation;
    pollTimer=setTimeout(()=>{if(token===generation&&expected===routeKey())load('',true);},pending?5000:60000);
  }

  const routeKey=()=>JSON.stringify([current(),getAccount()?.id]);
  const amount=x=>x===null||x===undefined?'Awaiting valuation':'₹'+esc(Number(x).toLocaleString('en-IN',{maximumFractionDigits:2}));
  const percent=x=>x===null||x===undefined?'—':esc(Number(x).toLocaleString('en-IN',{maximumFractionDigits:2}))+'%';
  function movement(value,format=percent,drawdown=false){
    const available=value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
    const n=Number(value),tone=!available?'unavailable':n===0?'flat':drawdown||n<0?'loss':'gain';
    return `<span class="performance-change is-${tone}">${format(available?value:null)}</span>`;
  }
  const stamp=x=>new Date(x).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  const kind=()=>({home:'dashboard'}[current().split('/')[0]]||current().split('/')[0]);
  const contestId=()=>current().split('/')[1];
  function reset(){stop();homeRequests.clear();key='';generation++;loaded=false;loading=false;error='';data=null;homeId='';}
  function button(action,label,cursor=''){return `<button class="secondary" data-performance-action="${action}" data-cursor="${esc(cursor)}" ${loading?'disabled':''}>${label}</button>`;}
  async function load(more='',background=false) {
    stop();
    const previous=JSON.stringify(data),previousError=error;
    const expected=routeKey(),token=++generation,id=contestId(),page=kind();
    key=expected;loading=true;error='';if(!data)loaded=false;
    try {
      let result;
      if(page==='dashboard') {
        if(more&&data?.home?.performance){
          const earlier=await performanceApi.performance(data.home.id,{cursor:more});
          result={...data,home:{...data.home,performance:{...data.home.performance,series:[...data.home.performance.series,...earlier.series],next_cursor:earlier.next_cursor}}};
        }else{
          result=await performanceApi.dashboard();
          const selected=result.items.find(c=>c.contest_id===homeId)||result.items.filter(c=>c.total_value!==null&&c.status!=='cancelled').slice().sort((a,b)=>(b.session_date||'').localeCompare(a.session_date||''))[0]||result.items[0];
          result.home={id:selected?.contest_id||'',performance:null,jobs:null,settings:null,chartError:'',coachError:'',generateError:''};
          if(selected){
            const [valuation,reports,settings]=await Promise.allSettled([performanceApi.performance(selected.contest_id),coachApi.jobs({contest_id:selected.contest_id}),coachApi.settings()]);
            if(valuation.status==='fulfilled')result.home.performance=valuation.value;else result.home.chartError=valuation.reason.message||'Portfolio values could not be loaded.';
            if(settings.status==='fulfilled')result.home.settings=settings.value;
            if(reports.status==='fulfilled')result.home.jobs=reports.value;else result.home.coachError=reports.reason.message||'AI insights could not be loaded.';
          }
        }
      }
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
      if(page==='dashboard'&&!more){
        result.marketStatus=await marketApi.status().catch(()=>null);
        result.benchmark=null;
        if(result.marketStatus?.mode==='yahoo'&&result.marketStatus.benchmark_id){
          try{result.benchmark=await marketApi.quotes([result.marketStatus.benchmark_id]);}catch{}
        }
      }
      if(token!==generation || expected!==routeKey()) return;
      data=result;if(page==='dashboard')homeId=result.home.id;loaded=true;
    } catch(e) {if(token===generation&&expected===routeKey()){error=e.message;loaded=true;}}
    finally {if(token===generation&&expected===routeKey()){loading=false;if(!background||previous!==JSON.stringify(data)||previousError!==error)render();if(page==='dashboard')poll();}}
  }
  function ensure(){if(key!==routeKey())load();else if(!loading)poll();}
  function pending(){if(key!==routeKey()||!loaded)return '<section class="panel empty" role="status">Loading simulation results…</section>';if(error)return `<section class="panel" role="alert"><p>${esc(error)}</p>${button('refresh','Retry results')}</section>`;return '';}
  function explanation(code){return {market_data_incomplete:'Waiting for a complete set of published closing prices.',calendar_unavailable:'The exchange calendar needs review before results can be calculated.',unsupported_session:'A changed or special exchange session needs review.'}[code]||'Results are waiting for a review of price and portfolio evidence.';}
  function status(d){
    const t=d.timing,session=d.session_date||d.metrics?.session_date;
    const titles={draft:'Contest draft',cancelled:'Contest cancelled',not_started:'Contest has not started',awaiting_close:'Waiting for the session close',awaiting_data:'Waiting for complete valuation data',processing:'Valuation is being prepared',current:'Current published snapshot',final:'Final simulated results',unavailable:'Valuation schedule unavailable'};
    const messages={draft:'Publish the contest to open participation.',cancelled:'No further valuations will be calculated for this cancelled contest.',not_started:'Rankings and portfolio metrics appear after the first published contest close. A confirmed submission is saved while you wait.',awaiting_close:'The contest is running. Results will appear after its next closing prices are published and processed.',awaiting_data:'The valuation is delayed while complete price and portfolio evidence is checked.',processing:'The scheduled publication time has passed. Results will appear when complete closing prices have been processed.',current:'These results use the latest complete published closing prices.',final:'The final simulated standings have been recorded.',unavailable:'The exchange schedule needs review before a valuation time can be confirmed.'};
    const title=session&&!d.is_current&&!d.is_final&&t?.state==='current'?'Earlier published snapshot':titles[t?.state]||'Awaiting valuation';
    return `<section class="callout" aria-label="Results status"><strong>${title}</strong><p>${messages[t?.state]||''}</p>${t?.next_results_available_at&&!['cancelled','final','draft','awaiting_data','processing'].includes(t.state)?`<p>Next results expected after <strong>${esc(stamp(t.next_results_available_at))}</strong>.</p>`:''}${d.error_code?`<p>${esc(explanation(d.error_code))}</p>`:''}${d.expected_session_date?`<p>Latest due session: ${esc(d.expected_session_date)}.</p>`:''}${session?`<p>Displayed snapshot ${esc(session)}${d.valued_at?' · '+esc(stamp(d.valued_at)):''}. ${!d.is_current?'These results are from an earlier snapshot.':''}</p>`:''}<p class="small">Simulated results · updated after each published daily close.</p>${button('refresh','Refresh results')}</section><details class="page-details"><summary>Contest schedule</summary>${contestTimeline(t,{esc,stamp})}</details>`;
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
  function homeInsights(){
    const h=data.home,p=h.performance;
    const reports=(h.jobs?.items||[]).filter(j=>j.status==='succeeded'&&j.report);
    const report=reports.find(j=>j.evidence.run_id===p?.metrics?.run_id)||reports[0];
    const active=h.jobs?.items?.some(j=>['queued','running','retry'].includes(j.status));
    const destination=h.id?'insights/'+h.id:'insights';
    return `<section class="panel home-ai-insights" aria-label="AI guidance"><span class="eyebrow">Review and learn</span><h2>AI insights for you</h2>${h.coachError?`<p role="alert">${esc(h.coachError)}</p>${button('refresh','Retry AI insights')}`:report?`<p class="small">${esc(report.session_date)} · ${report.evidence.is_final?'Final':'Interim'} report${report.evidence.run_id!==p?.metrics?.run_id?' · Earlier snapshot':''}</p>${report.evidence.run_id!==p?.metrics?.run_id?'<p class="callout">This report covers an earlier valuation. Generate an updated report in AI Insights to review the latest results.</p>':''}<h3>Snapshot highlights</h3><ul class="home-insight-list">${report.report.focus.slice(0,2).map(f=>`<li>${esc(f.text)}</li>`).join('')}</ul>${report.report.review_points[0]?`<details class="page-details"><summary>One thing to review</summary><p>${esc(report.report.review_points[0].text)}</p></details>`:''}${report.report.learning_actions[0]?`<div class="home-learning-step"><strong>Your next learning step</strong><p>${esc(report.report.learning_actions[0].title)}</p>${link('Open suggested lesson','academy/'+report.report.learning_actions[0].lesson_id,'secondary')}</div>`:''}`:`<p>${active?'Your coach report is being prepared. Open AI Insights to follow its progress.':!h.id?'Join a contest and confirm a portfolio to start receiving guidance based on your results.':!p?.metrics?'Your personal insights become available after your first published portfolio valuation.':h.settings?.enabled===false?'Your performance summary and learning checks are available in AI Insights. AI-written reports are currently turned off.':'Get a coach report to identify what worked, what to review and a useful next lesson.'}</p>`}${h.generateError?`<p role="alert">${esc(h.generateError)}</p>`:''}<div class="home-ai-actions">${p?.metrics&&h.settings?.enabled&&getAccount()?.email_verified&&!active&&!reports.some(j=>j.evidence.run_id===p.metrics.run_id)?button('home-generate','Generate AI insights'):''}${link(report?'Read full AI report':active?'View report progress':'Open AI Insights',destination,'secondary')}</div><p class="small">Educational guidance from saved simulation results${p?.market_data_kind==='yahoo'?', using Yahoo daily market prices':', using synthetic prices'}.</p></section>`;
  }
  function homePortfolio(){
    const h=data.home,p=h.performance,m=p?.metrics;
    return `<section class="home-portfolio" aria-label="Your portfolio analysis"><div class="section-heading"><h2>Your portfolio</h2>${data.items.length?`<div class="home-contest-picker"><label for="home-portfolio-contest">Contest</label><select id="home-portfolio-contest" ${loading?'disabled':''}>${data.items.map(c=>`<option value="${esc(c.contest_id)}" ${c.contest_id===h.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></div>`:''}</div><p class="small">Value history and AI guidance follow the selected contest. ${data.joined_count>data.items.length?'Your recent memberships are listed here; open Performance to browse all contests.':''}</p><div class="home-analysis-grid"><div>${m?`<section class="panel home-portfolio-summary"><div><span class="small">Latest portfolio value</span><strong>${amount(m.total_value)}</strong></div><div><span class="small">Net return</span><strong>${percent(m.return_pct)}</strong></div><p class="small">Snapshot ${esc(m.session_date)} · ${p.is_final?'Final':p.is_current?'Current':'Earlier result · awaiting a newer valuation'}</p></section>`:''}${h.chartError?`<section class="panel" role="alert"><h2>Portfolio value over time</h2><p>${esc(h.chartError)}</p>${button('refresh','Retry portfolio chart')}</section>`:portfolioValueChart(p?.series||[])}${p?.next_cursor?button('home-more','Load earlier portfolio values',p.next_cursor):''}${h.id?link('Explore full performance','performance/'+h.id,'secondary'):link('Find a contest','contests','secondary')}</div>${homeInsights()}</div></section>`;
  }
  function marketSummary(){
    if(data?.marketStatus?.mode!=='yahoo')return `<div class="market-context-grid">${newsPlaceholder('carousel')}</div>`;
    const q=data.benchmark?.items?.[0],point=value=>value==null?'Awaiting data':esc(Number(value).toLocaleString('en-IN',{maximumFractionDigits:2}));
    const change=q?.day_change_pct==null?null:Number(q.day_change_pct),direction=change===null?'':change>0?'is-up':change<0?'is-down':'';
    const movement=change===null?'Awaiting movement data':`${change>0?'↗ +':change<0?'↘ ':'→ '}${percent(change)} from open`;
    return `<div class="market-context-grid"><section class="panel market-overview" aria-label="Nifty 50 market overview"><header class="market-overview-header"><div><span class="eyebrow">MARKET OVERVIEW</span><h2>Nifty 50</h2></div><span class="market-close-badge">End of day</span></header><div class="market-overview-value"><strong class="market-index-level">${point(q?.close)}<span class="market-index-unit">points</span></strong><span class="market-day-change ${direction}">${movement}</span></div><p class="market-overview-source">Yahoo Finance · ${q?.session_date?esc(q.session_date):'Awaiting a complete daily price import'}${q&&q.freshness!=='current_eod'?' · Earlier session':''}</p><dl class="market-session-stats"><div><dt>Opening level</dt><dd>${point(q?.open)}</dd></div><div><dt>Closing level</dt><dd>${point(q?.close)}</dd></div></dl><p class="market-overview-note">Open-to-close movement for the displayed session. Updates after market close; your portfolio uses each holding’s own closing price.</p></section>${newsPlaceholder('carousel')}</div>`;
  }
  function dashboard(){
    const wait=pending();
    if(wait)return shell('dashboard',wait);
    return shell('dashboard',`${pagehead('Your simulation workspace','Hi, '+esc(getAccount()?.name||''),'Follow your contests, review results, and choose your next step.',`<div class="flex">${link('Contest history','contest-history','secondary')}${button('refresh','Refresh results')}</div>`)}${marketSummary()}${homePortfolio()}${summaryCards([['Contests joined',data.joined_count],['Active contests',data.active_count],['Completed contests',data.completed_count],['Contest wins',data.wins]])}${comparisonBars("Your contest returns",data.items.map(c=>({label:c.name,value:c.return_pct})),"Each contest uses its own latest close. These are separate contest returns, not a combined portfolio return.")}<div class="section-heading"><h2>Your contests</h2>${link('My Contests','my-contests','ghost')}</div>${homeContestCards(data.items,{esc,link,icon,amount,percent})}`);
  }
  function contestTable(items){return `<div class="panel tablewrap"><table><thead><tr><th>Contest</th><th>Status</th><th>Snapshot</th><th>Value</th><th>Return</th><th>Rank</th><th></th></tr></thead><tbody>${items.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.status==='settling'?'finalizing results':c.status)}${c.is_final?' · final':''}</td><td>${esc(c.session_date||'Not valued')}${c.session_date&&!c.is_current?' · older snapshot':''}</td><td>${amount(c.total_value)}</td><td>${percent(c.return_pct)}</td><td>${c.rank??'—'}</td><td>${link('Performance','performance/'+c.contest_id,'ghost')}${link('Leaderboard','leaderboard/'+c.contest_id,'ghost')}</td></tr>`).join('')||'<tr><td colspan="7">No recorded contest activity.</td></tr>'}</tbody></table></div>`;}
  function leaderboard(){
    const wait=pending();if(wait)return shell('leaderboard',wait);
    if(!contestId())return shell('leaderboard',`${pagehead('Compete','Contest leaderboards','Rankings are calculated within each contest at a common market close. Choose a contest to view its published rankings.')}${contestCards(data.items,'leaderboard')}${data.next_cursor?button('more','Load more contests',data.next_cursor):''}`);
    return shell('leaderboard',`${pagehead('Contest leaderboard',esc(data.contest_name),'See how portfolios compare at the latest published daily close.',link('Choose another contest','leaderboard','ghost'))}${status(data)}<p>Members: ${data.member_count} · Confirmed portfolios: ${data.submitted_count} · Ranked portfolios: ${data.participant_count}. Rankings appear after valuation; saved drafts are not counted as submissions.</p>${data.has_joined?submissionInfo(data):'<p class="small">Detailed portfolio metrics are private to each participating account. Administrators can follow public standings here.</p>'}${comparisonBars("Standings at a glance",data.items.slice(0,10).map(r=>({label:"#"+r.rank+" "+r.label+(r.is_you?" · you":""),value:r.return_pct})),"Net return for up to 10 loaded standings. Ties use lower drawdown, earlier submission, then entry ID.")}<section class="panel tablewrap"><table><thead><tr><th>Rank</th><th>Learner</th><th>Virtual value</th><th>Return</th><th>Benchmark</th><th>Excess (pp)</th><th>Max drawdown</th></tr></thead><tbody>${data.items.map(r=>`<tr><td>#${r.rank}</td><td>${esc(r.label)}${r.is_you?' · you':''}</td><td>${amount(r.total_value)}</td><td>${percent(r.return_pct)}</td><td>${percent(r.benchmark_return_pct)}</td><td>${percent(r.excess_return_pct).replace(/%$/,'')}</td><td>${percent(r.max_drawdown_pct)}</td></tr>`).join('')||'<tr><td colspan="7">No published ranking yet.</td></tr>'}</tbody></table>${data.next_cursor?button('more','Load more ranks',data.next_cursor):''}</section>${getAccount()&&data.has_joined?link('My performance','performance/'+contestId(),'secondary'):link('View contest','contests/'+contestId(),'secondary')}`);
  }
  function performance(){
    const wait=pending();if(wait)return shell('my-contests',wait);
    if(!contestId())return shell('my-contests',`${pagehead('Your results','Contest performance','Choose one of your contest memberships.')}${contestCards(data.items,'performance')}${data.next_cursor?button('more','Load more contests',data.next_cursor):''}`);
    const m=data.metrics;
    return shell('my-contests',`${pagehead('Your contest performance',esc(data.contest_name),'Your portfolio, its daily progress, and the benchmark to compare against.',link('Leaderboard','leaderboard/'+contestId(),'secondary'))}${status(data)}${m?`${summaryCards([['Portfolio value',amount(m.total_value)],['Net return',movement(m.return_pct)],['Benchmark return',movement(m.benchmark_return_pct)],['Rank','#'+m.rank]])}${returnChart(data.series)}<div class="visual-grid">${allocationChart(m.positions,m.cash,m.total_value)}${comparisonBars('Holding contributions',m.positions.map(p=>({label:p.symbol,value:p.contribution_pct})), 'Contribution to portfolio return in percentage points. The portfolio fee is excluded.', ' pp')}</div><details class="page-details panel"><summary>Portfolio details and holding values</summary><div class="grid2" style="margin-top:22px"><section class="panel"><h2>Portfolio metrics</h2><p>Starting virtual capital ${amount(m.capital)}.</p><p>Net P&amp;L ${movement(m.pnl,amount)} · residual cash ${amount(m.cash)} · one simulated fee ${amount(m.fee)}</p><p>${m.holding_count} holdings across ${m.sector_count} sectors. Largest position ${percent(m.largest_position_pct)} of portfolio value.</p><p>Equity concentration HHI ${esc(m.concentration_hhi)} (lower means more spread across equities; cash is excluded).</p><p>Maximum daily-close drawdown ${movement(m.max_drawdown_pct,percent,true)}. Excess return ${movement(m.excess_return_pct,x=>percent(x).replace(/%$/,''))} percentage points.</p><p class="small">Drawdown includes the initial simulated fee; intraday movements are not measured.</p></section><section class="panel"><h2>Holding contributions</h2><div class="tablewrap"><table><thead><tr><th>Holding</th><th>Shares</th><th>Value</th><th>Price P&amp;L</th></tr></thead><tbody>${m.positions.map(p=>`<tr><td>${esc(p.symbol)}</td><td>${p.quantity}</td><td>${amount(p.value)}</td><td>${movement(p.pnl,amount)}</td></tr>`).join('')}</tbody></table></div><p class="small">Holding contributions exclude the single portfolio-level simulated fee.</p></section></div></details>`:`${submissionInfo(data)}${returnChart([])}<details class="page-details"><summary>Understand your future results</summary>${metricGuide()}</details>`}<details class="panel page-details" style="margin-top:22px"><summary>Daily snapshots</summary><h2>Daily snapshots</h2><div class="tablewrap"><table><thead><tr><th>Close</th><th>Virtual value</th><th>Return</th><th>Benchmark</th><th>Drawdown</th></tr></thead><tbody>${data.series.map(s=>`<tr><td>${esc(s.session_date)}</td><td>${amount(s.total_value)}</td><td>${movement(s.return_pct)}</td><td>${movement(s.benchmark_return_pct)}</td><td>${movement(s.max_drawdown_pct,percent,true)}</td></tr>`).join('')||'<tr><td colspan="5">No successful daily snapshots.</td></tr>'}</tbody></table></div>${data.next_cursor?button('more','Load earlier snapshots',data.next_cursor):''}</details>${link('Submission history','portfolio/'+contestId(),'ghost')}${link('Open performance coach','insights/'+contestId(),'secondary')}`);
  }
  function page(){
    const k=kind();
    if(k!=='leaderboard'&&!getAccount())return shell('my-contests',`${pagehead('Your results','Sign in to view your results','Contest performance belongs to your account.')}${link('Sign in','login')}`);
    if(k==='dashboard')return dashboard();
    if(k==='leaderboard')return leaderboard();
    if(k==='contest-history'){const wait=pending();return shell('my-contests',`${pagehead('Your history','Completed contests','Finalized simulations and cancelled contests.')}${wait||contestTable(data.items)}${!wait&&data.next_cursor?button('more','Load more contests',data.next_cursor):''}${button('refresh','Refresh results')}`);}
    return performance();
  }
  function change(el){if(el.id==='home-portfolio-contest'&&data?.items.some(c=>c.contest_id===el.value)){homeId=el.value;load();render();}}
  async function click(buttonEl){if(buttonEl.disabled)return;
    if(buttonEl.dataset.performanceAction==='home-generate'){
      const h=data?.home;if(loading||!h?.performance?.metrics)return;
      const expected=routeKey(),token=generation,requestId=JSON.stringify([getAccount()?.id,h.id,h.performance.metrics.run_id,h.settings?.provider,h.settings?.model]);
      if(!homeRequests.has(requestId))homeRequests.set(requestId,crypto.randomUUID());
      loading=true;h.generateError='';render();
      try{await coachApi.create(h.id,homeRequests.get(requestId));if(token!==generation||expected!==routeKey())return;homeRequests.delete(requestId);await load();}
      catch(e){if(token===generation&&expected===routeKey()){h.generateError=e.message;loading=false;render();}}
      return;
    }
    if(buttonEl.dataset.performanceAction==='home-more'){load(buttonEl.dataset.cursor);return;}if(buttonEl.dataset.performanceAction==='more')load(buttonEl.dataset.cursor);else if(kind()==='dashboard'){load();render();}else{reset();render();}}
  return {page,ensure,reset,click,change,deactivate:()=>{stop();if(loading)reset();}};
}
