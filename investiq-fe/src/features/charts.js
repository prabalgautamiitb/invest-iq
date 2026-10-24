// Presentation only. Monetary calculations and rankings remain server-owned.
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const numeric = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
const pct = value => Number(value).toLocaleString('en-IN', {maximumFractionDigits:2}) + '%';
const colors = ['#56dfb2','#85b9ff','#d0adff','#ffd28c','#fa9db6','#7dd9e8'];

export function returnChart(series) {
  const rows = series.filter(s => numeric(s.return_pct) && numeric(s.benchmark_return_pct))
    .slice().sort((a,b) => a.session_date.localeCompare(b.session_date));
  if (!rows.length) return '<section class="panel visual-panel"><h2>Performance over time</h2><p class="chart-empty">Your chart starts after the first published valuation.</p></section>';
  const values = rows.flatMap(r => [Number(r.return_pct),Number(r.benchmark_return_pct)]);
  const lo = Math.min(0,...values), hi = Math.max(0,...values), pad = Math.max((hi-lo)*.15,.1);
  const bottom = lo-pad, top = hi+pad;
  const x = i => rows.length === 1 ? 338 : 66+i*544/(rows.length-1);
  const y = v => 30+(top-Number(v))/(top-bottom)*174;
  const lines = ['return_pct','benchmark_return_pct'].map((field,k) => `<polyline points="${rows.map((r,i)=>`${x(i)},${y(r[field])}`).join(' ')}" fill="none" stroke="${colors[k]}" stroke-width="3" ${k?'stroke-dasharray="7 5"':''}/>${rows.map((r,i)=>`<circle cx="${x(i)}" cy="${y(r[field])}" r="4" fill="${colors[k]}"><title>${escape(r.session_date)} · ${k?'Benchmark':'Portfolio'} ${pct(r[field])}</title></circle>`).join('')}`).join('');
  const ticks = [top,(top+bottom)/2,bottom].map(v => `<line x1="66" x2="610" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" opacity=".12"/><text x="54" y="${y(v)+4}" text-anchor="end">${pct(v)}</text>`).join('');
  const labels = rows.length===1 ? `<text x="338" y="235" text-anchor="middle">${escape(rows[0].session_date)}</text>` : `<text x="66" y="235">${escape(rows[0].session_date)}</text><text x="610" y="235" text-anchor="end">${escape(rows.at(-1).session_date)}</text>`;
  return `<section class="panel visual-panel"><div class="row"><h2>Performance over time</h2><span class="small">Daily close · return %</span></div><div class="chart-legend"><span><i style="background:${colors[0]}"></i>Your portfolio</span><span><i style="background:${colors[1]}"></i>Benchmark (dashed)</span></div><svg class="results-chart" viewBox="0 0 640 254" role="img" aria-label="Portfolio and benchmark returns across ${rows.length} published daily snapshots">${ticks}<line x1="66" x2="610" y1="${y(0)}" y2="${y(0)}" stroke="currentColor" opacity=".3"/>${lines}${labels}</svg><p class="small">${rows.length===1?'One published close so far. More points appear after each daily valuation.':'Each point is a recorded daily close. Exact values are available in Daily snapshots.'}</p></section>`;
}

export function comparisonBars(title, items, note='', unit='%') {
  const rows = items.filter(r => numeric(r.value));
  const extent = Math.max(...rows.map(r=>Math.abs(Number(r.value))),.01);
  return `<section class="panel visual-panel" aria-label="${escape(title)}"><h2>${escape(title)}</h2>${rows.length?`<div class="comparison-bars">${rows.map(r=>{const n=Number(r.value);return `<div class="comparison-row"><span class="bar-label">${escape(r.label)}</span><div class="bar-track"><span class="bar-zero"></span><span class="bar-value ${n<0?'bar-negative':''}" style="left:${n<0?50-Math.abs(n)/extent*50:50}%;width:${Math.abs(n)/extent*50}%"></span></div><strong>${escape(Number(n).toLocaleString('en-IN',{maximumFractionDigits:2})+unit)}</strong></div>`;}).join('')}</div>`:'<p class="chart-empty">Published results will appear here after valuation.</p>'}${note?`<p class="small">${escape(note)}</p>`:''}</section>`;
}

