// Deterministic animation engine: window.__render(t) sets every animated property from t (seconds).
const clamp=(x,a=0,b=1)=>Math.min(b,Math.max(a,x));
const ease={out:p=>1-Math.pow(1-p,3),inout:p=>p<.5?4*p*p*p:1-Math.pow(-2*p+2,3)/2,
  back:p=>{const c1=1.70158,c3=c1+1;return 1+c3*Math.pow(p-1,3)+c1*Math.pow(p-1,2)},lin:p=>p};
function fmt(v,f){switch(f){case'pct1':return(v*100).toFixed(1)+'%';case'pct0':return Math.round(v*100)+'%';
  case'ms':return Math.round(v)+' ms';case'ms1':return v.toFixed(1)+' ms';case'dec3':return v.toFixed(3);case'dec2':return v.toFixed(2);default:return Math.round(v).toString()}}
let SCENE=null,ELS=[];
function mountScene(id){
  SCENE=SCENES.find(s=>s.id===id); if(!SCENE)throw new Error('no scene '+id);
  document.getElementById('content').innerHTML=SCENE.html();
  ELS=[...document.querySelectorAll('[data-t],[data-kf],[data-out]')];
  ELS.forEach(el=>{
    if(el.dataset.fx&&el.dataset.fx.includes('draw')){const L=el.getTotalLength();el.style.strokeDasharray=L;el.dataset.len=L;}
    if(el.dataset.fx&&el.dataset.fx.includes('type')){el.dataset.text=el.dataset.text||el.textContent;}
  });
  window.__duration=SCENE.dur; window.__render(0);
}
window.__render=function(t){
  for(const el of ELS){
    const fx=(el.dataset.fx||'fade up').split(' ');
    let op=1,tr='';
    if(el.dataset.t!==undefined){
      const st=+el.dataset.t,d=+(el.dataset.d||0.7);
      const raw=clamp((t-st)/d), p=(fx.includes('pop')?ease.back:ease.out)(raw), pe=ease.out(raw);
      for(const f of fx){
        if(f==='fade')op*=pe;
        else if(f==='up')tr+=` translateY(${(1-p)*40}px)`;
        else if(f==='down')tr+=` translateY(${-(1-p)*40}px)`;
        else if(f==='left')tr+=` translateX(${-(1-p)*70}px)`;
        else if(f==='right')tr+=` translateX(${(1-p)*70}px)`;
        else if(f==='scale'||f==='pop'){tr+=` scale(${0.8+0.2*p})`;op*=pe;}
        else if(f==='growx'){tr+=` scaleX(${pe})`;el.style.transformOrigin='left center';}
        else if(f==='growy'){tr+=` scaleY(${pe})`;el.style.transformOrigin='center bottom';}
        else if(f==='draw'){el.style.strokeDashoffset=(+el.dataset.len)*(1-pe);}
        else if(f==='type'){const s=el.dataset.text;el.textContent=s.slice(0,Math.round(s.length*clamp((t-st)/d)));}
        else if(f==='count'){const a=+(el.dataset.from||0),b=+el.dataset.to;el.textContent=fmt(a+(b-a)*pe,el.dataset.fmt);}
        else if(f==='width'){el.style.width=(+el.dataset.w*pe)+'px';}
      }
    }
    if(el.dataset.out!==undefined)op*=1-ease.out(clamp((t-(+el.dataset.out))/0.45));
    if(el.dataset.kf){ // [[t,x,y],...] absolute position keyframes, eased per segment
      const kf=JSON.parse(el.dataset.kf);let x=kf[0][1],y=kf[0][2];
      for(let i=0;i<kf.length-1;i++){const[a,x0,y0]=kf[i],[b,x1,y1]=kf[i+1];
        if(t>=a&&t<=b){const p=ease.inout((t-a)/(b-a||1));x=x0+(x1-x0)*p;y=y0+(y1-y0)*p;break;} if(t>b){x=x1;y=y1;}}
      el.style.left=x+'px';el.style.top=y+'px';
    }
    el.style.opacity=op; if(tr)el.style.transform=tr;
  }
  const D=SCENE.dur, f=document.getElementById('fade');
  f.style.opacity=Math.max(1-t/0.45,(t-(D-0.45))/0.45,0);
  document.getElementById('bg').style.transform=`translate(${Math.sin(t/6)*30}px,${Math.cos(t/7)*20}px)`;
};
