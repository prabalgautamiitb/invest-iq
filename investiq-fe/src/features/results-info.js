// Dates are provided by the server's reviewed exchange calendar.
export function contestTimeline(timing,{esc,stamp}) {
  if(!timing)return '';
  const milestones=[['Entry opens',timing.entry_opens_at],['Entry closes',timing.entry_closes_at],['Contest starts',timing.starts_at],['First market close',timing.first_session_closes_at],[(timing.state||timing.status)==='cancelled'?'Originally scheduled first results':'First results expected after',timing.first_results_available_at],['Contest ends',timing.ends_at]];
  return `<section class="panel" aria-label="Contest timeline" style="margin-bottom:20px"><h2>Contest timeline</h2><dl class="grid3">${milestones.map(([label,value])=>`<div><dt class="small">${label}</dt><dd style="margin:6px 0 16px"><strong>${value?esc(stamp(value)):'Schedule unavailable'}</strong></dd></div>`).join('')}</dl><p class="small">All times are in Asia/Kolkata (IST). Results use published end-of-day prices and appear after valuation completes. Missing prices can delay publication.</p></section>`;
}
