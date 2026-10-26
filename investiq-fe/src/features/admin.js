import { academyApi } from '../api/services.js';

export function adminLogin({brand,icon}) {
  return `<nav class="mvp-authnav">${brand()}<span class="pill neutral">Administration</span></nav><main class="focused-auth"><header class="auth-title"><h1>Admin sign in</h1><p>Manage InvestIQ contests and learning content.</p></header><form class="panel authform" id="authform" data-kind="login"><label class="field">Email address<input name="email" autocomplete="username" type="email" placeholder="Admin email address" required></label><label class="field">Password<div class="passwordfield"><input id="auth-password" aria-label="Password" name="password" type="password" autocomplete="current-password" required maxlength="128"><button type="button" data-password-toggle aria-label="Show password" aria-pressed="false">Show</button></div></label><a class="positive small" href="#/reset-password">Forgot password?</a><button class="primary full" type="submit">Open admin workspace ${icon('arrow')}</button><p class="small">Use your existing administrator account. Your learner login stays separate.</p></form></main>`;
}

export function adminShell({route,body,brand,icon,esc,name,emailVerified}) {
  const learning=route.startsWith('admin/courses');
  const items=[['contests/admin','trophy','Contests'],['admin/courses','book','Learning content']];
  const navigation=items.map(([href,symbol,label],i)=>`<a href="#/${href}" class="${learning===(i===1)?'active':''}" ${learning===(i===1)?'aria-current="page"':''}>${icon(symbol)}<span>${label}</span></a>`).join('');
  return `<div class="shell admin-shell"><aside class="sidebar">${brand()}<span class="nav-group-label">Administration</span><nav class="sidenav" aria-label="Admin navigation">${navigation}</nav><div class="sidebarbottom"><p class="small">${esc(name)} · Administrator</p><button class="ghost full" data-action="logout">${icon('logout')} Sign out</button></div></aside><div class="workspace"><header class="appbar"><div class="mobilebrand">${brand()}</div><strong>Admin workspace</strong><span class="pill neutral">Contests &amp; learning</span><button class="ghost admin-mobile-signout" data-action="logout">Sign out</button></header><main class="main" id="main-content">${!emailVerified?'<div class="callout"><p>Verify your email before publishing. Check your inbox or <button class="ghost" data-action="request-verification">send another link</button>.</p></div>':''}${body}</main></div><nav class="bottomnav" aria-label="Mobile admin navigation">${navigation}</nav></div>`;
}

