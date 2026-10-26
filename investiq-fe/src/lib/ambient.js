/* Static decorative background persists across route changes. */
(()=>{
const layer=document.createElement('div');layer.className='iq-ambient';layer.setAttribute('aria-hidden','true');
layer.innerHTML='<div class="ambient-light light-a"></div><div class="ambient-light light-b"></div><div class="ambient-light light-c"></div><div class="ambient-grid"></div><div class="ambient-beam"></div><div class="ambient-particles"></div>';
const particles=layer.querySelector('.ambient-particles');for(let i=0;i<12;i++){const dot=document.createElement('span');dot.style.setProperty('--x',((i*31+7)%97)+'%');dot.style.setProperty('--y',((i*23+15)%92)+'%');dot.style.setProperty('--size',i%3===0?'3px':'2px');particles.append(dot)}
document.body.prepend(layer);
})();
