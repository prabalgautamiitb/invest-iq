import { martinApi as api, contestApi } from '../api/services.js';
import { floatingLauncher } from '../lib/floating-launcher.js';

// A separate root keeps the conversation stable while workspace pages re-render.
export function createMartinController({ getAccount, current }) {
  const root = document.createElement('div');
  root.id = 'martin-root';root.hidden = true;document.body.append(root);
  const floating = floatingLauncher(root);
  const moveHelp = document.createElement('p');moveHelp.id='martin-move-help';moveHelp.className='martin-announcement';moveHelp.textContent='Drag to move Martin. With the avatar focused, use arrow keys to move or Home to reset its position. Press Enter to open chat.';document.body.append(moveHelp);
  const announcements=document.createElement('p');announcements.className='martin-announcement';announcements.setAttribute('role','status');announcements.setAttribute('aria-live','polite');document.body.append(announcements);let announced='';
  const escape = value => String(value??'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const routes = new Set(['dashboard','home','contests','my-contests','portfolio','build','academy','learn','insights','social','community','marketplace','rewards','profile','settings','leaderboard','performance','contest-history']);
  const prompts = {
    learning: ['What is diversification?', 'How does a benchmark work?', 'What is drawdown?'],
    performance: ['How did I perform in my last contest?', 'Where can I improve?', 'How does my return compare with the benchmark?'],
  };
  // Original vector portrait, shared by the launcher and chat header.
  const portrait = `<svg viewBox="0 0 128 128" fill="none" aria-hidden="true" focusable="false">
    <circle cx="64" cy="64" r="64" fill="#172e43"/>
    <circle cx="96" cy="29" r="22" fill="#235362"/>
    <path d="M7 128c2-24 17-37 39-41h36c22 4 37 17 39 41" fill="#65d8b3"/>
    <path d="m47 88 17 15 17-15 9 40H38l9-40Z" fill="#ecf5e9"/>
    <path d="m46 88 18 15-15 15-12-27 9-3Zm36 0-18 15 15 15 12-27-9-3Z" fill="#37a98b"/>
    <path d="M53 73h22v19c-6 9-16 9-22 0V73Z" fill="#c98865"/>
    <ellipse cx="35" cy="58" rx="6" ry="10" fill="#e4a17a"/>
    <ellipse cx="93" cy="58" rx="6" ry="10" fill="#e4a17a"/>
    <path d="M36 41c0-21 56-21 56 0v23c0 20-13 31-28 31S36 84 36 64V41Z" fill="#f0b48b"/>
    <path d="M37 62c0 17 9 28 21 32-14-2-22-15-22-30V43l7-4-6 23Z" fill="#dfa07a"/>
    <path d="M34 53c-9-23 3-38 21-39 19-13 43 2 41 22l-4 19-6-21c-14 5-26 2-31-3-3 9-10 14-16 15l-1 10-4-3Z" fill="#182332"/>
    <path d="M42 28c10-11 27-13 39-6-15-2-26 2-34 10l-5-4Z" fill="#405268"/>
    <path d="m42 51 12-2m20 0 12 2" stroke="#634638" stroke-width="3" stroke-linecap="round"/>
    <rect x="38" y="54" width="23" height="17" rx="7" fill="#c3e9e5" fill-opacity=".22" stroke="#22394b" stroke-width="3"/>
    <rect x="67" y="54" width="23" height="17" rx="7" fill="#c3e9e5" fill-opacity=".22" stroke="#22394b" stroke-width="3"/>
    <path d="M61 59h6m-33-1 4 1m52 0 4-1" stroke="#22394b" stroke-width="3"/>
    <path d="M48 61v3m31-3v3" stroke="#253143" stroke-width="3" stroke-linecap="round"/>
    <path d="m64 64-2 9h4" stroke="#c78361" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M54 79c6 7 14 7 20 0H54Z" fill="#fff5e8"/>
    <path d="M55 80c5 6 13 6 18 0" stroke="#9b5c4b" stroke-width="2" stroke-linecap="round"/>
    <circle cx="33" cy="79" r="3" fill="#8be7d1"/>
    <path d="M104 50v10m-5-5h10" stroke="#a5e4f0" stroke-width="2" stroke-linecap="round"/>
  </svg>`;

  let open=false,mode='learning',owner=null,initialized=false,route='',epoch=0;
  let drafts={learning:'',performance:''},config=null,loaded=false,loading=false,busy=false,error='',notice='';
  let conversations=[],conversationNext=null,thread=null,turns=[],turnNext=null,historyView=false,selectedContest='',contests=[],contestNext=null,pending=null,pollTimer=null;
  const input=()=>root.querySelector('#martin-question');
  const launcher=()=>root.querySelector('[data-martin="toggle"]');
  const active=()=>turns.some(t=>['queued','running'].includes(t.status));
  const canSend=()=>getAccount()?.email_verified&&config?.enabled&&!loading&&!busy&&!active()&&Boolean(drafts[mode].trim());
  const stamp=value=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  function stop(){clearTimeout(pollTimer);pollTimer=null;}
  function context(){const [base,id]=current().split('/');const contest=['contests','portfolio','build','performance','leaderboard','insights'].includes(base)&&/^[0-9a-f-]{36}$/i.test(id||'')?id:'';return {label:contest?'This contest':['academy','learn'].includes(base)?'Academy':'Your workspace',insights:contest?'insights/'+contest:'insights'};}
  function reset(){stop();epoch++;announced='';announcements.textContent='';open=false;mode='learning';owner=null;initialized=false;route='';drafts={learning:'',performance:''};config=null;loaded=false;loading=false;busy=false;error='';notice='';conversations=[];conversationNext=null;thread=null;turns=[];turnNext=null;historyView=false;selectedContest='';contests=[];contestNext=null;pending=null;root.replaceChildren();root.hidden=true;}
  function control(action,label,attributes=''){return `<button type="button" data-martin="${action}" ${attributes} ${busy?'disabled':''}>${label}</button>`;}
  function answer(turn){
    const a=turn.answer;
    if(!a)return turn.status==='failed'?`<p class="martin-failure" role="status">${({daily_ai_limit:'Today’s demo AI allowance is used. Please try again tomorrow.',rate_limit_unavailable:'Martin’s usage check is unavailable. Please try again later.',provider_timeout:'Martin took too long to answer.',invalid_model_output:'Martin could not verify the answer.',owner_unavailable:'This question’s account or contest access is no longer available.',worker_interrupted:'Answering was interrupted. You can retry.'}[turn.error_code]||'Martin is unavailable right now.')}</p>${turn.attempts<3&&turn.id===turns.at(-1)?.id?control('retry','Retry answer',`data-id="${escape(turn.id)}"`):'<p class="martin-small">Ask a new question to try again.</p>'}`:turn.status==='cancelled'?'<p class="martin-small">Question cancelled.</p>':`<p class="martin-thinking" role="status">${turn.status==='queued'?'Your question is queued…':'Martin is reviewing the sources…'}</p>${control('cancel','Cancel question',`data-id="${escape(turn.id)}"`)}`;
    return `<p>${escape(a.introduction)}</p>${a.sources.map((s,i)=>`<details class="martin-source" ${a.intent==='personal_assessment'&&s.kind!=='lesson'?'open':''}><summary>[${i+1}] ${escape(s.title)}</summary><p>${escape(s.text)}</p><a href="#/${escape(s.href)}">Open source ↗</a>${s.kind==='performance'?`<span class="martin-snapshot">${s.is_final?'Final':'Interim'} snapshot${s.is_current===false?' · earlier result':''}</span>`:''}</details>`).join('')}<p class="martin-follow-up">${escape(a.follow_up)}</p><details class="martin-answer-details"><summary>About this answer</summary><p>${escape(a.limitation)}</p><p>Sources were captured for this question. Later valuations do not change saved answers.</p></details>`;
  }
  function welcome(){return `<p class="martin-context"><span aria-hidden="true">◈</span><span data-martin-context>${escape(context().label)}</span></p><h3>A little clarity for your next step.</h3><p class="martin-intro">Ask naturally about a concept or your own results. I’ll use your question and our conversation to choose the right context.</p><div class="martin-modes" role="group" aria-label="Question type"><button type="button" data-martin="mode" data-mode="learning" aria-pressed="${mode==='learning'}">Learn a concept</button><button type="button" data-martin="mode" data-mode="performance" aria-pressed="${mode==='performance'}">My performance</button></div>${mode==='performance'&&getAccount()?`<label class="martin-contest-label">Contest<select id="martin-contest"><option value="">Recent results · up to 3 contests</option>${contests.map(c=>`<option value="${escape(c.id)}" ${selectedContest===c.id?'selected':''}>${escape(c.name)}</option>`).join('')}</select></label>${contestNext?control('contests-more','Load more contests'):''}`:''}<p class="martin-small">Try a question</p><div class="martin-prompts">${prompts[mode].map((p,i)=>`<button type="button" data-martin="prompt" data-index="${i}">${escape(p)}<span aria-hidden="true">↗</span></button>`).join('')}</div><div class="martin-resources"><span>Explore now</span><a href="#/academy">Academy ↗</a><a data-martin-insights href="#/${getAccount()?context().insights:'login'}">${getAccount()?'AI Insights':'Sign in for results'} ↗</a></div>`;}
  function history(){return `<div class="martin-history"><h3>Your saved chats</h3>${loading?'<p role="status">Loading chats…</p>':''}${conversations.map(c=>`<article><button type="button" data-martin="conversation" data-id="${escape(c.id)}"><strong>${escape(c.title)}</strong><span>${c.mode==='learning'?'Learning':'Performance'} · ${escape(stamp(c.updated_at))}</span></button>${control('delete','Delete',`data-id="${escape(c.id)}" aria-label="Delete chat: ${escape(c.title)}"`)}</article>`).join('')||'<p class="martin-intro">No saved chats yet. Ask a question to start one.</p>'}${conversationNext?control('history-more','Load earlier chats'):''}</div>`;}
  function draw({bottom=false}={}){
    const editor=input(),focused=document.activeElement===editor,start=editor?.selectionStart,end=editor?.selectionEnd;
    const oldBody=root.querySelector('.martin-body'),oldScroll=oldBody?.scrollTop||0;
    const availability=!getAccount()?'Sign in to ask Martin and save your conversations.':!getAccount().email_verified?'Verify your email before asking Martin.':!loaded?'Connecting to Martin…':!config?.enabled?'Martin’s AI provider is not configured. Your saved chats remain available.':'Private chat · grounded in Academy lessons and your saved simulation results.';
    root.innerHTML=`<button type="button" class="martin-launcher" data-martin="toggle" aria-label="Ask Martin" aria-expanded="${open}" aria-controls="martin-window" aria-haspopup="dialog">${portrait}<span class="martin-launcher-caption" aria-hidden="true">Ask Martin</span><span class="martin-launcher-spark" aria-hidden="true">✦</span></button><section id="martin-window" class="martin-window" role="dialog" aria-modal="false" aria-labelledby="martin-title" aria-describedby="martin-availability" ${open?'':'hidden'}><header class="martin-header"><span class="martin-avatar" aria-hidden="true">${portrait}</span><div><h2 id="martin-title">Ask Martin</h2><p>Your learning copilot</p></div><button type="button" class="martin-close" data-martin="close" aria-label="Minimize Ask Martin"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/></svg></button></header><div class="martin-toolbar">${control('new','New chat')}${getAccount()?control('history',historyView?'Back to chat':'Chat history'):''}${getAccount()?control('refresh','Refresh'):''}</div><div class="martin-body">${error?`<div class="martin-failure" role="alert">${escape(error)}</div>`:''}${notice?`<p class="martin-notice" role="status">${escape(notice)}</p>`:''}${historyView?history():turns.length?`<div class="martin-thread-scope">${mode==='learning'?'Conversation':'Contest context'}${thread?.contest_id?' · selected contest':' '}</div>${turnNext?control('turns-more','Load earlier messages'):''}<div class="martin-messages" role="log" aria-live="off" aria-label="Conversation messages">${turns.map(t=>`<article class="martin-turn"><div class="martin-user-message"><span>You</span><p>${escape(t.question)}</p></div><div class="martin-assistant-message"><strong>Martin</strong>${answer(t)}</div></article>`).join('')}</div>`:welcome()}</div><form class="martin-composer" data-martin-form><p id="martin-availability" class="martin-availability">${escape(availability)}${!getAccount()?' <a href="#/login">Sign in ↗</a>':''}</p><label for="martin-question">Your question</label><textarea id="martin-question" name="question" rows="2" maxlength="1000" aria-describedby="martin-draft-note" placeholder="What would you like to understand?" ${!getAccount()||!getAccount()?.email_verified||historyView||busy?'disabled':''}>${escape(drafts[mode])}</textarea><div class="martin-composer-actions"><span class="martin-count" aria-hidden="true">${drafts[mode].length}/1000</span><button type="button" data-martin="clear" ${drafts[mode]?'':'disabled'}>Clear draft</button><button type="submit" class="martin-send" aria-label="Send question to Martin" ${canSend()&&!historyView?'':'disabled'}>Ask Martin <span aria-hidden="true">↑</span></button></div><p id="martin-draft-note">Questions and replies are saved privately. Delete a chat from history. Enter to send · Shift+Enter for a new line.</p></form></section>`;
    const latest=turns.at(-1),signal=latest?latest.id+latest.status:'';if(open&&signal&&signal!==announced){announced=signal;announcements.textContent=latest.status==='succeeded'?'Martin’s answer is ready.':latest.status==='failed'?'Martin could not answer. You can retry.':'';}
    const body=root.querySelector('.martin-body');if(body)body.scrollTop=error||notice?0:bottom?body.scrollHeight:oldScroll;
    if(focused&&open&&!input()?.disabled){input().focus({preventScroll:true});input().setSelectionRange(start,end);}
    launcher().setAttribute('aria-describedby','martin-move-help');
    floating.layout();
  }
  function sync(){const nextOwner=getAccount()?.id||null;if(!initialized||owner!==nextOwner){reset();owner=nextOwner;initialized=true;draw();}const visible=getAccount()?.role!=='admin'&&routes.has(current().split('/')[0]);root.hidden=!visible;if(!visible&&open){open=false;stop();draw();}if(route!==current()){route=current();const ctx=context();const el=root.querySelector('[data-martin-context]');if(el)el.textContent=ctx.label;const link=root.querySelector('[data-martin-insights]');if(link)link.href='#/'+(getAccount()?ctx.insights:'login');}floating.layout();}
  function poll(){stop();if(open&&thread&&active()){const token=epoch;pollTimer=setTimeout(()=>{if(token===epoch)refreshTurns();},2500);}}
  async function refreshTurns(){const token=epoch,id=thread?.id;if(!id)return;try{const data=await api.turns(id);if(token!==epoch||thread?.id!==id)return;const merged=new Map(turns.map(t=>[t.id,t]));data.items.forEach(t=>merged.set(t.id,t));const next=[...merged.values()].sort((a,b)=>a.created_at.localeCompare(b.created_at)||a.id.localeCompare(b.id));const changed=JSON.stringify(turns)!==JSON.stringify(next);turns=next;thread=data.conversation;if(changed)draw({bottom:!historyView});poll();}catch(e){if(token===epoch){error=e.message;draw();stop();}}}
  async function load(){if(!getAccount()||loading)return;const token=epoch;loading=true;error='';draw();try{const [settings,chats,mine]=await Promise.all([api.settings(),api.conversations(),contestApi.mine({limit:20})]);if(token!==epoch)return;config=settings;conversations=chats.items;conversationNext=chats.next_cursor;contests=mine.items;contestNext=mine.next_cursor;loaded=true;const ctx=context();if(!thread&&!selectedContest&&contests.some(c=>c.id===ctx.insights.split('/')[1]))selectedContest=ctx.insights.split('/')[1];}catch(e){if(token===epoch)error=e.message;}finally{if(token===epoch){loading=false;draw();if(thread)refreshTurns();}}}
  function close(){open=false;stop();root.querySelector('#martin-window').hidden=true;launcher().setAttribute('aria-expanded','false');launcher().focus({preventScroll:true});}
  function newChat(nextMode=mode){if(active()){notice='Wait for the current answer or cancel the question before starting another chat.';draw();return;}mode=nextMode;thread=null;turns=[];turnNext=null;historyView=false;notice='';error='';pending=null;draw();if(!input()?.disabled)input().focus({preventScroll:true});}
  async function send(){if(!canSend()||historyView)return;const payload={question:drafts[mode].trim(),mode,contest_id:mode==='performance'&&selectedContest?selectedContest:null,conversation_id:thread?.id||null};const encoded=JSON.stringify(payload);if(!pending||pending.encoded!==encoded)pending={key:crypto.randomUUID(),payload,encoded};const request=pending,token=epoch;busy=true;error='';notice='';draw();try{const turn=await api.ask(request.payload,request.key);if(token!==epoch)return;pending=null;drafts[mode]='';if(!thread)thread={id:turn.conversation_id,mode,contest_id:payload.contest_id,title:payload.question.slice(0,80)};turns=[...turns.filter(t=>t.id!==turn.id),turn];draw({bottom:true});}catch(e){if(token===epoch)error=e.message;}finally{if(token===epoch){busy=false;draw({bottom:true});poll();if(!input()?.disabled)input().focus({preventScroll:true});}}}
  root.addEventListener('click',async event=>{
    const b=event.target.closest('[data-martin]');if(!b||b.disabled)return;const action=b.dataset.martin;
    if(action==='toggle'){if(open)close();else{open=true;root.querySelector('#martin-window').hidden=false;launcher().setAttribute('aria-expanded','true');floating.layout();if(!loaded&&getAccount())load();else if(thread)refreshTurns();if(!input()?.disabled)input().focus({preventScroll:true});}return;}
    if(action==='close'){close();return;}
    if(action==='mode'){if(Object.hasOwn(prompts,b.dataset.mode)&&!busy)newChat(b.dataset.mode);return;}
    if(action==='new'){if(!busy)newChat();return;}
    if(action==='clear'){drafts[mode]='';pending=null;draw();input()?.focus({preventScroll:true});return;}
    if(action==='prompt'){const p=prompts[mode][Number(b.dataset.index)];if(p){drafts[mode]=p;pending=null;draw();if(!input()?.disabled)input().focus({preventScroll:true});}return;}
    if(busy)return;
    if(action==='refresh'){await load();return;}
    const token=epoch;busy=true;error='';notice='';
    try{
      if(action==='history'){historyView=!historyView;if(historyView){const page=await api.conversations();if(token!==epoch)return;conversations=page.items;conversationNext=page.next_cursor;}}
      else if(action==='conversation'){stop();const page=await api.turns(b.dataset.id);if(token!==epoch)return;thread=page.conversation;mode=thread.mode;selectedContest=thread.contest_id||'';turns=page.items.slice().reverse();turnNext=page.next_cursor;historyView=false;}
      else if(action==='history-more'){const page=await api.conversations({cursor:conversationNext});if(token!==epoch)return;conversations=[...conversations,...page.items];conversationNext=page.next_cursor;}
      else if(action==='turns-more'){const page=await api.turns(thread.id,{cursor:turnNext});if(token!==epoch)return;turns=[...page.items.slice().reverse(),...turns];turnNext=page.next_cursor;}
      else if(action==='contests-more'){const page=await contestApi.mine({limit:20,cursor:contestNext});if(token!==epoch)return;contests=[...contests,...page.items];contestNext=page.next_cursor;}
      else if(action==='delete'){if(!window.confirm('Delete this chat and all its saved questions and replies?'))return;await api.remove(b.dataset.id);if(token!==epoch)return;conversations=conversations.filter(c=>c.id!==b.dataset.id);if(thread?.id===b.dataset.id){stop();thread=null;turns=[];turnNext=null;pending=null;}notice='Chat deleted.';}
      else if(action==='retry'||action==='cancel'){const turn=await api.control(b.dataset.id,action);if(token!==epoch)return;turns=turns.map(t=>t.id===turn.id?turn:t);}
    }catch(e){if(token===epoch)error=e.message;}
    finally{if(token===epoch){busy=false;draw({bottom:action==='conversation'});poll();}}
  });
  root.addEventListener('input',event=>{if(event.target.id!=='martin-question')return;drafts[mode]=event.target.value.slice(0,1000);root.querySelector('.martin-count').textContent=drafts[mode].length+'/1000';root.querySelector('[data-martin="clear"]').disabled=!drafts[mode];root.querySelector('.martin-send').disabled=!canSend();});
  root.addEventListener('change',event=>{if(event.target.id==='martin-contest'&&!thread)selectedContest=event.target.value;});
  root.addEventListener('submit',event=>{event.preventDefault();send();});
  root.addEventListener('keydown',event=>{if(event.key==='Escape'&&open){event.preventDefault();event.stopPropagation();close();}else if(event.target.id==='martin-question'&&event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();send();}});
  return {sync,reset};
}
