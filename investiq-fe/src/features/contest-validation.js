const labels={name:'Contest name',capacity:'Maximum members',capital:'Virtual capital',entry_opens_at:'Entry opens',entry_closes_at:'Entry closes',starts_at:'Contest starts',ends_at:'Contest ends',min_holdings:'Minimum holdings',max_holdings:'Maximum holdings',max_position_bps:'Maximum position',simulated_cost_bps:'Simulated cost',eligible_instrument_ids:'Eligible stocks'};

export function contestFormIssues(values,simulationSessions=null) {
  const issues=[];
  const dates=['entry_opens_at','entry_closes_at','starts_at','ends_at'];
  const instants=dates.map(name=>{const value=String(values.get(name)||'');return value?new Date(value+'+05:30').getTime():NaN;});
  for(const [i,name] of dates.entries())if(values.get(name)&&!Number.isFinite(instants[i]))issues.push({field:name,message:`Enter a valid ${labels[name].toLowerCase()} date and time in IST.`});
  const checks=[
    [0,1,'Entry opens must be before entry closes.'],
    [1,2,'Entry closes must be before the contest starts.'],
    [2,3,'Contest ends must be after the contest starts.']
  ];
  for(const [from,to,message] of checks)if(Number.isFinite(instants[from])&&Number.isFinite(instants[to])&&instants[from]>=instants[to]){
    issues.push({field:dates[from],message},{field:dates[to],message});
  }
  if(simulationSessions?.length)for(const field of ['starts_at','ends_at']){
    const day=String(values.get(field)||'').slice(0,10);
    if(day&&!simulationSessions.includes(day))issues.push({field,message:`Choose a covered simulation session between ${simulationSessions[0]} and ${simulationSessions.at(-1)}. This environment has no prices for ${day}.`});
  }
  const min=Number(values.get('min_holdings')),max=Number(values.get('max_holdings'));
  if(min>max)issues.push({field:'max_holdings',message:'Maximum holdings must be at least minimum holdings.'});
  if(values.getAll('eligible').length<min)issues.push({field:'eligible_instrument_ids',message:`Select at least ${min} eligible stocks to match minimum holdings.`});
  return issues;
}

export function clearContestFormErrors(form) {
  form.querySelectorAll('[data-contest-field-error]').forEach(el=>{el.textContent='';el.hidden=true;});
  form.querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
  const summary=form.querySelector('[data-contest-form-error]');if(summary)summary.textContent='';
}

export function showContestFormErrors(form,issues,{focus=true,message=''}={}) {
  clearContestFormErrors(form);
  let first;
  for(const issue of issues){
    const error=[...form.querySelectorAll('[data-contest-field-error]')].find(el=>el.dataset.contestFieldError===issue.field);
    if(error){error.textContent=issue.message;error.hidden=false;}
    const field=issue.field==='eligible_instrument_ids'?form.querySelector('[data-contest-eligible-group]'):[...form.elements].find(el=>el.name===issue.field);
    if(field){field.setAttribute('aria-invalid','true');first||=field.matches('fieldset')?field.querySelector('input'):field;}
  }
  const summary=form.querySelector('[data-contest-form-error]');
  if(summary)summary.textContent=message||[...new Set(issues.map(issue=>issue.message))].join(' ');
  if(focus&&(issues.length||message)){
    const target=first||summary;target?.focus({preventScroll:true});target?.scrollIntoView({block:'center'});
  }
}

export function contestApiIssues(error) {
  return (error.details?.error?.details||[]).flatMap(detail=>{
    const field=detail.location?.at(-1);
    return labels[field]?[{field,message:detail.message||`Check ${labels[field].toLowerCase()}; its value is invalid.`}]:[];
  });
}