export function allocationChart(positions, cash, total) {
  if (!numeric(total) || Number(total)<=0) return '';
  const rows = [...positions.map(p=>({label:p.symbol,value:Number(p.value)})),{label:'Cash',value:Number(cash)}].filter(r=>Number.isFinite(r.value)&&r.value>0);
  return `<section class="panel visual-panel" aria-label="Portfolio allocation"><h2>Portfolio allocation</h2><p class="small">Share of the current virtual portfolio value.</p><div class="allocation-strip" role="img" aria-label="Holdings and cash as a percentage of portfolio value">${rows.map((r,i)=>`<span title="${escape(r.label)} ${pct(r.value/Number(total)*100)}" style="width:${r.value/Number(total)*100}%;background:${colors[i%colors.length]}"></span>`).join('')}</div><div class="allocation-key">${rows.map((r,i)=>`<div><span><i style="background:${colors[i%colors.length]}"></i>${escape(r.label)}</span><strong>${pct(r.value/Number(total)*100)}</strong></div>`).join('')}</div></section>`;
}


export function portfolioValueChart(series) {
  const rows=series.filter(s=>numeric(s.total_value)).slice().sort((a,b)=>a.session_date.localeCompare(b.session_date));
  if(!rows.length)return '<section class="panel visual-panel"><h2>Portfolio value over time</h2><p class="chart-empty">Your value chart starts after the first published daily valuation. Confirm a portfolio before entry closes to take part.</p></section>';
  const money=value=>'₹'+Number(value).toLocaleString('en-IN',{maximumFractionDigits:2});
  const compact=value=>'₹'+Number(value).toLocaleString('en-IN',{notation:'compact',maximumFractionDigits:2});
  const values=rows.map(r=>Number(r.total_value)),lo=Math.min(...values),hi=Math.max(...values);
  const pad=Math.max((hi-lo)*.15,Math.abs(hi)*.002,1),bottom=Math.max(0,lo-pad),top=hi+pad;
  const x=i=>rows.length===1?350:88+i*518/(rows.length-1);
  const y=value=>28+(top-Number(value))/(top-bottom)*176;
  const points=rows.map((r,i)=>`${x(i)},${y(r.total_value)}`).join(' ');
  const ticks=[top,(top+bottom)/2,bottom].map(v=>`<line x1="88" x2="606" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" opacity=".12"/><text x="78" y="${y(v)+4}" text-anchor="end">${escape(compact(v))}</text>`).join('');
  return `<section class="panel visual-panel home-value-chart"><div class="row"><h2>Portfolio value over time</h2><span class="small">Virtual INR · daily close</span></div><svg class="results-chart" viewBox="0 0 640 254" role="img" aria-label="Portfolio value across ${rows.length} published daily snapshots">${ticks}${rows.length>1?`<polygon points="${x(0)},204 ${points} ${x(rows.length-1)},204" fill="#56dfb2" opacity=".09"/>`:''}<polyline points="${points}" fill="none" stroke="#56dfb2" stroke-width="3"/>${rows.map((r,i)=>`<circle cx="${x(i)}" cy="${y(r.total_value)}" r="4" fill="#56dfb2"><title>${escape(r.session_date)} · ${escape(money(r.total_value))}</title></circle>`).join('')}<text x="${x(0)}" y="235" ${rows.length===1?'text-anchor="middle"':''}>${escape(rows[0].session_date)}</text>${rows.length>1?`<text x="606" y="235" text-anchor="end">${escape(rows.at(-1).session_date)}</text>`:''}</svg><p class="small">${rows.length===1?'One published close so far. More points appear after each daily valuation.':'Each point shows holdings plus residual cash, with the simulated fee included.'} The value axis is zoomed to show changes.</p><details class="page-details"><summary>Exact portfolio values</summary><div class="tablewrap"><table><thead><tr><th>Daily close</th><th>Virtual value</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${escape(r.session_date)}</td><td>${escape(money(r.total_value))}</td></tr>`).join('')}</tbody></table></div></details></section>`;
}
