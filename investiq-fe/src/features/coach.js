import { dailyOverview } from './coach-overview.js';
import { coachApi as api, contestApi } from '../api/services.js';

export function createCoachController({shell,pagehead,esc,link,render,current,getAccount}) {
  let key='',epoch=0,loaded=false,loading=false,busy=false,error='',notice='',contests=[],next=null,evidence=null,config=null,jobs=[],jobNext=null,reflections=[],reflectionNext=null,pollTimer=null,draft='';
  let section='overview',selectedReport='',contest=null,userOverview=null,overviewError='';
  const requests=new Map();
  const destination=()=>current().split('/')[1]||'';
  const signature=()=>JSON.stringify([current(),getAccount()?.id]);
  const stamp=value=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  function stop(){clearTimeout(pollTimer);pollTimer=null;}
  function reset(){stop();epoch++;key='';loaded=false;loading=false;busy=false;error='';notice='';contests=[];next=null;evidence=null;config=null;jobs=[];jobNext=null;reflections=[];reflectionNext=null;draft='';requests.clear();section='overview';selectedReport='';contest=null;userOverview=null;overviewError='';}
  function deactivate(){if(key){stop();epoch++;key='';loaded=false;loading=false;busy=false;}}
  function ensure(){if(getAccount()&&key!==signature()){busy=false;draft='';notice='';section='overview';selectedReport='';contest=null;load();}}
  const button=(action,label)=>`<button class="secondary" data-coach-action="${action}" ${busy||loading?'disabled':''}>${label}</button>`;
  function poll(){stop();const pending=jobs.some(j=>['queued','running','retry'].includes(j.status))||userOverview?.pending_reports>0;if(pending||userOverview?.valued_contests){const expected=signature(),token=epoch;pollTimer=setTimeout(()=>{if(expected===signature()&&token===epoch){if(destination())refreshJobs();else refreshOverview();}},pending?2500:60000);}}
  async function refreshOverview(){
    const expected=signature(),token=epoch;
    try{const response=await api.overview();if(expected!==signature()||token!==epoch)return;const changed=overviewError||JSON.stringify(userOverview)!==JSON.stringify(response);userOverview=response;overviewError='';if(changed)render();poll();}
    catch(e){if(expected===signature()&&token===epoch){overviewError='Your performance summary could not be refreshed. '+e.message;render();poll();}}
  }
  async function refreshJobs(){
    const expected=signature(),token=epoch;
    try{const [response,summary]=await Promise.all([api.jobs({contest_id:destination()}),api.overview().then(value=>({value,error:''})).catch(e=>({value:null,error:e.message}))]);if(expected!==signature()||token!==epoch)return;const changed=JSON.stringify(jobs)!==JSON.stringify(response.items)||overviewError!==summary.error||(summary.value&&JSON.stringify(userOverview)!==JSON.stringify(summary.value));jobs=response.items;jobNext=response.next_cursor;overviewError=summary.error;if(summary.value)userOverview=summary.value;if(changed)render();poll();}
    catch(e){if(expected===signature()&&token===epoch){notice='Report status could not be refreshed. '+e.message;render();poll();}}
  }
  async function load(more=false){
    stop();const expected=signature(),token=++epoch,id=destination();key=expected;loading=true;error='';overviewError='';if(!more){loaded=false;userOverview=null;jobs=[];}render();
    try{
      const summaryRequest=api.overview().then(value=>({value,error:''})).catch(e=>({value:null,error:e.message}));
      if(!id){const [response,summary]=await Promise.all([contestApi.mine(more&&next?{cursor:next}:{}),summaryRequest]);if(token!==epoch||expected!==signature())return;contests=more?[...contests,...response.items]:response.items;next=response.next_cursor;userOverview=summary.value;overviewError=summary.error;}
      else{
        const [settings,history,journal,details,summary]=await Promise.all([api.settings(),api.jobs({contest_id:id}),api.reflections(id),contestApi.get(id),summaryRequest]);
        let facts=null,pending='';
        try{facts=await api.evidence(id);}catch(e){if(e.status===409||e.status===403)pending=e.message;else throw e;}
        if(token!==epoch||expected!==signature())return;
        contest=details;config=settings;evidence=facts;notice=pending;jobs=history.items;jobNext=history.next_cursor;reflections=journal.items;reflectionNext=journal.next_cursor;userOverview=summary.value;overviewError=summary.error;
      }
      loaded=true;
    }catch(e){if(token===epoch&&expected===signature()){error=e.message;loaded=true;}}
    finally{if(token===epoch&&expected===signature()){loading=false;render();poll();}}
  }
  const factList=(facts,references=false)=>`<ul class="coach-facts">${facts.map(f=>`<li><p>${esc(f.text)}</p>${references?`<details><summary>Evidence reference</summary><p class="small">${esc(f.source)}</p></details>`:''}</li>`).join('')}</ul>`;
  const reportLabels={queued:'Report queued',running:'Reviewing your results',retry:'Waiting to retry',failed:'Generation could not be completed',succeeded:'Report ready'};
  const sections=[['overview','Overview'],['learning','Learning'],['journal','Journal'],['evidence','Evidence'],['history','Past reports']];
  function defaultJob(){return jobs.find(j=>j.report&&j.evidence.record_id===evidence?.record_id&&j.provider===config?.provider&&j.model===config?.model)||jobs.find(j=>j.report);}
  function selectedJob(){return jobs.find(j=>j.id===selectedReport&&j.report)||defaultJob();}
  function revealSection(){document.querySelector('.coach-nav')?.scrollIntoView({block:'start',behavior:'instant'});document.getElementById('coach-section')?.focus({preventScroll:true});}
  function sectionButton(id,label){return `<button type="button" class="${section===id?'primary':'secondary'}" data-coach-action="section" data-section="${id}" ${section===id?'aria-current="page"':''}>${label}</button>`;}
  function reportContext(job){
    if(!job)return '';
    const older=job.evidence.record_id!==evidence?.record_id;
    return `<div class="coach-report-context"><span class="pill neutral">${esc(job.session_date)} · ${job.evidence.is_final?'Final':'Interim'} snapshot</span>${older?'<span class="coach-older">Earlier snapshot — this report does not cover the latest valuation.</span>':''}${selectedReport&&job.id!==defaultJob()?.id?'<button class="ghost" data-coach-action="latest-report">Show latest report</button>':''}</div>`;
  }
  function waiting(){return '<section class="panel coach-empty"><h2>No report yet</h2><p>Once a valuation is available, generate a report to see your key takeaways and learning suggestions.</p>'+sectionButton('journal','Open your journal')+'</section>';}
  function overview(job){
    if(!job)return waiting();
    const r=job.report;
    return `<section class="panel coach-overview" data-coach-job="${esc(job.id)}"><div class="row"><h2>Report ready</h2>${sectionButton('evidence','View all evidence')}</div><h3>Your key takeaways</h3><p class="small">Up to three priorities selected by the coach for this snapshot.</p><ol class="coach-takeaways">${r.focus.slice(0,3).map((f,i)=>`<li><span class="coach-number">${i+1}</span><p>${esc(f.text)}</p></li>`).join('')}</ol>${r.focus.length>3?`<details class="page-details"><summary>${r.focus.length-3} more coach priorities</summary>${factList(r.focus.slice(3))}</details>`:''}<div class="coach-columns"><section><h3>What worked</h3>${r.what_worked.length?factList(r.what_worked):'<p>No positive holding contribution was identified in this snapshot.</p>'}</section><section><h3>What to review</h3>${factList(r.review_points)}</section></div><div class="coach-next"><div><strong>Your next learning step</strong><p>${esc(r.learning_actions[0]?.title||'Explore the suggested lessons for this report.')}</p></div>${sectionButton('learning','Explore learning')}</div></section>`;
  }
  function learning(job){
    if(!job)return waiting();
    return `<section class="panel"><h2>Suggested learning actions</h2><p>Choose a lesson to explore the ideas behind this report.</p><div class="coach-lessons">${job.report.learning_actions.map((l,i)=>`<article><span class="small">Lesson ${i+1}</span><h3>${esc(l.title)}</h3>${link('Open current lesson','academy/'+l.lesson_id,'primary')}<details class="page-details"><summary>Cited lesson excerpt (version ${l.version})</summary>${l.paragraphs.map(p=>`<p class="coach-text">${esc(p)}</p>`).join('')}<p class="small">The excerpt is from the version cited when this report was created. The current lesson may have changed.</p></details></article>`).join('')}</div><div class="coach-next"><div><strong>Pause and reflect</strong><p>${esc(job.report.reflection_question)}</p></div>${sectionButton('journal','Write a reflection')}</div></section>`;
  }
  function journal(job){return `<section class="panel"><h2>Your decision journal</h2><p>Private to you. Your reflections are saved with this contest and are not sent to the model.</p>${job?`<blockquote class="coach-prompt">${esc(job.report.reflection_question)}</blockquote>`:''}${getAccount()?.email_verified?`<form data-coach-form="reflection"><label class="field">My reasoning<textarea name="body" aria-label="My reasoning" placeholder="What did you learn, and what would you review next time?" maxlength="2000" required>${esc(draft)}</textarea></label><button class="primary" ${busy||loading?'disabled':''}>Save reflection</button></form>`:'<p>Verify your email to save a reflection.</p>'}<h3>Saved reflections</h3>${reflections.map(r=>`<article class="coach-reflection"><p class="coach-text">${esc(r.body)}</p><p class="small">${esc(stamp(r.created_at))}</p></article>`).join('')||'<p>No saved reflections yet.</p>'}${reflectionNext?button('reflections-more','Load earlier reflections'):''}</section>`;}
  function evidenceView(job){
    const source=job?.evidence||evidence;
    if(!source)return '<section class="panel"><h2>Evidence is not ready</h2><p>Confirm a portfolio and wait for the first published valuation.</p></section>';
    return `<section class="panel"><h2>Snapshot evidence</h2><p>Recorded observations behind ${job?'the selected report':'your latest valuation'}. These facts come from saved simulation results.</p>${factList(source.facts,true)}<h3>Limitations</h3><ul>${(job?.report?.limitations||source.limitations).map(l=>`<li>${esc(l)}</li>`).join('')}</ul>${job?`<details class="page-details"><summary>Technical report details</summary><dl class="coach-metadata"><dt>Provider / model</dt><dd>${esc(job.provider)} / ${esc(job.model)}</dd><dt>Report requested</dt><dd>${esc(stamp(job.created_at))}</dd><dt>Prompt / generation</dt><dd>${esc(job.prompt_version)} / ${job.generation}</dd><dt>Attempts</dt><dd>${job.attempts} / ${config?.max_attempts||3}</dd><dt>Source run</dt><dd>${esc(job.evidence.run_id)}</dd><dt>Submission</dt><dd>${esc(job.evidence.submission_id)}</dd><dt>Metric / report format</dt><dd>${esc(job.evidence.metric_version)} / ${esc(job.report.format_version)}</dd><dt>Evidence fingerprint</dt><dd>${esc(job.evidence_hash)}</dd></dl></details>`:''}</section>`;
  }
  function history(){return `<section class="panel"><h2>Past reports</h2><p>Open a saved report to review the snapshot it was based on.</p><div class="coach-history">${jobs.map(j=>`<article><div><h3>${esc(j.session_date)} snapshot</h3><p>${esc(reportLabels[j.status]||j.status)} · ${esc(stamp(j.created_at))}</p>${j.error_code?`<details><summary>Processing details</summary><p class="small">${esc(j.error_code==='daily_ai_limit'?'Today’s demo AI allowance is used. Please try again tomorrow.':j.error_code)}${j.status==='retry'?' · This report will retry on the next processing run.':''}</p></details>`:''}</div>${j.report?`<button class="secondary" data-coach-action="open-report" data-id="${esc(j.id)}">Open report</button>`:''}</article>`).join('')||'<p>No reports requested yet.</p>'}</div>${jobNext?button('jobs-more','Load earlier reports'):''}</section>`;}
  function contestStatus(status){
    const states={draft:['Draft','neutral'],scheduled:['Upcoming','upcoming'],open:['Open for entry','open'],locked:['Entries locked','neutral'],running:['Live','live'],settling:['Finalising results','upcoming'],completed:['Completed','complete'],cancelled:['Cancelled','cancelled']};
    const [label,tone]=states[status]||[status,'neutral'];
    const mark=status==='completed'?'<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10" cy="10" r="7.5"/><path d="m6.5 10 2.3 2.3 4.7-4.6"/></svg>':status==='running'?'<span class="coach-status-dot" aria-hidden="true"></span>':'<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="10" cy="10" r="7.5"/><path d="M10 6v4l2.5 1.5"/></svg>';
    return `<span class="coach-contest-status status-${tone}" aria-label="Contest status: ${esc(label)}">${mark}${esc(label)}</span>`;
  }
  function page(){
    let body=pagehead('Review and learn','AI Insights','Understand your results. Choose one learning step.');
    if(!getAccount())return shell('insights',body+`<section class="panel"><p>Sign in to view your private report evidence and coach history.</p>${link('Sign in','login')}</section>`);
    body+=`<div class="flex" style="margin-bottom:20px">${destination()?link('Choose contest','insights','secondary'):''}${button('refresh','Refresh coach')}</div>`;
    if(key!==signature()||!loaded)return shell('insights',body+'<section class="panel" role="status">Loading coach evidence…</section>');
    if(error)return shell('insights',body+`<section class="panel" role="alert">${esc(error)} ${button('refresh','Retry coach')}</section>`);
    body+=dailyOverview(userOverview,{esc,link,button,error:overviewError});
    if(notice)body+=`<p class="callout" role="status">${esc(notice)}</p>`;
    if(!destination())return shell('insights',body+`${contests.length?'<section class="coach-intro"><h2>Per-contest reports</h2><p>Explore each contest’s results, AI review and private journal.</p></section>':''}<div class="contest-grid">${contests.map(c=>`<section class="panel coach-contest-card">${contestStatus(c.status)}<h2>${esc(c.name)}</h2>${link('Open performance coach','insights/'+c.id,'secondary')}</section>`).join('')||''}</div>${next?button('more','Load more contests'):''}`);
    const active=jobs.find(j=>['queued','running','retry'].includes(j.status)),existing=evidence&&jobs.find(j=>j.evidence.record_id===evidence.record_id&&j.provider===config?.provider&&j.model===config?.model),job=selectedJob();
    body+=`<section class="panel coach-context" aria-label="Contest and report status"><div><h2>${esc(contest?.name||'Your contest')}</h2><p>${evidence?`Latest valuation: ${esc(evidence.session_date)} · ${evidence.is_final?'Final':'Interim'}${evidence.is_current?'':' · Waiting for newer results'}`:'Confirm your portfolio and wait for the first published valuation.'}</p>${active?`<div role="status"><h3>${esc(reportLabels[active.status])}</h3></div><p class="small">Status updates automatically. You can use the other sections while you wait.</p>`:!config?.enabled?'<p class="small">AI generation is disabled or not configured. Evidence and your journal remain available.</p>':!getAccount()?.email_verified?'<p>Verify your email before requesting a report.</p>':!evidence?'<p class="small">Your journal is available while you wait for results.</p>':existing?.status==='succeeded'?'<p class="small">Your report for this snapshot is ready.</p>':existing?.status==='failed'?'<p>Your report could not be generated. Retry or check Past reports for details.</p>':''}</div><div class="coach-context-actions">${evidence&&config?.enabled&&getAccount()?.email_verified&&!active&&(!existing||existing.status==='failed')?button('generate',existing?.status==='failed'?'Retry coach report':'Generate coach report'):''}${link('View performance','performance/'+destination(),'ghost')}</div></section><nav class="coach-nav" aria-label="AI Insights sections">${sections.map(([id,label])=>sectionButton(id,label)).join('')}</nav>${reportContext(job)}<div class="coach-section" id="coach-section" tabindex="-1">${section==='overview'?overview(job):section==='learning'?learning(job):section==='journal'?journal(job):section==='evidence'?evidenceView(job):history()}</div><p class="small coach-disclaimer">Educational simulation using saved closing valuations. Insights explain saved results and learning priorities; they are not forecasts or trading recommendations.</p>`;
    return shell('insights',body);
  }
  async function click(b){
    if(b.disabled||loading)return;const action=b.dataset.coachAction,id=destination();
    if(action==='section'){if(!sections.some(([id])=>id===b.dataset.section))return;section=b.dataset.section;render();revealSection();return;}
    if(action==='latest-report'){selectedReport='';section='overview';render();revealSection();return;}
    if(action==='open-report'){selectedReport=b.dataset.id;section='overview';render();revealSection();return;}
    if(busy)return;
    if(action==='refresh'){load();return;}if(action==='more'){load(true);return;}
    const expected=signature(),token=epoch;busy=true;notice='';render();
    try{
      if(action==='generate'){
        const k=JSON.stringify([getAccount()?.id,id,evidence?.record_id,config?.provider,config?.model]);if(!requests.has(k))requests.set(k,crypto.randomUUID());
        await api.create(id,requests.get(k));if(token!==epoch||expected!==signature())return;requests.delete(k);await refreshJobs();
      }else if(action==='jobs-more'){
        const result=await api.jobs({contest_id:id,cursor:jobNext});if(token!==epoch||expected!==signature())return;jobs=[...jobs,...result.items];jobNext=result.next_cursor;
      }else if(action==='reflections-more'){
        const result=await api.reflections(id,{cursor:reflectionNext});if(token!==epoch||expected!==signature())return;reflections=[...reflections,...result.items];reflectionNext=result.next_cursor;
      }
    }catch(e){if(token===epoch&&expected===signature())notice=e.message;}
    finally{if(token===epoch&&expected===signature()){busy=false;render();poll();}}
  }
  async function submit(form){
    if(busy||loading)return;const body=String(new FormData(form).get('body')).trim();if(!body)return;
    const id=destination(),expected=signature(),token=epoch,k=JSON.stringify([getAccount()?.id,id,body]);if(!requests.has(k))requests.set(k,crypto.randomUUID());busy=true;notice='';render();
    try{await api.reflect({contest_id:id,body},requests.get(k));if(expected!==signature()||token!==epoch)return;requests.delete(k);draft='';const response=await api.reflections(id);if(expected!==signature()||token!==epoch)return;reflections=response.items;reflectionNext=response.next_cursor;notice='Private reflection saved.';}
    catch(e){if(expected===signature()&&token===epoch)notice=e.message;}
    finally{if(expected===signature()&&token===epoch){busy=false;render();}}
  }
  function input(el){if(el.name==='body')draft=el.value;}
  return {page,ensure,reset,deactivate,click,submit,input};
}
