import { marketApi } from '../api/market.js';

export const newsPlaceholder = (variant = 'list') => `<section class="panel market-news market-news--${variant}" data-market-news="${variant}" aria-label="${variant === 'carousel' ? 'Market news highlights' : 'Top five market news'}"><h2>Market brief</h2><p class="small" role="status">Loading market headlines…</p></section>`;

// Updates only its own DOM: draft inputs, chart selections and scroll stay intact.
export function createMarketNews({ root, esc }) {
  let data = null, error = false, loading = false, lastRead = 0, index = 0, paused = false;
  let rotation = null, polling = null;
  const hosts = () => [...root.querySelectorAll('[data-market-news]')];
  const articles = () => (data?.items || []).filter(item => {
    try { return new URL(item.url).protocol === 'https:'; } catch { return false; }
  }).slice(0, 5);
  const date = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
  }) + ' IST' : 'Time unavailable';
  const metadata = item => `<span>${esc(item.source)}</span><span aria-hidden="true">·</span><time datetime="${esc(item.published_at)}">${esc(date(item.published_at))}</time>`;
  function article(item, number, compact = false) {
    return `<article class="news-article ${compact ? 'news-slide' : ''}"><span class="news-number" aria-hidden="true">${String(number + 1).padStart(2, '0')}</span><div><div class="news-meta">${metadata(item)}</div><h3><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}<span class="news-external" aria-hidden="true"> ↗</span><span class="sr-only"> (opens original article in a new tab)</span></a></h3>${compact ? `<a class="news-read" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">Read the original story ↗</a>` : ''}</div></article>`;
  }
  function paint(host, animate = false) {
    const outgoing = animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? host.querySelector('.news-slide:not(.news-slide-outgoing)')?.cloneNode(true) : null;
    const items = articles(), carousel = host.dataset.marketNews === 'carousel';
    index %= items.length || 1;
    const updated = data?.updated_at ? `${data.status === 'stale' ? 'Saved headlines · ' : ''}Updated ${date(data.updated_at)}` : '';
    host.innerHTML = `<header class="market-news-header"><div><span class="eyebrow">THE MARKET BRIEF</span><h2>${carousel ? 'In the headlines' : 'Market news'}</h2></div><span class="news-edition">${items.length ? 'INDIA' : 'NEWS'}</span></header>${items.length ? `${carousel ? `<div class="news-slide-content" aria-live="off">${article(items[index], index, true)}</div><div class="news-controls"><div class="news-dots" role="group" aria-label="Choose headline">${items.map((_, i) => `<button type="button" data-news-index="${i}" aria-label="Show headline ${i + 1}" aria-pressed="${i === index}"><span></span></button>`).join('')}</div><div class="news-playback"><span class="news-count">${index + 1} / ${items.length}</span><button type="button" data-news-pause aria-label="${paused ? 'Resume' : 'Pause'} headline rotation">${paused ? '▶' : 'Ⅱ'}</button></div></div>` : `<p class="small news-intro">Five latest market stories, directly from the publisher.</p><div class="news-list">${items.map((item, i) => article(item, i)).join('')}</div>`}<footer class="news-footer"><span>${esc(updated)}</span><span>${esc(data?.schedule?.startsWith('Daily') ? data.schedule : 'Hourly during market hours')}</span></footer>` : `<div class="news-empty"><span aria-hidden="true">↗</span><p>${error ? 'Market news is temporarily unavailable.' : data?.status === 'disabled' ? 'Market news is currently disabled.' : 'Headlines will appear after the next news refresh.'}</p><p class="small">${data?.next_refresh_at ? 'Next scheduled update: ' + esc(date(data.next_refresh_at)) : esc(data?.schedule || 'Updated hourly during NSE market hours.')}</p></div>`}`;
    const incoming = host.querySelector('.news-slide');
    if (outgoing && incoming) {
      outgoing.classList.add('news-slide-outgoing');
      outgoing.setAttribute('aria-hidden', 'true');
      outgoing.inert = true;
      incoming.parentElement.append(outgoing);
      const timing = { duration: 450, easing: 'ease-in-out' };
      incoming.animate([{ opacity: 0 }, { opacity: 1 }], timing);
      const fadeOut = outgoing.animate([{ opacity: 1 }, { opacity: 0 }], { ...timing, fill: 'forwards' });
      fadeOut.onfinish = () => outgoing.remove();
    }
  }
  function paintAll() { hosts().forEach(paint); }
  async function read() {
    if (loading || !hosts().length) return;
    loading = true;
    try {
      data = await marketApi.news(); error = false; lastRead = Date.now();
    } catch {
      error = true; lastRead = Date.now();
    } finally {
      loading = false; paintAll();
    }
  }
  function rotate() {
    if (paused || document.hidden || articles().length < 2) return;
    const host = root.querySelector('[data-market-news="carousel"]');
    if (!host || host.matches(':hover') || host.contains(document.activeElement)) return;
    index = (index + 1) % articles().length;
    paint(host, true);
  }
  function sync() {
    clearInterval(rotation); clearInterval(polling);
    rotation = polling = null;
    if (!hosts().length) return;
    if (data || error) paintAll();
    if (Date.now() - lastRead >= 60000) read();
    rotation = setInterval(rotate, 3000);
    polling = setInterval(() => { if (!document.hidden && Date.now() - lastRead >= 60000) read(); }, 60000);
  }
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-news-index], [data-news-pause]');
    if (!button) return;
    const previousIndex = index;
    if (button.hasAttribute('data-news-pause')) paused = !paused;
    else index = Number(button.dataset.newsIndex);
    const selector = button.hasAttribute('data-news-pause') ? '[data-news-pause]' : `[data-news-index="${index}"]`;
    const host = button.closest('[data-market-news]');
    paint(host, index !== previousIndex);
    host.querySelector(selector)?.focus();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && hosts().length && Date.now() - lastRead >= 60000) read();
  });
  document.addEventListener('investiq:render', sync);
  return { sync };
}
