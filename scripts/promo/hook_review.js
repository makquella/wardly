// Narration time owns all motion (as in beta_motion.js): no CSS timers, and the
// dust and pings come from a fixed seed, so every render is the same.
const sections=[...document.querySelectorAll('.scene')];
const allWords=captions.flatMap(c=>c.words);
const clamp=x=>Math.min(1,Math.max(0,x)), ease=x=>1-Math.pow(1-clamp(x),3);
const back=x=>{x=clamp(x);const c=1.2;return 1+(c+1)*Math.pow(x-1,3)+c*Math.pow(x-1,2);};
const escape=s=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Seconds into a scene when its first word containing the fragment is spoken.
const wordAt=(scene,fragment,fallback=0.4)=>{
 const span=timeline[scene], f=fragment.toLowerCase();
 const word=allWords.find(w=>w.s>=span.start-0.01&&w.s<span.end&&w.w.toLowerCase().includes(f));
 return word?word.s-span.start:fallback;
};
sections.forEach((section,i)=>section.querySelectorAll('[data-on],[data-at]').forEach(el=>{
 const at=el.dataset.on?wordAt(i,el.dataset.on)-0.08:parseFloat(el.dataset.at)||0;
 el.dataset.t=String(Math.max(0,at+(parseFloat(el.dataset.delay)||0)));
 const base=getComputedStyle(el).transform;
 el.dataset.base=base==='none'?'':base;
}));
const length=i=>timeline[i].end-timeline[i].start;
const typeAt=wordAt(2,language==='uk'?'номер':'number',0.6)+0.05;
const pressAt=typeAt+0.12+0.045*10;
const checkAt=Math.max(pressAt+0.25,wordAt(2,language==='uk'?'розбирає':'reviews',1.6));
// Dust over the map, and gold pings on it.
let seed=7;
const random=()=>(seed=(seed*1664525+1013904223)>>>0)/4294967296;
const dust=document.querySelector('.dust');
const motes=Array.from({length:70},()=>{
 const el=document.createElement('i'), size=2+random()*5;
 el.style.width=el.style.height=`${size}px`;
 dust.appendChild(el);
 return {el,x:random()*1080,y:random()*1920,v:14+random()*36,p:random()*6.28};
});
const pings=[[150,250],[930,560],[110,1540],[960,1700],[820,190]].map(([x,y],i)=>{
 const el=document.createElement('b');el.textContent='!';el.style.left=`${x}px`;el.style.top=`${y}px`;
 dust.appendChild(el);return {el,p:i*1.3};
});
const plane=document.querySelector('.plane'), flash=document.querySelector('.flash');
// The desk slam in the hook's b-roll lands on «хто злив» / «who threw».
const slamAt=wordAt(0,language==='uk'?'хто':'who',2.4)-0.04;
const clipFrame=(img,local)=>{
 const frames=motion['clip:'+img.dataset.clip]; if(!frames?.length)return null;
 const from=parseFloat(img.dataset.from||0)-(img.dataset.clip==='rage'?slamAt:0);
 const n=Math.min(frames.length-1,Math.max(0,Math.floor((local+from)*24)));
 if(img.dataset.frame===String(n))return null;
 img.src=frames[n]; img.dataset.frame=String(n); return img.decode();
};
window.renderAt=async t=>{
 const active=Math.max(0,timeline.findIndex(s=>t>=s.start&&t<s.end));
 const local=Math.max(0,t-timeline[active].start), span=length(active);
 // The map drifts, and every cut kicks the camera in a little.
 const kick=0.035*(1-ease(local/0.5));
 plane.style.transform=`translate(-50%,-50%) rotateX(57deg) rotateZ(${-45+Math.sin(t*0.12)*4}deg) scale(${1.08+t*0.004+kick})`;
 motes.forEach(m=>{
  const y=((m.y-t*m.v)%1920+1920)%1920;
  m.el.style.transform=`translate(${m.x+Math.sin(t*0.6+m.p)*14}px,${y}px)`;
  m.el.style.opacity=String(0.18+0.3*(0.5+0.5*Math.sin(t*1.4+m.p)));
 });
 pings.forEach(g=>{const k=0.5+0.5*Math.sin(t*2.2+g.p);g.el.style.transform=`scale(${0.9+0.18*k})`;g.el.style.opacity=String(0.35+0.4*k);});
 const current=sections[active];
 sections.forEach((el,i)=>{el.style.visibility=i===active?'visible':'hidden';});
 // Leaving a scene: it fades and blurs out over its last 0.22 s.
 const out=active===sections.length-1?1:clamp((span-local)/0.22);
 let shake=0;
 const decoding=[];
 current.querySelectorAll('[data-hero]').forEach(img=>{
  const frames=motion[img.dataset.hero];
  if(frames?.length){const n=Math.floor(t*20)%frames.length;if(img.dataset.frame!==String(n)){img.src=frames[n];img.dataset.frame=String(n);decoding.push(img.decode());}}
 });
 current.querySelectorAll('[data-clip]').forEach(img=>{const d=clipFrame(img,local);if(d)decoding.push(d);});
 // Every cut punches in from a white flash; hits flash again.
 // Text punches in a little (it stays in the safe area); footage and map more.
 let flashAmount=active?0.5*(1-ease(local/0.14)):0, punch=0.012*(1-ease(local/0.35));
 let quake=0;
 current.querySelectorAll('.fx').forEach(el=>{
  const at=parseFloat(el.dataset.t)||0, x=local-at, k=ease(x/0.35);
  let move='', opacity=k, blur=0;
  switch(el.dataset.fx){
   case 'blur': move=`translateY(${(1-k)*26}px) scale(${0.96+0.04*k})`; blur=(1-k)*16; break;
   case 'rise': move=`translateY(${(1-k)*80}px)`; break;
   // Text inside a card starts 36 px in: a shorter slide keeps it in the safe area.
   case 'slide': move=`translateX(${(1-k)*-40}px)`; break;
   case 'pop': move=`scale(${0.55+0.45*back(x/0.45)})`; opacity=ease(x/0.2); break;
   case 'slam': {
    const s=ease(x/0.2); move=`scale(${1.1-0.1*s})`; opacity=ease(x/0.12);
    const after=x-0.2; if(after>0&&after<0.35)shake=Math.max(shake,9*(1-after/0.35));
    break;
   }
  }
  if(el.dataset.fx==='slam'&&x>0&&x<0.12)flashAmount=Math.max(flashAmount,0.35*(1-x/0.12));
  el.style.opacity=String(x<0?0:opacity);
  el.style.transform=`${move} ${el.dataset.base||''}`;
  el.style.filter=blur>0.2?`blur(${blur}px)`:'';
 });
 if(active===0&&current.classList.contains('with-footage')){
  const after=local-slamAt;
  if(after>0&&after<0.45)quake=26*(1-after/0.45);
  if(after>0&&after<0.1)flashAmount=Math.max(flashAmount,0.6*(1-after/0.1));
  // The slam knocks the chat away.
  current.querySelectorAll('.bubble').forEach((b,i)=>{
   if(after<=0)return;
   const k=ease(after/0.5), dir=i%2?1:-1;
   b.style.transform=`translate(${dir*k*260}px,${-k*120+k*k*260}px) rotate(${dir*k*24}deg) scale(${1-0.2*k})`;
   b.style.opacity=String(1-k);
  });
 }
 const footage=current.querySelector('.footage');
 if(footage){
  const q=quake?`translate(${Math.sin(local*97)*quake}px,${Math.cos(local*73)*quake*0.7}px)`:'';
  footage.style.transform=`${q} scale(${1+0.08*(1-ease(local/0.4))+local*0.01})`;
 }
 if(active===2&&current.classList.contains('keys')){
  // The finger lands on the key ~0.5 s in; then the keyboard dims under the form.
  current.querySelector('.footage').style.opacity=String(1-0.72*ease((local-0.55)/0.35));
 }
 if(active===1){
  const at=parseFloat(current.querySelector('.burst').dataset.t)||0, k=clamp((local-at)/0.6);
  const burst=current.querySelector('.burst');
  burst.style.opacity=String(local<at?0:(1-k)*0.9);
  burst.style.transform=`scale(${0.4+2.4*ease(k)})`;
  if(local>at&&local-at<0.12)flashAmount=Math.max(flashAmount,0.55*(1-(local-at)/0.12));
  if(local>at)current.querySelector('.promise').style.opacity=String(1-0.65*ease((local-at)/0.3));
 }
 if(active===2){
  const typed=current.querySelector('.typed'), text=typed.dataset.text;
  const n=Math.max(0,Math.min(text.length,Math.floor((local-typeAt)/0.045)));
  typed.textContent=text.slice(0,n);
  typed.style.display=n?'inline':'none';
  current.querySelector('.placeholder').style.display=n?'none':'inline';
  current.querySelector('.caret').style.opacity=String(Math.floor(local*3)%2?0.2:1);
  const press=local-pressAt;
  current.querySelector('.button').style.transform=`scale(${press>0&&press<0.14?0.92:1})`;
  current.querySelector('.status').style.opacity=String(press>0?ease(press/0.2):0);
  current.querySelector('.spin').style.transform=`rotate(${local*540}deg)`;
  current.querySelector('.checks').style.opacity=String(press>0?ease(press/0.25):0);
  current.querySelector('.checks').style.transform=`translateY(${press>0?(1-ease(press/0.3))*40:40}px)`;
  const steps=[...current.querySelectorAll('.check')], end=span-0.35;
  const progress=clamp((local-checkAt)/Math.max(0.5,end-checkAt));
  current.querySelector('.bar i').style.width=`${progress*100}%`;
  steps.forEach((step,i)=>step.classList.toggle('done',progress>=(i+1)/steps.length-0.001));
 }
 if(active===3){
  const count=current.querySelector('.count'), to=Number(count.dataset.to), k=ease((local-0.15)/1.1);
  const value=Math.round(to*k);
  count.textContent=String(value);
  current.querySelector('.arc').style.strokeDashoffset=String(540.35*(1-value/100));
  const grade=current.querySelector('.grade'), g=local-1.25;
  grade.style.opacity=String(g>0?ease(g/0.15):0);
  grade.style.transform=`scale(${g>0?0.5+0.5*back(g/0.35):0.5})`;
 }
 if(active===4){
  const k=ease(local/0.5);
  current.querySelector('.example-hero').style.transform=`translateY(${(1-k)*70}px) scale(${1+local*0.012})`;
  current.querySelector('.example-hero').style.opacity=String(k);
  const finding=current.querySelector('.finding'), f=local-(parseFloat(finding.dataset.t)||0);
  finding.style.borderColor=f>0&&Math.floor(f*6)%2===0&&f<0.7?'#ffc94d':'';
 }
 if(active===5){
  current.querySelector('.monitor img').style.transform=`scale(${1.05+local*0.025})`;
 }
 if(active===6){
  const at=wordAt(6,language==='uk'?'репорт':'report',1.2)+0.1;
  current.querySelector('.strike').style.transform=`scaleX(${ease((local-at)/0.3)})`;
  current.querySelector('.stamp').style.transform+=' rotate(-6deg)';
 }
 if(active===7){
  const pulse=0.5+0.5*Math.sin(local*5);
  current.querySelector('.address').style.boxShadow=`0 20px ${50+30*pulse}px #f05560${pulse>0.5?'88':'55'}`;
 }
 const dx=shake?Math.sin(local*95)*shake:0, dy=shake?Math.cos(local*71)*shake*0.6:0;
 current.style.opacity=String(out);
 current.style.filter=out<1?`blur(${(1-out)*10}px)`:'';
 current.style.transform=`translate(${dx}px,${dy}px) scale(${1+punch-(1-out)*0.03})`;
 flash.style.opacity=String(Math.min(0.7,flashAmount));
 // Captions: the whole phrase, the word being spoken in gold.
 const cue=captions.find(c=>t>=c.start&&t<c.end), box=document.querySelector('.captions');
 box.style.display=cue?'block':'none';
 box.innerHTML=cue?cue.words.map((w,i)=>{
  const next=cue.words[i+1]?.s??cue.end;
  return `<span class="${t>=w.s&&t<next?'now':''}">${escape(w.w)}</span>`;
 }).join(' '):'';
 await Promise.all(decoding);
};
window.layoutErrors=()=>{
 const visible=el=>{for(let x=el;x;x=x.parentElement){const s=getComputedStyle(x);if(s.visibility==='hidden'||s.display==='none'||Number(s.opacity)===0)return false;}return true;};
 const items=[...document.querySelectorAll('[data-safe]')].filter(visible), errors=[];
 for(const el of items){const r=el.getBoundingClientRect();if(r.left<78||r.top<196||r.right>910||r.bottom>1450)errors.push({text:el.textContent,box:[r.left,r.top,r.right,r.bottom]});if(el.scrollWidth>el.clientWidth+2||el.scrollHeight>el.clientHeight+2)errors.push({text:el.textContent,overflow:true});}
 items.forEach((a,i)=>items.slice(i+1).forEach(b=>{if(a.contains(b)||b.contains(a))return;const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();if(Math.min(x.right,y.right)-Math.max(x.left,y.left)>8&&Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top)>8)errors.push({overlap:[a.textContent,b.textContent]});}));
 const box=document.querySelector('.captions');if(visible(box)&&box.clientHeight>145)errors.push({captions:'more than two lines'});
 if(document.querySelectorAll('[data-brand]').length!==1)errors.push({branding:'duplicate logo'});
 return errors;
};
window.renderAt(0);
