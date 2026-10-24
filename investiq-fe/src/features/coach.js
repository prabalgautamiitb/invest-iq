import { coachApi as api, contestApi } from '../api/services.js';

export function createCoachController({shell,pagehead,esc,link,render,current,getAccount}) {
  let key='',epoch=0,loaded=false,loading=false,busy=false,error='',notice='',contests=[],next=null,evidence=null,config=null,jobs=[],jobNext=null,reflections=[],reflectionNext=null,pollTimer=null,draft='';
  const requests=new Map();
  const destination=()=>current().split('/')[1]||'';
  const signature=()=>JSON.stringify([current(),getAccount()?.id]);
  const stamp=value=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  function stop(){clearTimeout(pollTimer);pollTimer=null;}
  function reset(){stop();epoch++;key='';loaded=false;loading=false;busy=false;error='';notice='';contests=[];next=null;evidence=null;config=null;jobs=[];jobNext=null;reflections=[];reflectionNext=null;draft='';requests.clear();}
  function deactivate(){if(key){stop();epoch++;key='';loaded=false;loading=false;busy=false;}}
  function ensure(){if(getAccount()&&key!==signature()){busy=false;draft='';notice='';load();}}
  const button=(action,label)=>`<button class="secondary" data-coach-action="${action}" ${busy||loading?'disabled':''}>${label}</button>`;
  function poll(){stop();if(jobs.some(j=>['queued','running','retry'].includes(j.status))){const expected=signature(),token=epoch;pollTimer=setTimeout(()=>{if(expected===signature()&&token===epoch)refreshJobs();},2500);}}
  async function refreshJobs(){
    const expected=signature(),token=epoch;
    try{const response=await api.jobs({contest_id:destination()});if(expected!==signature()||token!==epoch)return;jobs=response.items;jobNext=response.next_cursor;render();poll();}
    catch(e){if(expected===signature()&&token===epoch){notice='Report status could not be refreshed. '+e.message;render();}}
  }
  async function load(more=false){
    stop();const expected=signature(),token=++epoch,id=destination();key=expected;loading=true;error='';if(!more)loaded=false;render();
    try{
      if(!id){const response=await contestApi.mine(more&&next?{cursor:next}:{});if(token!==epoch||expected!==signature())return;contests=more?[...contests,...response.items]:response.items;next=response.next_cursor;}
      else{
        const [settings,history,journal]=await Promise.all([api.settings(),api.jobs({contest_id:id}),api.reflections(id)]);
        let facts=null,pending='';
        try{facts=await api.evidence(id);}catch(e){if(e.status===409||e.status===403)pending=e.message;else throw e;}
        if(token!==epoch||expected!==signature())return;
        config=settings;evidence=facts;notice=pending;jobs=history.items;jobNext=history.next_cursor;reflections=journal.items;reflectionNext=journal.next_cursor;
      }
      loaded=true;
    }catch(e){if(token===epoch&&expected===signature()){error=e.message;loaded=true;}}
    finally{if(token===epoch&&expected===signature()){loading=false;render();poll();}}
  }
  const factList=facts=>`<ul>${facts.map(f=>`<li style="margin-bottom:14px;overflow-wrap:anywhere">${esc(f.text)}<details><summary class="small">Evidence reference</summary><p class="small">${esc(f.source)}</p></details></li>`).join('')}</ul>`;
  function reportCard(job){
    const report=job.report;
    const labels={queued:'Queued for the coach worker',running:'Generating and checking evidence',retry:'Waiting to retry after a processing failure',failed:'Generation could not be completed',succeeded:'Report ready'};
    return `<section class="panel" data-coach-job="${job.id}"><div class="row"><h2>${esc(labels[job.status]||job.status)}</h2><span class="pill neutral">${esc(job.session_date)} snapshot</span></div><p class="small">${esc(job.provider)} · ${esc(job.model)} · ${esc(job.prompt_version)} · generation ${job.generation} · ${job.attempts}/${config?.max_attempts||3} attempts</p><p class="small">Requested ${esc(stamp(job.created_at))} · ${job.evidence.is_final?'Final contest snapshot':'Interim contest snapshot'}</p>${job.error_code?`<p class="callout">${esc(job.error_code)}${job.status==='retry'?' · The worker will retry automatically.':' · Check the provider configuration before requesting another generation.'}</p>`:''}${report?`<h3>Performance, benchmark and portfolio observations</h3>${factList(report.summary)}<h3>Coach focus</h3>${factList(report.focus)}<h3>What worked in this snapshot</h3>${report.what_worked.length?factList(report.what_worked):'<p>No positive holding contribution was identified in the available snapshot.</p>'}<h3>Review points</h3>${factList(report.review_points)}<h3>Suggested learning actions</h3>${report.learning_actions.map(l=>`<article class="callout"><h4>${esc(l.title)}</h4><p class="small">Published lesson version ${l.version} · ${esc(l.version_id)}</p><details><summary>Cited lesson excerpt (version ${l.version})</summary>${l.paragraphs.map(p=>`<p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(p)}</p>`).join('')}</details>${link('Open current lesson','academy/'+l.lesson_id,'secondary')}</article>`).join('')}<h3>Reflection question</h3><p>${esc(report.reflection_question)}</p><details><summary>Evidence and limitations</summary><p class="small">Source run ${esc(job.evidence.run_id)} · submission ${esc(job.evidence.submission_id)} · ${esc(job.evidence.metric_version)} · ${esc(report.format_version)}</p><p class="small" style="overflow-wrap:anywhere">Evidence fingerprint: ${esc(job.evidence_hash)}</p><ul>${report.limitations.map(s=>`<li>${esc(s)}</li>`).join('')}</ul></details>`:'<p>Reports use saved simulation evidence and published lessons. No provisional AI result is shown while validation is pending.</p>'}</section>`;
  }
  function journal(){return `<section class="panel"><h2>Your decision journal</h2><p>Private reflections are saved with this contest and are not sent to the model.</p>${getAccount()?.email_verified?`<form data-coach-form="reflection"><label class="field">My reasoning<textarea name="body" aria-label="My reasoning" maxlength="2000" required>${esc(draft)}</textarea></label><button class="primary" ${busy||loading?'disabled':''}>Save reflection</button></form>`:'<p>Verify your email to save a reflection.</p>'}${reflections.map(r=>`<article class="post"><p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(r.body)}</p><p class="small">${esc(stamp(r.created_at))}</p></article>`).join('')||'<p>No saved reflections yet.</p>'}${reflectionNext?button('reflections-more','Load earlier reflections'):''}</section>`;}
  function page(){
    let body=pagehead('Review and learn','Performance coach','Evidence-backed reviews of your own simulated contest portfolios.');
    if(!getAccount())return shell('insights',body+`<section class="panel"><p>Sign in to view your private report evidence and coach history.</p>${link('Sign in','login')}</section>`);
    body+=`<div class="flex" style="margin-bottom:20px">${link('Choose contest','insights','secondary')}${button('refresh','Refresh coach')}</div>`;
    if(key!==signature()||!loaded)return shell('insights',body+'<section class="panel" role="status">Loading coach evidence…</section>');
    if(error)return shell('insights',body+`<section class="panel" role="alert">${esc(error)} ${button('refresh','Retry coach')}</section>`);
    if(notice)body+=`<p class="callout" role="status">${esc(notice)}</p>`;
    if(!destination())return shell('insights',body+`<div class="grid2">${contests.map(c=>`<section class="panel"><h2>${esc(c.name)}</h2><p>${esc(c.status)} · Reports require a confirmed submission and a published valuation.</p>${link('Open performance coach','insights/'+c.id,'secondary')}</section>`).join('')||'<section class="panel">Join a contest and submit a portfolio to start building report evidence.</section>'}</div>${next?button('more','Load more contests'):''}`);
    const active=jobs.some(j=>['queued','running','retry'].includes(j.status)),existing=evidence&&jobs.find(j=>j.evidence.record_id===evidence.record_id&&j.provider===config?.provider&&j.model===config?.model);
    body+='<p class="callout">Synthetic-price educational simulation. Every numerical claim comes from a saved valuation. The coach selects learning priorities; this is not a forecast or a recommendation to trade.</p>';
    body+=`<section class="panel"><h2>Current report evidence</h2>${evidence?`<p>${esc(evidence.session_date)} · ${evidence.is_final?'Final':'Interim'} snapshot${evidence.is_current?'':' · Behind the expected valuation date'}</p><details><summary>View deterministic observations</summary>${factList(evidence.facts)}</details>`:'<p>Evidence is not ready. Confirm a portfolio and wait for the first published valuation. You can still save a reflection below.</p>'}${!config?.enabled?'<p>AI generation is disabled or not configured. Deterministic evidence and your journal remain available.</p>':!getAccount()?.email_verified?'<p>Verify your email before requesting a report.</p>':evidence&&!active&&(!existing||existing.status==='failed')?button('generate',existing?.status==='failed'?'Retry coach report':'Generate coach report'):active?'<p role="status">Your report is queued or processing. Status updates automatically.</p>':existing?.status==='succeeded'?'<p>A report already exists for this snapshot and provider. A newer valuation can produce a new report.</p>':''}</section>`;
    body+=jobs.map(reportCard).join('')+(jobNext?button('jobs-more','Load earlier reports'):'')+journal();
    return shell('insights',body);
  }
  async function click(b){
    if(b.disabled||busy||loading)return;const action=b.dataset.coachAction,id=destination();
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
