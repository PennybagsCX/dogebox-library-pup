// Dogebox Library pup — live search dropdown enhancement
let ctrl=null;
const q=document.getElementById("q");
if(q){
  q.addEventListener("input",async e=>{
    const term=e.target.value.trim();
    if(term.length<2)return;
    if(ctrl)ctrl.abort();
    ctrl=new AbortController();
    try{
      const r=await fetch("/api/search?q="+encodeURIComponent(term),{signal:ctrl.signal});
      const data=await r.json();
      const dd=document.getElementById("suggest");
      dd.innerHTML="";
      (data.movies||[]).slice(0,5).forEach(m=>{
        const o=document.createElement("option");
        o.value=m.title;
        o.textContent="🎬 "+m.title+" ("+(m.year||"?")+")";
        dd.appendChild(o);
      });
      (data.series||[]).slice(0,5).forEach(s=>{
        const o=document.createElement("option");
        o.value=s.title;
        o.textContent="📺 "+s.title+" ("+(s.year||"?")+")";
        dd.appendChild(o);
      });
    }catch(e){}
  });
}
