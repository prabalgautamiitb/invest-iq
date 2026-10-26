import { academyApi } from '../api/services.js';

export function createLearningController({shell,pagehead,esc,link,render,current,getAccount}) {
  let notice='',courseFilter='all';
  let key='',generation=0,loading=false,loaded=false,error='',courses=[],progress=null,lesson=null,history=[],historyCursor=null,courseCursor=null,result=null,answers={},retry=null;
  const routeKey=()=>JSON.stringify([current(),getAccount()?.id]);
  const lessonId=()=>current().split('/')[1];
  function reset(){notice='';courseFilter='all';key='';generation++;loading=false;loaded=false;error='';courses=[];progress=null;lesson=null;history=[];result=null;answers={};retry=null;historyCursor=null;courseCursor=null;}
  const button=(action,label,id='')=>`<button class="secondary" data-learning-action="${action}" data-id="${esc(id)}" ${loading?'disabled':''}>${label}</button>`;
  async function load() {
    const expected=routeKey();reset();key=expected;const token=generation;loading=true;
    try {
      const signed=!!getAccount(),id=lessonId();
      const [content,p,h]=await Promise.all([id?academyApi.lesson(id):academyApi.courses(),signed?academyApi.progress():null,id&&signed?academyApi.attempts(id):null]);
      if(token!==generation||expected!==routeKey())return;
      if(id)lesson=content;else{courses=content.items;courseCursor=content.next_cursor;}
      progress=p;history=h?.items||[];historyCursor=h?.next_cursor||null;loaded=true;
    } catch(e){if(token===generation&&expected===routeKey()){error=e.message;loaded=true;}}
    finally{if(token===generation&&expected===routeKey()){loading=false;render();}}
  }
  function ensure(){if(key!==routeKey())load();}
  function totals(){if(!progress)return `<p>${link('Sign in','login','ghost')} to save learning progress. Guest practice activity is kept separate.</p>`;return `<div class="grid4">${[['Total XP',progress.xp],['Lessons completed',progress.completed_lesson_ids.length],['Current streak',progress.current_streak+' days'],['Longest streak',progress.longest_streak+' days']].map(([label,value])=>`<section class="panel stat"><p class="small">${label}</p><strong class="num">${value}</strong></section>`).join('')}</div><p class="small">Streaks count first-time lesson completions on distinct days in Asia/Kolkata. Pass every quiz question to complete a lesson. Retakes do not award extra XP or coins. First-time lesson completions earn 50 virtual coins in the Rewards sandbox.</p>`;}
  function feedback(a){return `<article class="callout"><strong>${a.passed?'Quiz passed':'Keep learning'} · ${a.correct_count}/${a.total} correct · ${a.xp_awarded} XP awarded</strong>${a.feedback.map(f=>`<p>${f.correct?'✓':'Try again'} · ${esc(f.explanation)}</p>`).join('')}</article>`;}
  function page(){
    const wrap=body=>shell('academy',body);
    let body=pagehead('Learn','Your Academy','Development curriculum: simulation mechanics and reading recorded evidence.');
    if(key!==routeKey()||!loaded)return wrap(body+'<section class="panel" role="status">Loading Academy…</section>');
    if(error)return wrap(body+`<section class="panel" role="alert"><p>${esc(error)}</p>${button('refresh','Retry Academy')}</section>`);
    body+=totals()+(notice?`<p class="callout" role="alert">${esc(notice)}</p>`:'');
    if(!lesson){
      const enrolledIds=new Set(progress?.enrolled_course_ids||[]);
      const enrolledCount=courses.filter(c=>enrolledIds.has(c.id)).length;
      const visible=courses.filter(c=>courseFilter==='all'||(courseFilter==='enrolled'?enrolledIds.has(c.id):!enrolledIds.has(c.id)));
      const views=[['all','All courses',courses.length],['enrolled','My courses',enrolledCount],['available','Not enrolled',courses.length-enrolledCount]];
      const empty=courseFilter==='enrolled'?(courseCursor?"No enrolled courses in the loaded catalogue. Load more courses to browse the rest.":"You haven’t enrolled in a course yet. Browse All courses to get started."):courseFilter==='available'?(courseCursor?'No unenrolled courses in the loaded catalogue. Load more courses to browse the rest.':'You’re enrolled in every published course. You can continue learning in My courses.'):'No published courses yet.';
      body+=`<div class="section-heading"><h2>Courses</h2>${button('refresh','Refresh Academy')}</div>
        ${getAccount()?`<div class="tabs" role="group" aria-label="Course views">${views.map(([value,label,count])=>`<button type="button" class="${courseFilter===value?'active':''}" data-learning-action="filter" data-id="${value}" aria-pressed="${courseFilter===value}" ${loading?'disabled':''}>${label} (${count})</button>`).join('')}</div>`:''}
        <p class="small" role="status">${courses.length} ${courseCursor?'courses loaded':'published courses'}${progress?` · ${enrolledCount} enrolled · ${courses.length-enrolledCount} not enrolled`:''}. ${courseCursor?'Load more to see the rest of the catalogue.':courseFilter==='all'?'This is the complete course catalogue.':''}</p>
        <div class="grid2">${visible.map(c=>{const enrolled=enrolledIds.has(c.id),done=c.lessons.filter(l=>progress?.completed_lesson_ids.includes(l.id)).length;return `<section class="panel" data-learning-course="${esc(c.id)}"><h2>${esc(c.title)}</h2><p>${esc(c.description)}</p><p>${done} / ${c.lessons.length} lessons completed</p>${getAccount()&&!enrolled?button('enroll','Enroll in course',c.id):enrolled?'<p class="positive">Enrolled</p>':''}${c.lessons.map(l=>`<div class="settingsrow"><div>${link(esc(l.title),'academy/'+l.id,'ghost')}<p class="small">${l.xp} XP · ${progress?.completed_lesson_ids.includes(l.id)?'Completed':'Not completed'}</p></div></div>`).join('')}</section>`;}).join('')||`<section class="panel"><p>${empty}</p>${courseFilter!=='all'?button('filter','Browse all courses','all'):''}</section>`}</div>${courseCursor?button('courses-more','Load more courses',courseCursor):''}`;
      if(progress)body+=`<section class="panel" style="margin-top:22px"><h2>Your achievements</h2>${progress.achievements.map(a=>`<p>${esc({first_lesson:'First lesson completed',first_course:'First course completed',three_day_streak:'Three-day learning streak'}[a.code]||a.code)} · ${esc(new Date(a.awarded_at).toLocaleDateString('en-IN',{timeZone:'Asia/Kolkata'}))}</p>`).join('')||'<p>Complete a lesson to earn your first achievement.</p>'}</section>`;
    } else {
      const enrolled=progress?.enrolled_course_ids.includes(lesson.course_id);
      body+=`<section class="panel lessonbody" style="margin-top:22px">${link('All courses','academy','ghost')}<h2>${esc(lesson.title)}</h2><p class="small">Version ${lesson.version} · ${lesson.xp} XP on first completion</p>${lesson.paragraphs.map(p=>`<p>${esc(p)}</p>`).join('')}<h3>Check your understanding</h3>${lesson.questions.map(q=>`<fieldset><legend>${esc(q.prompt)}</legend>${q.options.map((o,i)=>`<label class="settingsrow"><span>${esc(o)}</span><input type="radio" name="question-${esc(q.key)}" value="${i}" data-learning-question="${esc(q.key)}" ${answers[q.key]===i?'checked':''} ${loading?'disabled':''}></label>`).join('')}</fieldset>`).join('')}${!getAccount()?link('Sign in to take the quiz','login'):!enrolled?button('enroll','Enroll to take this quiz',lesson.course_id):`<button class="primary" data-learning-action="submit" ${loading||lesson.questions.some(q=>answers[q.key]===undefined)?'disabled':''}>Submit quiz</button>`}${result?feedback(result):''}</section>`;
      if(getAccount())body+=`<section class="panel" style="margin-top:22px"><h2>Your attempt history</h2>${history.map(a=>`<div class="settingsrow"><span>${esc(new Date(a.submitted_at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'}))} IST · ${a.correct_count}/${a.total} · ${a.passed?'Passed':'Not passed'}</span><strong>${a.xp_awarded} XP</strong></div>`).join('')||'<p>No attempts yet.</p>'}${historyCursor?button('history-more','Load more attempts',historyCursor):''}</section>`;
    }
    return wrap(body);
  }
  async function click(b){
    if(b.disabled||loading)return;
    const action=b.dataset.learningAction;
    if(action==='refresh'){reset();render();return;}
    if(action==='filter'){if(['all','enrolled','available'].includes(b.dataset.id)){courseFilter=b.dataset.id;render();}return;}
    const expected=routeKey(),token=generation;loading=true;notice='';render();
    try {
      if(action==='enroll'){
        await academyApi.enroll(b.dataset.id);
        const p=await academyApi.progress();if(token===generation&&expected===routeKey())progress=p;
      } else if(action==='submit') {
        const input={version_id:lesson.version_id,answers:lesson.questions.map(q=>({question_key:q.key,choice:answers[q.key]}))};
        const serialized=JSON.stringify(input);
        if(retry?.serialized!==serialized)retry={serialized,key:crypto.randomUUID()};
        const r=await academyApi.submitAttempt(lesson.id,input,retry.key);
        const [p,h]=await Promise.all([academyApi.progress(),academyApi.attempts(lesson.id)]);
        if(token===generation&&expected===routeKey()){result=r;progress=p;history=h.items;historyCursor=h.next_cursor;retry=null;}
      } else if(action==='courses-more') {
        const c=await academyApi.courses({cursor:b.dataset.id});
        if(token===generation&&expected===routeKey()){courses.push(...c.items);courseCursor=c.next_cursor;}
      } else if(action==='history-more') {
        const h=await academyApi.attempts(lesson.id,{cursor:b.dataset.id});
        if(token===generation&&expected===routeKey()){history.push(...h.items);historyCursor=h.next_cursor;}
      }
    } catch(e){if(token===generation&&expected===routeKey())notice=e.message;}
    finally{if(token===generation&&expected===routeKey()){loading=false;render();}}
  }
  function change(input){if(loading)return;answers[input.dataset.learningQuestion]=Number(input.value);result=null;render();}
  return {page,ensure,reset,click,change,deactivate(){if(loading)reset();}};
}