export function createAdminController({shell,pagehead,esc,link,icon,render,current,getAccount}) {
  const blankQuestion=()=>({prompt:'',options:'',correct:'1',explanation:''});
  const blank=()=>({title:'',slug:'',description:'',lessonTitle:'',paragraphs:'',xp:'50',questions:[blankQuestion()]});
  let key='',epoch=0,loading=false,error='',courses=[],next=null,busy=false,draft=blank(),notice='';
  const routeKey=()=>JSON.stringify([current(),getAccount()?.id]);
  function reset(){epoch++;key='';loading=false;error='';courses=[];next=null;busy=false;draft=blank();notice='';}
  async function load(more=false){
    const token=++epoch,expected=routeKey();key=expected;loading=true;error='';
    try{
      let page=await academyApi.adminCourses({limit:50,...(more&&next?{cursor:next}:{})});
      const items=more?[...courses,...page.items]:page.items;
      const id=current().split('/')[2];
      // A linked course may be beyond the first page.
      while(id&&id!=='new'&&!items.some(c=>c.id===id)&&page.next_cursor){page=await academyApi.adminCourses({limit:50,cursor:page.next_cursor});items.push(...page.items);}
      if(token!==epoch||expected!==routeKey())return;
      courses=items;next=page.next_cursor;
    }catch(e){if(token===epoch)error=e.message;}
    finally{if(token===epoch){loading=false;render();}}
  }
  function ensure(){if(getAccount()?.role!=='admin')return;if(key!==routeKey()){draft=blank();busy=false;load();}}
  function editor(course){
    const field=(name,label,value,attrs='')=>`<label class="field">${label}<input name="${name}" value="${esc(value)}" ${attrs} required></label>`;
    return `<form data-admin-content-form class="panel admin-editor" aria-busy="${busy}"><fieldset class="admin-editor-fields" ${busy?'disabled':''}><h2>${course?'Add a lesson':'Course details'}</h2>${!course?`${field('title','Course title',draft.title,'maxlength="160"')}<label class="field">URL name<input name="slug" value="${esc(draft.slug)}" pattern="[a-z][a-z0-9-]{0,79}" maxlength="80" placeholder="investing-essentials" required><small>Lowercase letters, numbers and hyphens. Must start with a letter.</small></label><div class="field"><label for="admin-description">Course description</label><textarea id="admin-description" name="description" maxlength="1000" rows="3" required>${esc(draft.description)}</textarea></div><h2>First lesson</h2>`:''}<div class="grid2">${field('lessonTitle','Lesson title',draft.lessonTitle,'maxlength="160"')}${field('xp','Completion XP',draft.xp,'type="number" min="1" max="1000" step="1"')}</div><div class="field"><label for="admin-lesson-content">Lesson content</label><textarea id="admin-lesson-content" name="paragraphs" rows="10" aria-describedby="admin-paragraph-help" required>${esc(draft.paragraphs)}</textarea><small id="admin-paragraph-help">Separate paragraphs with a blank line. Content is displayed as plain text.</small></div><div class="row"><h2>Knowledge check</h2><span class="pill neutral">${draft.questions.length} / 20 questions</span></div><p class="small">Learners earn the lesson’s XP once, after answering every question correctly.</p>${draft.questions.map((q,i)=>`<fieldset class="admin-question"><legend>Question ${i+1}</legend><div class="field"><label for="admin-prompt-${i}">Question text</label><textarea id="admin-prompt-${i}" data-question="${i}" name="prompt" rows="2" maxlength="1000" required>${esc(q.prompt)}</textarea></div><div class="field"><label for="admin-options-${i}">Answer options</label><textarea id="admin-options-${i}" data-question="${i}" name="options" rows="4" aria-describedby="admin-options-help-${i}" required>${esc(q.options)}</textarea><small id="admin-options-help-${i}">One option per line. Add 2–10 distinct options.</small></div>${field(`correct-${i}`,'Correct option number',q.correct,`data-question="${i}" data-question-field="correct" type="number" min="1" max="10" step="1"`)}<div class="field"><label for="admin-explanation-${i}">Answer explanation</label><textarea id="admin-explanation-${i}" data-question="${i}" name="explanation" rows="3" maxlength="2000" required>${esc(q.explanation)}</textarea></div>${draft.questions.length>1?`<button type="button" class="ghost" data-admin-action="remove-question" data-index="${i}">${icon('close')} Remove question</button>`:''}</fieldset>`).join('')}<button type="button" class="secondary" data-admin-action="add-question" ${draft.questions.length>=20||busy?'disabled':''}>${icon('plus')} Add question</button><p class="callout">Publishing makes this ${course?'lesson':'course and its first lesson'} available in Learn immediately.</p><p data-admin-error role="alert" tabindex="-1">${esc(error)}</p><div class="admin-editor-actions"><button type="submit" class="primary" ${busy?'disabled':''}>${icon('check')} ${busy?'Publishing…':course?'Publish lesson':'Publish course'}</button>${link('Cancel','admin/courses','secondary')}</div></fieldset></form>`;
  }
  function page(){
    if(getAccount()?.role!=='admin')return shell('admin',`${pagehead('Administration','Admin access required','Sign in with an administrator account to manage learning content.')}${link('Sign in','login','secondary')}`);
    const id=current().split('/')[2],course=courses.find(c=>c.id===id);
    const heading=pagehead('Learning administration',id==='new'?'Create a course':id?(course?.title||'Course content'):'Learning content',id?'Write a lesson and its knowledge check, then publish it for learners.':'Publish courses and add lessons to the Academy.',!id?link(icon('plus')+' Add course','admin/courses/new','primary'):link('Back to courses','admin/courses','secondary'));
    const wait=key!==routeKey()||loading;
    let body=wait?'<section class="panel" role="status">Loading learning content…</section>':id==='new'?editor():id?course?`<section class="panel admin-course-summary"><p>${esc(course.description)}</p><h2>Published lessons</h2><ol>${course.lessons.map(l=>`<li>${esc(l.title)} <span class="small">${l.xp} XP</span></li>`).join('')}</ol></section>${editor(course)}`:'<section class="panel" role="alert">Course not found.</section>':`${error?`<p class="callout" role="alert">${esc(error)} <button data-admin-action="retry" class="secondary">Retry</button></p>`:''}<div class="contest-grid admin-courses">${courses.map(c=>`<article class="panel"><span class="pill">Published · ${c.lessons.length} lessons</span><h2>${esc(c.title)}</h2><p>${esc(c.description)}</p>${link(icon('plus')+' Add lesson','admin/courses/'+c.id,'secondary')}</article>`).join('')||'<section class="panel empty">No courses yet. Publish your first course to get started.</section>'}</div>${next?'<button class="secondary" data-admin-action="more">Load more courses</button>':''}`;
    return shell('admin',heading+(notice?`<p class="callout" role="status">${esc(notice)}</p>`:'')+body);
  }
  function input(t){if(!t.closest('[data-admin-content-form]')||busy)return;if(t.dataset.question!==undefined){draft.questions[Number(t.dataset.question)][t.dataset.questionField||t.name]=t.value;}else if(Object.hasOwn(draft,t.name))draft[t.name]=t.value;}
  function click(b){if(busy)return;const a=b.dataset.adminAction;if(a==='add-question'&&draft.questions.length<20){draft.questions.push(blankQuestion());render();}else if(a==='remove-question'&&draft.questions.length>1){draft.questions.splice(Number(b.dataset.index),1);render();}else if(a==='more')load(true);else if(a==='retry')load();}
  async function submit(){
    if(busy||getAccount()?.role!=='admin')return;
    error='';notice='';
    const lesson={title:draft.lessonTitle.trim(),xp:Number(draft.xp),paragraphs:draft.paragraphs.split(/\n\s*\n/).map(p=>p.trim()).filter(Boolean),questions:draft.questions.map((q,i)=>({key:'question_'+(i+1),prompt:q.prompt.trim(),options:q.options.split('\n').map(o=>o.trim()).filter(Boolean),correct:Number(q.correct)-1,explanation:q.explanation.trim()}))};
    if(lesson.paragraphs.length>50)error='Use up to 50 paragraphs per lesson.';
    if(lesson.paragraphs.some(p=>p.length>10000))error='Keep each paragraph within 10,000 characters.';
    for(const [i,q] of lesson.questions.entries()){
      if(q.options.length<2||q.options.length>10||new Set(q.options).size!==q.options.length||q.options.some(o=>o.length>500))error=`Question ${i+1}: add 2–10 distinct options, each within 500 characters.`;
      else if(!Number.isInteger(q.correct)||q.correct<0||q.correct>=q.options.length)error=`Question ${i+1}: choose a correct option number from 1 to ${q.options.length}.`;
    }
    if(error){render();document.querySelector('[data-admin-error]')?.focus();return;}
    const token=epoch,expected=routeKey(),id=current().split('/')[2];busy=true;render();
    try{
      if(id==='new'){
        const result=await academyApi.publishCourse({title:draft.title.trim(),slug:draft.slug.trim(),description:draft.description.trim(),lessons:[lesson]});
        if(token!==epoch||expected!==routeKey())return;
        draft=blank();notice='Course published. Learners can now find it in Learn.';location.hash='/admin/courses/'+result.id;
      }else{
        await academyApi.publishLesson(id,lesson);
        if(token!==epoch||expected!==routeKey())return;
        draft=blank();notice='Lesson published and added to this course.';await load();
      }
    }catch(e){if(token===epoch&&expected===routeKey())error=e.status===422?'Check the required fields, paragraph lengths and question options.':e.message;}
    finally{if(expected===routeKey()){busy=false;render();if(error)document.querySelector('[data-admin-error]')?.focus();}}
  }
  return {page,ensure,reset,input,click,submit,deactivate(){if(loading){epoch++;key='';loading=false;}busy=false;}};
}
