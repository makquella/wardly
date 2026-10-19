const sections=[...document.querySelectorAll('.scene')];
const escape=s=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const emphasis=/wardly|двадцять|twenty|bloodthorn|windows|нічого|nothing|темпову|tempo/i;
const ease=x=>1-Math.pow(1-Math.min(1,Math.max(0,x)),3);
window.renderAt=async t=>{
 const active=Math.max(0,timeline.findIndex(s=>t>=s.start&&t<s.end));
 const local=Math.max(0,t-timeline[active].start);
 sections.forEach((el,i)=>{el.style.visibility=i===active?'visible':'hidden';el.style.opacity=i===active?1:0;});
 const current=sections[active], decoding=[];
 current.querySelectorAll('[data-hero]').forEach(img=>{
  const frames=motion[img.dataset.hero];
  if(frames?.length){const n=Math.floor(t*20)%frames.length;if(img.dataset.frame!==String(n)){img.src=frames[n];img.dataset.frame=String(n);decoding.push(img.decode());}}
 });
 // Deterministic entrances: each element fades and rises after its delay.
 current.querySelectorAll('.enter').forEach(el=>{
  const d=parseFloat(getComputedStyle(el).getPropertyValue('--d'))||0, k=ease((local-d)/0.4);
  el.style.opacity=k; el.style.transform=`translateY(${(1-k)*36}px)`;
 });
 current.querySelectorAll('.cell').forEach(el=>{
  const i=parseFloat(getComputedStyle(el).getPropertyValue('--i'))||0, k=ease((local-0.15-i*0.06)/0.3);
  el.style.opacity=k; el.style.transform=`scale(${0.85+0.15*k})`;
 });
 const cue=captions.find(c=>t>=c.start&&t<c.end), box=document.querySelector('.captions');
 box.style.display=cue&&active!==6?'block':'none';
 box.innerHTML=cue?cue.words.map(w=>`<span class="${emphasis.test(w.w)?'emphasis':''}">${escape(w.w)}</span>`).join(' '):'';
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
