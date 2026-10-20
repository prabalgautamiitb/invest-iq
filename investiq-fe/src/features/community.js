import { communityApi as api } from '../api/services.js';

export function createCommunityController({shell,pagehead,esc,link,render,current,getAccount}) {
  let key='',generation=0,loaded=false,loading=false,busy=false,error='',notice='',items=[],groups=[],root=null,reports=[],next=null,groupNext=null,filter='',group='',reportId='',moderateId='',composeKind='discussion';
  const pending=new Map(),drafts=new Map(),formDrafts=new Map();
  const route=()=>current().split('/')[1]||'';
  const signature=()=>JSON.stringify([current(),getAccount()?.id,filter,group]);
  const verified=()=>!!getAccount()?.email_verified;
  const stamp=t=>new Date(t).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  function reset(){generation++;key='';loaded=false;loading=false;busy=false;error='';notice='';items=[];groups=[];root=null;reports=[];next=null;groupNext=null;filter='';group='';reportId='';moderateId='';pending.clear();drafts.clear();formDrafts.clear();}
  function deactivate(){if(key){generation++;key='';loaded=false;loading=false;busy=false;}}
  async function load(more=false){
    const expected=signature(),token=++generation,r=route();
    key=expected;loading=true;error='';if(!more)loaded=false;render();
    try {
      const params={...(next&&more?{cursor:next}:{}),...(filter&&filter!=='saved'?{kind:filter}:{}),...(filter==='saved'?{saved:true}:{}),...(group?{group}:{} )};
      const [content,allGroups]=await Promise.all([r==='moderation'?api.reports(more&&next?{cursor:next}:{}):r?api.comments(r,more&&next?{cursor:next}:{}):api.feed(params),api.groups()]);
      const post=r&&r!=='moderation'?await api.get(r):null;
      const selectedId=post?.group_id||group;
      if(selectedId&&!allGroups.items.some(g=>g.id===selectedId))allGroups.items.push(await api.group(selectedId));
      if(token!==generation||expected!==signature())return;
      groups=allGroups.items;groupNext=allGroups.next_cursor;root=post;
      if(r==='moderation'){reports=more?[...reports,...content.items]:content.items;next=content.next_cursor;}
      else {items=more?[...items,...content.items]:content.items;next=content.next_cursor;}
      loaded=true;
    }catch(e){if(token===generation&&expected===signature()){error=e.message;loaded=true;}}
    finally{if(token===generation&&expected===signature()){loading=false;render();}}
  }
  function ensure(){if(key!==signature()){busy=false;reportId='';moderateId='';load();}for(const form of document.querySelectorAll('[data-community-form]')){const saved=formDrafts.get(form.dataset.communityForm);if(saved)for(const [name,value] of Object.entries(saved)){const el=form.elements.namedItem(name);if(el)el.value=value;}}}
  const button=(action,label,id='',value='')=>`<button class="secondary" data-community-action="${action}" data-id="${esc(id)}" data-value="${esc(value)}" ${busy||loading?'disabled':''}>${label}</button>`;
  function card(p){
    const signed=!!getAccount(),can=verified(),total=p.votes.reduce((a,b)=>a+b,0),g=groups.find(g=>g.id===p.group_id);
    return `<article class="panel post" data-community-post="${p.id}"><div class="row"><strong>${esc(p.author)}${p.own?' · You':''}</strong><span class="pill neutral">${esc(p.kind)}</span></div><p class="small">${esc(stamp(p.created_at))}${g?' · '+esc(g.name):''}</p><p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(p.body)}</p>${p.kind==='poll'?`<div class="poll-options">${p.options.map((o,i)=>`<button class="poll-choice ${p.my_vote===i?'selected':''}" data-community-action="vote" data-id="${p.id}" data-value="${i}" ${!can||!p.poll_open||p.my_vote!==null||busy||loading?'disabled':''}><span>${esc(o)}</span><strong>${p.votes[i]} vote${p.votes[i]===1?'':'s'}${p.my_vote===i?' · Your vote':''}</strong></button>`).join('')}<p class="small">${total} total votes · ${p.poll_open?'Closes':'Closed'} ${esc(stamp(p.closes_at))}. One final vote per account.</p></div>`:''}<div class="postfooter">${can?button('like',`${p.liked?'Unlike':'Like'} · ${p.likes}`,p.id,String(!p.liked)):`<span>${p.likes} likes</span>`}${p.kind!=='comment'?link(`${p.comments} replies`,'social/'+p.id,'ghost'):''}${can?(p.kind!=='comment'?button('save',p.saved?'Unsave':'Save',p.id,String(!p.saved)):'')+button('report','Report',p.id):''}${p.own&&can?button('delete','Delete',p.id):''}</div>${!signed?'<p class="small">Sign in and verify your email to participate.</p>':''}</article>`;
  }
  function composer(){
    if(!getAccount())return `<section class="panel">${link('Sign in to join the discussion','login')}</section>`;
    if(!verified())return '<section class="panel">Verify your email to post, reply, vote, save posts or join groups.</section>';
    const r=route(),selectedGroup=groups.find(g=>g.id===(root?.group_id||group));
    if(selectedGroup&&!selectedGroup.joined)return '<p class="callout">Join this public group before posting or replying.</p>';
    return `<section class="panel"><h2>${r?'Write a reply':'Share a thought or question'}</h2><form data-community-form="${r?'comment':'post'}"><label class="field">${r?'Your reply':'Your post'}<textarea name="body" aria-label="${r?'Your reply':'Your post'}" maxlength="4000" required>${esc(drafts.get(r?'comment':'post')||'')}</textarea></label>${!r?`<label class="field">Post category<select name="kind" id="community-kind" aria-label="Post category">${['discussion','idea','market','poll'].map(k=>`<option value="${k}" ${composeKind===k?'selected':''}>${k}</option>`).join('')}</select></label>${composeKind==='poll'?'<label class="field">Poll options (one per line, 2–6)<textarea name="options" maxlength="750" required></textarea></label><label class="field">Poll duration<select name="days" aria-label="Poll duration"><option value="1">1 day</option><option value="3">3 days</option><option value="7">7 days</option></select></label>':''}`:''}<p class="small">${selectedGroup?'Posting in '+esc(selectedGroup.name):'Public discussion'} · Your public-profile setting controls whether other people see your name.</p><button class="primary" ${busy||loading?'disabled':''}>${r?'Reply':'Publish post'}</button></form></section>`;
  }
  function groupPanel(){return `<section class="panel"><h2>Public groups</h2><p class="small">Anyone can read. Join a group to post and reply.</p>${groups.map(g=>`<div class="settingsrow"><div><strong>${esc(g.name)}</strong><p>${esc(g.description)}</p><p>${g.members} member${g.members===1?'':'s'}</p>${button('group','View group',g.id)}</div>${verified()?button('membership',g.joined?'Leave group':'Join group',g.id,String(!g.joined)):''}</div>`).join('')||'<p>No groups yet. Create the first public learning group.</p>'}${groupNext?button('groups-more','Load more groups'):''}${verified()?'<details><summary>Create a public group</summary><form data-community-form="group"><label class="field">Group name<input name="name" minlength="3" maxlength="80" required></label><label class="field">Description<textarea name="description" maxlength="500" required></textarea></label><button class="primary">Create group</button></form></details>':''}</section>`;}
  function page(){
    const r=route();let body=pagehead('Connect','Community','Public learning discussions, ideas and polls. Keep account details and portfolio holdings private.');
    body+=`<div class="flex" style="margin-bottom:20px">${link('All discussions','social','secondary')}${button('refresh','Refresh community')}${getAccount()?.role==='admin'?link('Moderation','social/moderation','secondary'):''}</div>`;
    if(r==='moderation'&&getAccount()?.role!=='admin')return shell('social',body+'<p class="callout">Administrator access required.</p>');
    if(key!==signature()||!loaded)return shell('social',body+'<section class="panel" role="status">Loading community…</section>');
    if(error)return shell('social',body+`<section class="panel" role="alert">${esc(error)} ${button('refresh','Retry community')}</section>`);
    if(notice)body+=`<p class="callout" role="status">${esc(notice)}</p>`;
    if(reportId||moderateId)body+=`<section class="panel"><form data-community-form="${moderateId?'moderate':'report'}"><h2>${moderateId?'Moderation decision':'Report content'}</h2>${moderateId?'<label class="field">Decision<select name="action" aria-label="Decision"><option value="hide">Hide</option><option value="restore">Restore hidden content</option><option value="dismiss">Dismiss report</option></select></label>':''}<label class="field">Reason<textarea name="reason" minlength="5" maxlength="500" required></textarea></label><button class="primary" ${busy||loading?'disabled':''}>${moderateId?'Record decision':'Submit report'}</button>${button('cancel','Cancel')}</form></section>`;
    if(r==='moderation')return shell('social',body+`<section class="panel"><h2>Reports and recent reviews</h2><p>Unresolved reports appear first. Reporter identities are kept private.</p>${reports.map(p=>`<article class="post"><p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(p.body)}</p><p>Report: ${esc(p.reason)}</p><p>${p.resolved?'Reviewed':'Needs review'} · Content ${esc(p.state)}</p>${button('moderate','Review content',p.content_id)}</article>`).join('')||'<p>No reports yet.</p>'}${next?button('more','Load more reports'):''}</section>`);
    if(!r)body+=`<div class="tabs">${[['','All'],['idea','Ideas'],['market','Market'],['poll','Polls'],...(getAccount()?[['saved','Saved']]:[])].map(([v,n])=>button('filter',n,'',v)).join('')}</div>${group?`<p class="callout">Viewing ${esc(groups.find(g=>g.id===group)?.name||'public group')} ${button('group','Clear group')}</p>`:''}`;
    body+=`<div class="socialgrid"><div>${root?card(root):''}${composer()}${r?'<h2>Replies</h2>':''}${items.map(card).join('')||'<section class="panel">No posts in this view yet.</section>'}${next?button('more','Load more posts'):''}</div><aside>${groupPanel()}</aside></div>`;
    return shell('social',body);
  }
  async function mutate(work,message){
    if(busy||loading)return;const expected=signature(),token=generation;busy=true;notice='';render();
    try{await work();if(token!==generation||expected!==signature())return;notice=message;reportId='';moderateId='';await load();}
    catch(e){if(token===generation&&expected===signature()){notice=e.message;render();}}
    finally{if(expected===signature()){busy=false;render();}}
  }
  async function click(b){
    if(b.disabled||busy||loading)return;
    const a=b.dataset.communityAction,id=b.dataset.id,v=b.dataset.value;
    if(a==='refresh'){load();return;}
    if(a==='more'){load(true);return;}
    if(a==='groups-more'){
      const expected=signature(),token=generation;loading=true;render();
      try{const page=await api.groups({cursor:groupNext});if(expected===signature()&&token===generation){const merged=new Map([...groups,...page.items].map(g=>[g.id,g]));groups=[...merged.values()];groupNext=page.next_cursor;}}
      catch(e){if(expected===signature()&&token===generation)notice=e.message;}
      finally{if(expected===signature()&&token===generation){loading=false;render();}}return;
    }
    if(a==='filter'){filter=v;load();return;}
    if(a==='group'){group=id;if(route())location.hash='/social';else load();return;}
    if(a==='report'||a==='moderate'){reportId=a==='report'?id:'';moderateId=a==='moderate'?id:'';render();return;}
    if(a==='cancel'){reportId='';moderateId='';render();return;}
    if(a==='like'||a==='save')return mutate(()=>api.flag(id,a,v==='true'),'Preference saved.');
    if(a==='vote')return mutate(()=>api.vote(id,Number(v)),'Your final vote was recorded.');
    if(a==='membership')return mutate(()=>api.membership(id,v==='true'),'Group membership updated.');
    if(a==='delete'&&window.confirm('Delete this content? This cannot be undone.'))return mutate(()=>api.remove(id),'Content deleted.');
  }
  function input(el){const form=el.closest('[data-community-form]');if(form)formDrafts.set(form.dataset.communityForm,Object.fromEntries(new FormData(form)));if(el.name==='body')drafts.set(route()?'comment':'post',el.value);}
  function change(el){input(el);if(el.id==='community-kind'){composeKind=el.value;render();}}
  async function submit(form){
    const type=form.dataset.communityForm,data=Object.fromEntries(new FormData(form));
    if(type==='group')return mutate(()=>api.createGroup(data),'Public group created.');
    if(type==='report')return mutate(()=>api.report(reportId,data.reason),'Report sent for administrator review.');
    if(type==='moderate')return mutate(()=>api.moderate(moderateId,data),'Moderation decision recorded.');
    const payload=type==='comment'?{body:data.body}:{body:data.body,kind:data.kind,...(group?{group_id:group}:{}),...(data.kind==='poll'?{options:data.options.split('\n').map(s=>s.trim()).filter(Boolean),closes_at:new Date(Date.now()+Number(data.days)*86400000).toISOString()}:{} )};
    // Keep the normalized payload and request key after an ambiguous response, including a poll's timestamp.
    const requestSignature=JSON.stringify([getAccount()?.id,type,route(),data,group]);
    if(!pending.has(requestSignature))pending.set(requestSignature,{key:crypto.randomUUID(),payload});
    const attempt=pending.get(requestSignature),expected=signature(),epoch=generation;
    return mutate(async()=>{if(type==='comment')await api.comment(route(),attempt.payload,attempt.key);else await api.create(attempt.payload,attempt.key);if(expected===signature()&&epoch===generation){pending.delete(requestSignature);drafts.delete(type);formDrafts.delete(type);}},type==='comment'?'Reply published.':'Post published.');
  }
  return {page,ensure,reset,deactivate,click,submit,input,change};
}
