/* Background persists across route changes; no re-renders or API requests. */
(()=>{
const layer=document.createElement('div');layer.className='iq-ambient';layer.setAttribute('aria-hidden','true');
layer.innerHTML='<div class="ambient-light light-a"></div><div class="ambient-light light-b"></div><div class="ambient-light light-c"></div><div class="ambient-grid"></div><div class="ambient-beam"></div><div class="ambient-particles"></div>';
const particles=layer.querySelector('.ambient-particles');for(let i=0;i<12;i++){const dot=document.createElement('span');dot.style.setProperty('--x',((i*31+7)%97)+'%');dot.style.setProperty('--y',((i*23+15)%92)+'%');dot.style.setProperty('--size',i%3===0?'3px':'2px');dot.style.setProperty('--duration',(22+i%5*5)+'s');dot.style.setProperty('--delay',(-i*4)+'s');particles.append(dot)}
document.body.prepend(layer);
let enabled=true;try{enabled=localStorage.getItem('investiq-ambient-motion')!=='paused'}catch{}
const button=document.createElement('button');button.type='button';button.className='ambient-control';document.body.append(button);
function sync(){document.body.dataset.ambient=document.hidden?'hidden':enabled?'running':'paused';button.setAttribute('aria-pressed',String(enabled));button.setAttribute('aria-label',enabled?'Pause animated background':'Resume animated background');button.textContent=enabled?'Motion on':'Motion paused'}
button.addEventListener('click',()=>{enabled=!enabled;try{localStorage.setItem('investiq-ambient-motion',enabled?'running':'paused')}catch{}sync()});document.addEventListener('visibilitychange',sync);sync();
})();
