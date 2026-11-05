const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=value=>'₹'+Number(value).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const day=value=>value?new Date(value+'T12:00:00+05:30').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}):'Starting capital';

export function capitalChart(series,{activeContests=0}={}) {
  const rows=series.filter(r=>r.total_value!=null&&Number.isFinite(Number(r.total_value))).slice().sort((a,b)=>(a.session_date||'').localeCompare(b.session_date||''));
  const closes=rows.filter(r=>r.session_date).length;
  const table=`<details class="capital-value-details"><summary>Exact portfolio values</summary><div class="tablewrap"><table><thead><tr><th>Daily close</th><th>Virtual value</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.session_date||'Starting capital')}</td><td>${money(r.total_value)}</td></tr>`).join('')}</tbody></table></div></details>`;
  const header=`<header class="capital-chart-heading"><div><h3>Portfolio value over time</h3><p>${closes?`${closes} published ${closes===1?'close':'closes'} · Virtual INR`:'Your performance timeline'}</p></div><span class="capital-range-label">All history</span></header>`;
  if(!closes)return `<section class="home-value-chart capital-chart capital-chart--waiting">${header}<div class="capital-chart-empty"><span class="capital-empty-icon" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M6 6v20h21M11 20v-6m6 6V9m6 11v-9"/></svg></span><h3>Waiting for your first valuation</h3><p>Your starting capital is ready. Your first published contest close will begin this chart.</p><ol class="capital-start-steps"><li ${activeContests?'class="is-done"':''}><span>${activeContests?'✓':'1'}</span>Join a contest</li><li><span>2</span>Confirm your portfolio</li><li><span>3</span>Follow daily results</li></ol></div>${table}</section>`;
  const values=rows.map(r=>Number(r.total_value)),first=values[0],last=values.at(-1);
  const tone=last>first?'gain':last<first?'loss':'flat';
  const minimum=Math.min(...values),maximum=Math.max(...values),padding=Math.max((maximum-minimum)*.18,Math.abs(maximum)*.001,1);
  const low=Math.max(0,minimum-padding),high=maximum+padding;
  const x=i=>64+i*526/Math.max(1,rows.length-1),y=value=>36+(high-Number(value))/(high-low)*180;
  const path=rows.map((r,i)=>`${i?'L':'M'}${x(i).toFixed(2)},${y(r.total_value).toFixed(2)}`).join(' ');
  const axis=value=>'₹'+Number(value).toLocaleString('en-IN',{notation:'compact',minimumFractionDigits:2,maximumFractionDigits:2});
  const ticks=[high,low+(high-low)*2/3,low+(high-low)/3,low].map(value=>`<line x1="64" x2="590" y1="${y(value)}" y2="${y(value)}" class="capital-gridline"/><text x="52" y="${y(value)+4}" text-anchor="end">${esc(axis(value))}</text>`).join('');
  const points=rows.map((r,i)=>{
    const cx=x(i),cy=y(r.total_value),tooltipX=Math.max(64,Math.min(422,cx-84)),tooltipY=Math.max(4,cy-66);
    return `<g class="capital-series-point" data-capital-point tabindex="${i===rows.length-1?'0':'-1'}" aria-label="${esc(day(r.session_date))}, ${money(r.total_value)}"><line x1="${cx}" x2="${cx}" y1="28" y2="220" class="capital-crosshair"/><circle cx="${cx}" cy="${cy}" r="15" class="capital-point-target"/><circle cx="${cx}" cy="${cy}" r="${i===rows.length-1?5:3}" class="capital-point"/><g class="capital-tooltip" transform="translate(${tooltipX},${tooltipY})"><rect width="168" height="52" rx="9"/><text x="12" y="19" class="capital-tooltip-date">${esc(day(r.session_date))}</text><text x="12" y="39" class="capital-tooltip-value">${money(r.total_value)}</text></g></g>`;
  }).join('');
  const lastDate=rows.at(-1).session_date;
  return `<section class="home-value-chart capital-chart capital-chart--${tone}">${header}<svg class="results-chart capital-curve" viewBox="0 0 640 258" role="img" aria-label="Overall portfolio value across ${closes} published daily closes"><defs><linearGradient id="capital-area-fill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="currentColor" stop-opacity=".22"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>${ticks}<path d="${path} L590,220 L64,220 Z" fill="url(#capital-area-fill)"/><line x1="64" x2="590" y1="${y(first)}" y2="${y(first)}" class="capital-baseline"/><path d="${path}" class="capital-line"/>${points}<text x="64" y="248">Start</text>${rows.length>2?`<text x="${x(Math.floor((rows.length-1)/2))}" y="248" text-anchor="middle">${esc(day(rows[Math.floor((rows.length-1)/2)].session_date).replace(/ \d{4}$/, ''))}</text>`:''}<text x="590" y="248" text-anchor="end">${esc(day(lastDate).replace(/ \d{4}$/, ''))}</text></svg><div class="capital-chart-key"><span><i></i>Portfolio value</span><span><i class="is-baseline"></i>Starting capital</span></div><p class="capital-chart-note">Daily published values · Scale adjusts to show changes. Hover a point or use arrow keys to inspect values.</p>${table}</section>`;
}

document.addEventListener('keydown',event=>{
  const point=event.target.closest?.('[data-capital-point]');
  if(!point||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const points=[...point.closest('svg').querySelectorAll('[data-capital-point]')],index=points.indexOf(point);
  const next=event.key==='Home'?0:event.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,index+(event.key==='ArrowLeft'?-1:1)));
  event.preventDefault();point.setAttribute('tabindex','-1');points[next].setAttribute('tabindex','0');points[next].focus();
});
