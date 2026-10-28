import { communityApi as api } from '../api/services.js';

export function createCommunityController({shell,pagehead,esc,link,icon,render,current,getAccount}) {
  let key='',generation=0,loaded=false,loading=false,busy=false,error='',notice='';
  let items=[],groups=[],joined=[],selected=null,root=null,reports=[],next=null,joinedNext=null;
  let filter='',query='',groupScope='joined',reportId='',moderateId='',lastRoute='';
  const pending=new Map(),drafts=new Map();
  const verified=()=>!!getAccount()?.email_verified;
  function route(){const [,part='',id='']=current().split('/');if(part==='group')return {view:'group',id};if(/^[0-9a-f-]{36}$/i.test(part))return {view:'post',id:part};return {view:part||'feed',id:''};}
  const signature=()=>JSON.stringify([current(),getAccount()?.id,filter,query,groupScope]);
  const formKey=type=>JSON.stringify([getAccount()?.id,current(),type]);
  const stamp=t=>new Date(t).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST';
  const button=(action,label,id='',value='',cls='secondary',attributes='')=>`<button type="button" class="${cls}" data-community-action="${action}" data-id="${esc(id)}" data-value="${esc(value)}" ${busy||loading?'disabled':''} ${attributes}>${label}</button>`;
  function reset(){generation++;key='';loaded=false;loading=false;busy=false;error='';notice='';items=[];groups=[];joined=[];selected=null;root=null;reports=[];next=null;joinedNext=null;filter='';query='';groupScope='joined';reportId='';moderateId='';lastRoute='';pending.clear();drafts.clear();}
  function deactivate(){if(key){generation++;key='';loaded=false;loading=false;busy=false;}}
  async function load(more=false){
    const expected=signature(),token=++generation,r=route();key=expected;loading=true;error='';if(!more)loaded=false;render();
    try{
      const memberPromise=Promise.allSettled([getAccount()?api.groups({scope:'joined',limit:100}):Promise.resolve({items:[],next_cursor:null})]);
      const empty={items:[],next_cursor:null};let content=empty,group=null,post=null,directory=empty;
      const params={...(more&&next?{cursor:next}:{}),...(filter?{kind:filter}:{})};
      if(r.view==='discover'||r.view==='groups'){
        if(r.view==='discover'||getAccount())directory=await api.groups({...(more&&next?{cursor:next}:{}),scope:r.view==='groups'?groupScope:'all',q:query});
      }else if(r.view==='group'){group=await api.group(r.id);if(group.joined)content=await api.feed({...params,group:r.id});}
      else if(r.view==='post')[post,content]=await Promise.all([api.get(r.id),api.comments(r.id,more&&next?{cursor:next}:{})]);
      else if(r.view==='moderation')content=await api.reports(more&&next?{cursor:next}:{});
      else if(r.view!=='create'&&(r.view!=='saved'||getAccount()))content=await api.feed({...params,scope:r.view==='lounge'?'public':r.view==='saved'?'accessible':'joined',...(r.view==='saved'?{saved:true}:{})});
      const [membershipResult]=await memberPromise;if(membershipResult.status==='rejected')throw membershipResult.reason;
      const memberships=membershipResult.value;
      if(token!==generation||expected!==signature())return;
      joined=memberships.items;joinedNext=memberships.next_cursor;selected=group;root=post;
      if(['discover','groups'].includes(r.view)){groups=more?[...groups,...directory.items]:directory.items;next=directory.next_cursor;}
      else if(r.view==='moderation'){reports=more?[...reports,...content.items]:content.items;next=content.next_cursor;}
      else{items=more?[...items,...content.items]:content.items;next=content.next_cursor;}loaded=true;
    }catch(e){if(token===generation&&expected===signature()){error=e.message;loaded=true;}}
    finally{if(token===generation&&expected===signature()){loading=false;render();}}
  }
  function ensure(){
    if(lastRoute!==current()){lastRoute=current();notice='';filter='';query=String(drafts.get(formKey('search'))?.q||'').trim();next=null;}
    if(key!==signature()){busy=false;reportId='';moderateId='';load();}
    for(const form of document.querySelectorAll('[data-community-form]')){const draft=drafts.get(formKey(form.dataset.communityForm));if(draft)for(const [name,value] of Object.entries(draft)){const node=form.elements.namedItem(name);if(node)node.value=value;}}
  }
  function membership(g){
    if(!getAccount())return link('Sign in to join','login','secondary');
    if(!verified())return '<span class="small">Verify your email to join.</span>';
    return button('membership',icon(g.joined?'check':'plus')+(g.joined?'Leave community':'Join community'),g.id,String(!g.joined),g.joined?'secondary':'primary');
  }
  // Stable visual identities without uploading images or exposing private profile photos.
  const initials=name=>esc(String(name).trim().split(/\s+/).map(s=>s[0]).slice(0,2).join('').toUpperCase());
  const identity=id=>{let hash=0;for(const c of String(id))hash=(hash*31+c.charCodeAt(0))>>>0;return ['mint','blue','violet','amber','rose'][hash%5];};
  const symbol=g=>`<span class="community-group-symbol community-tone-${identity(g.id)}" aria-hidden="true">${initials(g.name)}</span>`;
  const glyph=name=>`<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${{upvote:'<path d="m12 3 9 9h-6v9H9v-9H3Z"/>',comment:'<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-3 2V11.5a10 10 0 0 1 20 0Z"/>',bookmark:'<path d="M6 3h12v18l-6-4-6 4Z"/>',more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',pen:'<path d="m16 3 5 5-12 12-6 1 1-6Z M13 6l5 5"/>'}[name]}</svg>`;
  function relativeStamp(t){
    const date=new Date(t),now=new Date(),day=d=>d.toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'});
    if(day(date)===day(now))return 'Today';
    if(day(date)===day(new Date(now.getTime()-86400000)))return 'Yesterday';
    return date.toLocaleDateString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',...(date.getFullYear()!==now.getFullYear()?{year:'numeric'}:{})});
  }

  function groupCard(g){return `<article class="panel community-group-card community-tone-${identity(g.id)}" data-community-group="${esc(g.id)}"><div class="community-cover" aria-hidden="true"><span></span><i></i></div><div class="community-group-content"><div class="community-group-top">${symbol(g)}${g.owned?'<span class="community-access">Created by you</span>':g.joined?'<span class="community-access community-joined">'+icon('check')+' Joined</span>':'<span class="community-access">Members community</span>'}</div><h2>${link(esc(g.name),'social/group/'+g.id,'community-title-link')}</h2><p class="community-group-description">${esc(g.description)}</p><div class="community-group-stats"><span>${icon('users')}<b>${g.members}</b> ${g.members===1?'member':'members'}</span><span>${glyph('comment')}<b>${g.posts||0}</b> ${(g.posts||0)===1?'post':'posts'}</span></div><footer>${link('Open community '+icon('arrow'),'social/group/'+g.id,'ghost')}${membership(g)}</footer></div></article>`;}
  function card(p){
    const total=p.votes.reduce((a,b)=>a+b,0),can=verified(),groupName=p.group_name||selected?.name||joined.find(g=>g.id===p.group_id)?.name||'Community';
    const kindLabel={discussion:'Discussion',idea:'Investment idea',market:'Market talk',poll:'Community poll',comment:'Reply'}[p.kind]||p.kind;
    return `<article class="panel community-post" data-community-post="${p.id}"><header><span class="community-author-avatar community-tone-${identity(p.author)}" aria-hidden="true">${initials(p.author)}</span><div><div class="community-post-byline"><strong>${esc(p.author)}</strong>${p.own?'<span class="community-you">You</span>':''}</div><p>${p.group_id?link(esc(groupName),'social/group/'+p.group_id,'community-post-group'):link('General discussion','social/lounge','community-post-group')}<span aria-hidden="true"> · </span><time datetime="${esc(p.created_at)}" title="${esc(stamp(p.created_at))}">${esc(relativeStamp(p.created_at))}</time></p></div>${can?`<details class="community-post-menu"><summary aria-label="Post options">${glyph('more')}</summary><div>${button('report','Report',p.id,'','ghost')}${p.own?button('delete','Delete',p.id,'','ghost negative'):''}</div></details>`:''}</header><span class="community-post-kind kind-${esc(p.kind)}">${esc(kindLabel)}</span><p class="community-post-body">${esc(p.body)}</p>${p.kind==='poll'?`<div class="poll-options">${p.options.map((o,i)=>`<button type="button" class="poll-choice ${p.my_vote===i?'selected':''}" data-community-action="vote" data-id="${p.id}" data-value="${i}" ${!can||!p.poll_open||p.my_vote!==null||busy||loading?'disabled':''}><span class="community-poll-fill" style="width:${total?p.votes[i]/total*100:0}%" aria-hidden="true"></span><span>${esc(o)}</span><strong>${p.votes[i]} vote${p.votes[i]===1?'':'s'}${p.my_vote===i?' · Your vote':''}</strong></button>`).join('')}<p class="small">${total} total votes · ${p.poll_open?'Closes':'Closed'} ${esc(stamp(p.closes_at))}. One final vote per account.</p></div>`:''}<footer class="community-post-actions">${can?button('like',glyph('upvote')+`<span>${p.likes}</span>`,p.id,String(!p.liked),`ghost community-upvote ${p.liked?'is-upvoted':''}`,`aria-label="${p.liked?'Remove upvote':'Upvote'} · ${p.likes}" aria-pressed="${p.liked}" title="${p.liked?'Remove upvote':'Upvote'}"`):`<span class="community-vote-count" role="img" aria-label="${p.likes} upvotes">${glyph('upvote')}<span>${p.likes}</span></span>`}${p.kind!=='comment'?`<a class="ghost community-replies" href="#/social/${p.id}" aria-label="View ${p.comments} ${p.comments===1?'reply':'replies'}" title="Replies">${glyph('comment')}<span>${p.comments}</span></a>`:''}${can&&p.kind!=='comment'?button('save',glyph('bookmark')+(p.saved?'Unsave':'Save'),p.id,String(!p.saved),`ghost community-save ${p.saved?'is-saved':''}`):''}</footer></article>`;
  }

  function composer(){
    const r=route(),reply=r.view==='post',publicPost=r.view==='lounge';
    if(!getAccount())return `<section class="panel community-empty">${link('Sign in to join the discussion','login','secondary')}</section>`;
    if(!verified())return '<section class="panel community-empty"><p>Verify your email to join communities and share your ideas.</p></section>';
    if(r.view==='group'&&!selected?.joined)return '';
    if(!reply&&!publicPost&&!joined.length)return `<section class="panel community-empty"><span class="community-group-symbol">${icon('users')}</span><h2>Find your people</h2><p>Join a community to see its posts here and start a conversation.</p>${link('Discover communities','social/discover','primary')}</section>`;
    const type=reply?'comment':'post',draft=drafts.get(formKey(type))||{},kind=draft.kind||'discussion';
    return `<section class="panel community-composer"><details ${r.view!=='feed'||Object.keys(draft).length?'open':''}><summary><span class="community-compose-avatar">${glyph('pen')}</span><span><strong>${reply?'Write a reply':'Start a conversation'}</strong><small>${reply?'Add your perspective':'Ask a question or share an investing idea'}</small></span><span class="community-compose-plus">${icon('plus')}</span></summary><form data-community-form="${type}">${!reply&&!publicPost&&r.view!=='group'?`<label class="field">Community<select name="group_id" aria-label="Post community" required><option value="">Choose a community</option>${joined.map(g=>`<option value="${g.id}" ${joined.length===1?'selected':''}>${esc(g.name)}</option>`).join('')}</select></label>${joinedNext?button('joined-more','Load more joined communities'):''}`:''}<label class="field">${reply?'Your reply':'Your post'}<textarea name="body" aria-label="${reply?'Your reply':'Your post'}" maxlength="4000" required placeholder="Share a question, an idea, or something you learned…"></textarea></label>${!reply?`<label class="field">Post category<select name="kind" id="community-kind" aria-label="Post category">${[['discussion','Discussion'],['idea','Investment idea'],['market','Market discussion'],['poll','Poll']].map(([k,label])=>`<option value="${k}" ${kind===k?'selected':''}>${label}</option>`).join('')}</select></label>${kind==='poll'?'<label class="field">Poll options (one per line, 2–6)<textarea name="options" maxlength="750" required></textarea></label><label class="field">Poll duration<select name="days" aria-label="Poll duration"><option value="1">1 day</option><option value="3">3 days</option><option value="7">7 days</option></select></label>':''}`:''}<div class="community-composer-footer"><p class="small">${publicPost||reply&&!root?.group_id?'Public discussion':'Only community members can read this.'} Your profile privacy setting controls your display name.</p><button class="primary" ${busy||loading?'disabled':''}>${icon('plus')}${reply?'Reply':'Publish post'}</button></div></form></details></section>`;
  }
  function circles(){return joined.length?`<div class="community-circles" aria-label="Your community shortcuts">${joined.slice(0,8).map(g=>`<a href="#/social/group/${g.id}" title="${esc(g.name)}">${symbol(g)}<span>${esc(g.name)}</span></a>`).join('')}<a href="#/social/discover"><span class="community-discover-symbol">${icon('plus')}</span><span>Discover</span></a></div>`:'';}
  function sidebar(){return `<aside class="community-sidebar"><section class="panel"><div class="row"><h2>Your circles</h2>${link('View all','social/groups','ghost')}</div>${joined.slice(0,5).map(g=>`<a class="community-sidebar-group" href="#/social/group/${g.id}">${symbol(g)}<span><strong>${esc(g.name)}</strong><small>${g.members} ${g.members===1?'member':'members'} · ${g.posts||0} ${(g.posts||0)===1?'post':'posts'}</small></span>${icon('arrow')}</a>`).join('')||'<p class="small">Find a community that shares your curiosity.</p>'}${link('Explore communities '+icon('arrow'),'social/discover','ghost')}</section><section class="panel community-create-prompt"><span class="community-prompt-art" aria-hidden="true"><i>IQ</i><i>+</i><i>↗</i></span><span class="community-kicker">BETTER TOGETHER</span><h2>Small circle.<br>Big ideas.</h2><p>A place for your classmates, investing club, or curious friends.</p>${link(icon('plus')+' Create community','social/create','secondary')}</section><section class="community-etiquette"><h2>A little community spirit</h2><p>Share your reasoning. Welcome different perspectives. Keep personal account details private.</p>${link('Visit general discussion '+icon('arrow'),'social/lounge','ghost')}</section></aside>`;}
  function createForm(){
    if(!getAccount())return `<section class="panel">${link('Sign in to create a community','login')}</section>`;
    if(!verified())return '<section class="panel"><p>Verify your email before creating a community.</p></section>';
    return `<section class="panel community-create-form"><span class="community-group-symbol">${icon('users')}</span><h2>Create your community</h2><p>Give your circle a clear name and purpose. You’ll join automatically when it’s created.</p><form data-community-form="group"><label class="field">Community name<input name="name" minlength="3" maxlength="80" required placeholder="e.g. MBA Investing Circle"></label><label class="field">Description<textarea name="description" maxlength="500" required placeholder="Who is this community for, and what will you discuss?"></textarea></label><div class="community-access-note">${icon('shield')}<p>Anyone can discover your community. Only members can read its posts and participate. Joining is open to verified accounts.</p></div><button class="primary" ${busy||loading?'disabled':''}>${icon('plus')}Create community</button></form></section>`;
  }
  function reportForm(){return reportId||moderateId?`<section class="panel"><form data-community-form="${moderateId?'moderate':'report'}"><h2>${moderateId?'Moderation decision':'Report content'}</h2>${moderateId?'<label class="field">Decision<select name="action" aria-label="Decision"><option value="hide">Hide</option><option value="restore">Restore hidden content</option><option value="dismiss">Dismiss report</option></select></label>':''}<label class="field">Reason<textarea name="reason" minlength="5" maxlength="500" required></textarea></label><button class="primary" ${busy||loading?'disabled':''}>${moderateId?'Record decision':'Submit report'}</button>${button('cancel','Cancel')}</form></section>`:'';}
  function moderation(){return reportForm()+`<section class="panel"><h2>Reports and recent reviews</h2><p>Reporter identities are kept private.</p>${reports.map(p=>`<article><p>${esc(p.body)}</p><p>Report: ${esc(p.reason)}</p><p>${p.resolved?'Reviewed':'Needs review'} · Content ${esc(p.state)}</p>${button('moderate','Review content',p.content_id)}</article>`).join('')||'<p>No reports yet.</p>'}${next?button('more','Load more reports'):''}</section>`;}
  function page(){
    const r=route(),active=['group','post'].includes(r.view)?'feed':r.view;
    let body='<div class="community-pagehead">'+pagehead('THE INVESTIQ COLLECTIVE','Community','Good investing starts with a great conversation.')+'</div>';
    body+=`<nav class="community-nav" aria-label="Community sections">${[['feed','My feed','social'],['discover','Discover','social/discover'],['groups','My communities','social/groups'],['saved','Saved posts','social/saved']].map(([v,label,url])=>`<a class="${active===v?'active':''}" href="#/${url}" ${active===v?'aria-current="page"':''}>${label}</a>`).join('')}${button('refresh',icon('refresh')+'<span>Refresh</span>','','','ghost')}</nav>`;
    if(key!==signature()||!loaded)return shell('social',body+'<section class="panel" role="status">Loading community…</section>');
    if(error)return shell('social',body+`<section class="panel" role="alert"><p>${esc(error)}</p>${button('refresh','Retry community')}${link('Discover communities','social/discover','ghost')}</section>`);
    if(notice)body+=`<p class="callout" role="status">${esc(notice)}</p>`;
    if(r.view==='create')return shell('social',body+createForm());
    if(['discover','groups'].includes(r.view)){
      body+=`<section class="community-directory-heading"><div><h2>${r.view==='discover'?'Discover communities':'My communities'}</h2><p>${r.view==='discover'?'Find your people. Explore a new perspective.':'Your joined circles and communities you created.'}</p></div><form data-community-form="search" class="community-search"><label class="field">Search communities<input name="q" type="search" maxlength="80" value="${esc(query)}" placeholder="Search by name or interest"></label><button class="secondary" ${loading?'disabled':''}>${icon('search')}Search</button></form></section>`;
      if(r.view==='groups'&&getAccount())body+=`<div class="tabs" role="group" aria-label="Your community views">${[['joined','Joined'],['created','Created by you']].map(([v,label])=>`<button data-community-action="group-scope" data-value="${v}" aria-pressed="${groupScope===v}" class="${groupScope===v?'active':''}">${label}</button>`).join('')}</div>`;
      body+=r.view==='groups'&&!getAccount()?`<section class="panel">${link('Sign in to see your communities','login')}</section>`:`<div class="community-directory">${groups.map(groupCard).join('')||`<section class="panel community-empty"><h2>${query?'No communities found':r.view==='discover'?'Start a new circle':'Your circle starts here'}</h2><p>${query?'Try another name or interest.':'Discover a community to join, or create one for your own group.'}</p>${link('Create community','social/create','secondary')}</section>`}</div>${next?button('more','Load more communities'):''}`;
      return shell('social',body);
    }
    if(r.view==='moderation')return shell('social',body+moderation());
    let stream=r.view==='group'&&selected?`<section class="panel community-banner community-tone-${identity(selected.id)}"><div class="community-cover" aria-hidden="true"><span></span><i></i></div><div class="community-banner-content"><div class="community-banner-heading">${symbol(selected)}<div><span class="community-access">Members feed${selected.owned?' · Created by you':''}</span><h2>${esc(selected.name)}</h2></div>${membership(selected)}</div><p>${esc(selected.description)}</p><div class="community-group-stats"><span>${icon('users')}${selected.members} ${selected.members===1?'member':'members'}</span><span>${selected.posts||0} posts</span></div></div></section>`:'';
    if(r.view==='feed')stream+=circles();
    stream+=reportForm();
    if(r.view==='group'&&!selected?.joined)stream+=`<section class="panel community-empty"><span class="community-group-symbol">${icon('shield')}</span><h2>Join the conversation</h2><p>Join this community to read its feed, share posts, and take part in discussions.</p></section>`;
    else if(r.view==='saved'&&!getAccount())stream+=`<section class="panel">${link('Sign in to see saved posts','login')}</section>`;
    else{
      if(r.view==='lounge')stream+='<div class="community-feed-heading"><h2>General discussion</h2><p>Public conversations open to everyone.</p></div>';
      if(root)stream+=card(root);
      if(r.view!=='saved')stream+=composer();
      if(r.view!=='post')stream+=`<div class="community-feed-heading"><h2>${r.view==='saved'?'Saved posts':r.view==='group'?'Community feed':r.view==='lounge'?'Latest discussions':'Your feed'}</h2>${r.view==='feed'?'<p>Latest posts from communities you’ve joined.</p>':''}<div class="community-feed-filters" role="group" aria-label="Post filters">${[['','All'],['discussion','Discussions'],['idea','Ideas'],['market','Market'],['poll','Polls']].map(([v,label])=>`<button data-community-action="filter" data-value="${v}" aria-pressed="${filter===v}" class="${filter===v?'active':''}">${label}</button>`).join('')}</div></div>`;
      else stream+='<h2 class="community-replies-title">Replies</h2>';
      stream+=items.map(card).join('')||`<section class="panel community-empty"><h3>${r.view==='post'?'No replies yet':r.view==='saved'?'No saved posts in this view':'No posts in this view yet'}</h3><p>${r.view==='post'?'Be the first to add to the conversation.':r.view==='saved'?'Save a post to return to it later.':'Start a conversation, try another filter, or discover another community.'}</p></section>`;
      if(next)stream+=button('more',r.view==='post'?'Load more replies':'Load more posts');
    }
    return shell('social',body+`<div class="community-layout"><div class="community-stream">${stream}</div>${sidebar()}</div>`);
  }
  async function mutate(work,message,navigate=null){
    if(busy||loading)return;const expected=signature(),token=generation;busy=true;notice='';render();
    try{const result=await work();if(token!==generation||expected!==signature())return;notice=message;reportId='';moderateId='';if(navigate){location.hash=navigate(result);return;}await load();}
    catch(e){if(token===generation&&expected===signature()){notice=e.message;if([403,404].includes(e.status))await load();else render();}}
    finally{if(expected===signature()){busy=false;render();}}
  }
  async function click(b){
    if(b.disabled||busy||loading)return;const a=b.dataset.communityAction,id=b.dataset.id,v=b.dataset.value;
    if(a==='refresh'){load();return;}if(a==='more'){load(true);return;}if(a==='filter'){filter=v;load();return;}if(a==='group-scope'){groupScope=v;load();return;}
    if(a==='joined-more'){
      const expected=signature(),token=generation;loading=true;render();
      try{const page=await api.groups({scope:'joined',limit:100,cursor:joinedNext});if(expected===signature()&&token===generation){joined=[...new Map([...joined,...page.items].map(g=>[g.id,g])).values()];joinedNext=page.next_cursor;}}
      catch(e){if(expected===signature()&&token===generation)notice=e.message;}
      finally{if(expected===signature()&&token===generation){loading=false;render();}}return;
    }
    if(a==='report'||a==='moderate'){reportId=a==='report'?id:'';moderateId=a==='moderate'?id:'';render();return;}if(a==='cancel'){reportId='';moderateId='';render();return;}
    if(a==='like'||a==='save')return mutate(()=>api.flag(id,a,v==='true'),'Preference saved.');
    if(a==='vote')return mutate(()=>api.vote(id,Number(v)),'Your final vote was recorded.');
    if(a==='membership'){if(v==='false'&&!window.confirm('Leave this community? Its posts will no longer appear in your feed. You can join again later.'))return;return mutate(()=>api.membership(id,v==='true'),v==='true'?'Community joined. Its posts are now available.':'You left the community.');}
    if(a==='delete'&&window.confirm('Delete this content? This cannot be undone.'))return mutate(()=>api.remove(id),'Content deleted.');
  }
  function input(el){const form=el.closest('[data-community-form]');if(form)drafts.set(formKey(form.dataset.communityForm),Object.fromEntries(new FormData(form)));}
  function change(el){input(el);if(el.id==='community-kind')render();}
  async function submit(form){
    const type=form.dataset.communityForm,data=Object.fromEntries(new FormData(form)),draftKey=formKey(type),requestRoute=signature(),requestGeneration=generation;
    if(type==='search'){query=String(data.q||'').trim();load();return;}
    if(type==='group')return mutate(async()=>{const result=await api.createGroup(data);if(requestRoute===signature()&&requestGeneration===generation)drafts.delete(draftKey);return result;},'Community created.',result=>'/social/group/'+result.id);
    if(type==='report')return mutate(()=>api.report(reportId,data.reason),'Report sent for administrator review.');
    if(type==='moderate')return mutate(()=>api.moderate(moderateId,data),'Moderation decision recorded.');
    const r=route(),groupId=r.view==='group'?r.id:data.group_id;
    if(type==='post'&&r.view!=='lounge'&&!groupId){notice='Choose a joined community before posting.';render();return;}
    const payload=type==='comment'?{body:data.body}:{body:data.body,kind:data.kind,...(groupId?{group_id:groupId}:{}),...(data.kind==='poll'?{options:data.options.split('\n').map(s=>s.trim()).filter(Boolean),closes_at:new Date(Date.now()+Number(data.days)*86400000).toISOString()}:{})};
    const requestKey=JSON.stringify([getAccount()?.id,current(),type,data]);if(!pending.has(requestKey))pending.set(requestKey,{key:crypto.randomUUID(),payload});
    const attempt=pending.get(requestKey),expected=signature(),token=generation;
    return mutate(async()=>{if(type==='comment')await api.comment(r.id,attempt.payload,attempt.key);else await api.create(attempt.payload,attempt.key);if(expected===signature()&&token===generation){pending.delete(requestKey);drafts.delete(formKey(type));}},type==='comment'?'Reply published.':'Post published.');
  }
  return {page,ensure,reset,deactivate,click,submit,input,change};
}
