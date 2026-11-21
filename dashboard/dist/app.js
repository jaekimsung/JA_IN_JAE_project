"use strict";
const el = id => document.getElementById(id);
const esc = value => String(value ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = (v,d=0) => Number.isFinite(v) ? v.toLocaleString("ko-KR",{maximumFractionDigits:d}) : "—";
const pct = v => Number.isFinite(v) ? num(100*v,1)+"%" : "—";
const names = {B0:"B0 Expert",B1:"B1 BC",B2:"B2 SAC",B3:"B3 RLPD"};
const nameOf = r => (names[r.method] || r.method) + (r.seed == null ? "" : " · seed "+r.seed);
const empty = text => '<p class="empty">'+esc(text)+'</p>';
const table = (headers,rows) => '<div class="scroll"><table><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join("")+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+x+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>';
function options(id,pairs,fallback) {
  const node=el(id), old=node.value;
  node.replaceChildren(...pairs.map(([v,k])=>new Option(k,v)));
  node.value=pairs.some(([v])=>v===old)?old:(fallback ?? pairs[0]?.[0] ?? "");
}
let data, groups, busy=false;
const label=e=>nameOf(e)+" · "+e.panel+" · "+Object.keys(e.scenarios).sort().join("/")+(e.step!=null?" · "+num(e.step)+" 전이":"");
const scope = e=>[e.panel,e.cohort,e.aggregate.metric_version].join("|");
function comparison(){
  const summaryOpen=el("comparison").querySelector("details")?.open;
  const group=groups.get(el("cohort").value)||[];
  const chosen=group.filter(e=>e.representative).sort((a,b)=>String(a.method).localeCompare(b.method)||a.seed-b.seed);
  const rows=chosen.map(e=>{
    const a=e.aggregate, r=a.compliant_completion_rate;
    const bar=Number.isFinite(r)?'<span class="bar"><i style="width:'+Math.min(100,Math.max(0,r*100))+'%"></i></span>':"";
    return ['<button class="method" data-record="'+esc(e.id)+'" title="'+esc(e.id)+'">'+esc(nameOf(e))+'</button>',num(a.n_valid)+" / "+num(a.n_planned),bar+pct(r),pct(a.collision_rate),num(a.n_red_episode),num(a.n_yield_violation),num(a.stops?.standstill_s_mean,1),num(a.mean_elapsed_completed,1)];
  });
  const covered=new Set(chosen.map(e=>e.method));
  const absent=Object.keys(data.spec.methods).filter(m=>!covered.has(m)).map(m=>names[m]||m);
  el("comparison").innerHTML=(rows.length?table(["모델 / 학습 seed","유효 / 계획","규정 준수 완주율","충돌률","적색 위반 에피소드","양보 위반 에피소드","평균 정차 (s)","완주 평균 시간 (s)"],rows):empty("이 케이스 구성에 저장된 대표 모델 평가가 없습니다."))+'<p class="foot">모델을 선택하면 해당 평가의 주행 기록으로 이동합니다.'+(absent.length?' 이 조건의 대표 평가 없음 · '+esc(absent.join(", ")):"")+'</p>';
  const methods=[...new Set(chosen.map(e=>e.method))];
  const stat=values=>{
    if(!values.length)return "—";
    const mean=values.reduce((a,b)=>a+b,0)/values.length;
    if(values.length===1)return pct(mean)+" (n=1)";
    const sd=Math.sqrt(values.reduce((sum,v)=>sum+(v-mean)**2,0)/(values.length-1));
    return pct(mean)+" ± "+num(100*sd,1)+"%p";
  };
  if(chosen.length){
    const summaryRows=methods.map(method=>{
      const entries=chosen.filter(e=>e.method===method);
      const seeds=entries.map(e=>e.seed);
      const unique=seeds.every(s=>s!=null)&&new Set(seeds).size===seeds.length;
      const result=k=>unique?stat(entries.map(e=>e.aggregate[k]).filter(Number.isFinite)):"—";
      return [esc(names[method]||method),esc(seeds.map(s=>s??"—").join(", ")),result("compliant_completion_rate"),result("collision_rate")];
    });
    el("comparison").insertAdjacentHTML("beforeend",'<details '+(summaryOpen?'open':'')+'><summary>학습 seed 간 평균과 변동</summary>'+table(["모델","평가된 seed","준수 완주율 · 평균 ± 표준편차","충돌률 · 평균 ± 표준편차"],summaryRows)+'<p class="foot">각 seed에 같은 가중치를 적용합니다. 표준편차는 seed가 2개 이상일 때의 표본 표준편차입니다. 동일 seed의 복수 평가가 있으면 평균을 보류합니다.</p></details>');
  }
}
function metricList(r){
  if(!r)return [];
  const dev=data.evaluations.some(e=>e.run===r.id && e.step!=null);
  const bc=r.method==="B1";
  const keys=new Set(r.curve.flatMap(p=>bc?[...Object.keys(p.training||{}),...Object.keys(p.validation||{})]:Object.keys(p.metrics||{})));
  return [...(dev?[["dev","Dev 완주율과 충돌률"]]:[]),...Array.from(keys,k=>[k,k])];
}
function training(reset=false){
  const r=data.runs.find(o=>o.id===el("run").value);
  const metrics=metricList(r);
  if(reset)options("metric",metrics);
  if(!r){el("chart").innerHTML=empty("저장된 학습 기록이 없습니다.");el("runinfo").textContent="";el("save").disabled=true;return;}
  el("metadata").textContent=JSON.stringify({설정:r.config,최근상태:r.status,학습완료:r.complete,최저검증손실:r.best,샘플효율:r.efficiency},null,2);
  const key=el("metric").value, bc=r.method==="B1", dev=key==="dev";
  const completed=Object.keys(r.complete).length>0;
  const last=r.curve.at(-1)||{}, xkey=bc?"updates":"transitions",unit=bc?"업데이트":"전이";
  el("curveName").textContent=nameOf(r);
  el("runinfo").textContent=[completed?"완료":(r.status.phase||"기록 수집 중"),num(r.complete[xkey]??r.status[xkey]??last[xkey])+" "+unit,r.id].join(" · ");
  let series;
  if(dev){
    const devs=data.evaluations.filter(e=>e.run===r.id&&e.step!=null).sort((a,b)=>a.step-b.step);
    series=[["규정 준수 완주율","compliant_completion_rate"],["충돌률","collision_rate"]].map(([name,k])=>({name,points:devs.map(e=>[e.step,Number.isFinite(e.aggregate[k])?100*e.aggregate[k]:null])}));
  }else{
    const sources=bc?[["학습","training"],["검증","validation"]]:[[key,"metrics"]];
    series=sources.map(([name,source])=>({name,points:r.curve.map(p=>[p[xkey],p[source]?.[key]])}));
  }
  drawChart(series,dev?"비율 (%)":key,unit,dev);
  const eff=r.efficiency;
  el("chartNote").textContent=dev&&eff.target_transition!=null?"목표 최초 도달 "+num(eff.target_transition)+" 전이 · 연속 달성 확인 "+num(eff.confirmation_transition)+" 전이":bc&&r.best.loss!=null?"최저 검증 loss "+num(r.best.loss,7)+" · 선택 체크포인트 "+r.best.path:"학습 지표는 기록 구간의 평균입니다. 업데이트 전 구간은 공란으로 표시합니다.";
}
function drawChart(series,yLabel,xLabel,rate){
  const valid=series.flatMap(s=>s.points).filter(([x,y])=>Number.isFinite(x)&&Number.isFinite(y));
  el("save").disabled=!valid.length;
  if(!valid.length){el("chart").innerHTML=empty("선택한 지표에 기록된 값이 없습니다.");return;}
  const xs=series.flatMap(s=>s.points.map(p=>p[0])).filter(Number.isFinite);
  const ys=valid.map(p=>p[1]);
  const xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=rate?0:Math.min(...ys), ymax=rate?100:Math.max(...ys);
  const X=x=>75+(x-xmin)/(xmax-xmin||1)*810;
  const Y=y=>230-(y-ymin)/(ymax-ymin||1)*185;
  const colors=["#136987","#b85b19"];
  let svg='<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="'+esc(yLabel)+'" viewBox="0 0 920 290" font-family="sans-serif" font-size="13" fill="#375467"><rect width="920" height="290" fill="white"/><text x="10" y="23">'+esc(yLabel)+'</text>';
  for(let i=0;i<=4;i++){
    const x=75+i*810/4,y=230-i*185/4;
    svg+='<path stroke="#d4e0e5" d="M75 '+y+'H885"/><text text-anchor="end" x="65" y="'+(y+4)+'">'+num(ymin+i*(ymax-ymin)/4,5)+'</text><text text-anchor="middle" x="'+x+'" y="252">'+num(xmin+i*(xmax-xmin)/4)+'</text>';
  }
  svg+='<text x="885" y="280" text-anchor="end">'+esc(xLabel)+'</text>';
  series.forEach((s,i)=>{
    const color=colors[i%colors.length];let path="",move=true,dots="";
    for(const [x,y] of s.points){
      if(!Number.isFinite(y)||!Number.isFinite(x)){move=true;continue;}
      path+=(move?"M":"L")+X(x)+" "+Y(y)+" ";move=false;
      dots+='<circle cx="'+X(x)+'" cy="'+Y(y)+'" r="3.4" fill="'+color+'"><title>'+esc(s.name)+" · "+num(x)+" "+esc(xLabel)+" · "+num(y,7)+(rate?"%":"")+'</title></circle>';
    }
    svg+='<path d="'+path+'" stroke="'+color+'" stroke-width="2.7" fill="none"/>'+dots+'<text x="'+(690+i*110)+'" y="23" fill="'+color+'">● '+esc(s.name)+'</text>';
  });
  el("chart").innerHTML=svg+"</svg>";
}
function cases(reset=true){
  const e=data.evaluations.find(o=>o.id===el("evaluation").value);
  if(!e){el("scenario").innerHTML=empty("평가 기록이 없습니다.");el("episodes").innerHTML="";return;}
  el("aggregate").textContent=JSON.stringify(e.aggregate,null,2);
  const codes=Object.keys(e.scenarios).sort();
  if(reset)options("filter",["전체",...codes].map(k=>[k,k]));
  const rows=codes.map(code=>{
    const sample=e.cases.filter(c=>c.scenario_id===code), valid=sample.filter(c=>c.attempt_valid);
    const rate=k=>valid.length?pct(valid.filter(c=>c[k]===true).length/valid.length):"—";
    return [esc(code),num(valid.length)+" / "+num(sample.length),rate("compliant_completion"),rate("ever_AV_collision")];
  });
  const a=e.aggregate, lane=a.situations?.lane_drop;
  el("scenario").innerHTML='<div class="pair">'+table(["시나리오","유효 / 기록","규정 준수 완주율","충돌률"],rows)+table(["종료 원인","에피소드 수"],Object.entries(a.primary_end_reason_counts||{}).map(([k,v])=>[esc(k),num(v)]))+'</div><p class="foot">'+(lane?.n_required?'필수 차선 변경 · 평균 변경 위치 '+num(lane.position_m_mean,2)+' m · 평균 대기 '+num(lane.wait_s_mean,2)+' s · ':"")+'출처 · runs/'+esc(e.id)+'</p>';
  const list=e.cases.filter(c=>(el("filter").value==="전체"||el("filter").value===c.scenario_id)&&(!el("fail").checked||!c.attempt_valid||!c.compliant_completion));
  el("episodes").innerHTML=list.length?table(["케이스","시나리오","수요 배율","유효","종료 원인","소요 (s)","변경 위치 (m)","차선 대기 (s)"],list.map(c=>[num(c.case_index),esc(c.scenario_id),num(c.demand_multiplier,2),c.attempt_valid?"유효":"무효",esc(c.primary_end_reason),num(c.elapsed_s,1),num(c.position,2),num(c.wait,1)])):empty("조건에 해당하는 케이스가 없습니다.");
}
function archives(){
  el("pools").innerHTML=data.pools.length?table(["데이터 풀","전이 수","에피소드","학습 전이","검증 전이","파트"],data.pools.map(p=>[esc(p.id),num(p.unique_transitions),num(p.completed_episodes),num(p.split_counts?.expert_train),num(p.split_counts?.expert_val),num(p.parts?.length)])):empty("데이터 풀 기록이 없습니다.");
  el("demos").innerHTML=data.demos.length?table(["데모 폴더","시나리오","케이스","주행 횟수","상태"],data.demos.map(d=>[esc(d.id),esc(d.scenario),num(d.case_index),num(d.episodes?.length),esc(d.phase)])):empty("데모 기록이 없습니다.");
  options("log",data.logs.map(k=>[k,k]));
}
async function showLog(){
  if(!el("logDetails").open)return;
  const file=el("log").value;
  if(!file){el("logText").textContent="저장된 로그가 없습니다.";return;}
  try{
    const res=await fetch("/api/log?file="+encodeURIComponent(file));
    if(!res.ok)throw Error(res.status);
    const text=await res.text();
    if(el("log").value===file){el("logText").textContent=text;el("logText").scrollTop=el("logText").scrollHeight;}
  }catch(err){el("logText").textContent="로그 읽기 오류 · "+err.message;}
}
async function refresh(){
  if(busy)return;
  busy=true;el("refresh").disabled=true;
  try{
    const res=await fetch("/api/results");
    if(!res.ok)throw Error(res.status);
    data=await res.json();
    el("overview").innerHTML='<span><strong>'+data.runs.filter(r=>Object.keys(r.complete).length).length+'</strong>학습 완료</span><span><strong>'+data.evaluations.length+'</strong>평가 기록</span>';
    groups=new Map();
    for(const e of data.evaluations){
      const k=scope(e);
      if(!groups.has(k))groups.set(k,[]);
      groups.get(k).push(e);
    }
    const ranked=[...groups].sort((a,b)=>b[1].filter(e=>e.representative).length-a[1].filter(e=>e.representative).length);
    options("cohort",ranked.map(([k,g])=>[k,g[0].panel+" · "+Object.keys(g[0].scenarios).sort().join("/")+" · "+g[0].cases.length+"케이스 · "+g[0].cohort.slice(0,6)]));
    options("run",data.runs.map(r=>[r.id,nameOf(r)+" · "+r.id]));
    const evals=[...data.evaluations].sort((a,b)=>Number(b.representative)-Number(a.representative)||label(a).localeCompare(label(b))||a.step-b.step);
    options("evaluation",evals.map(e=>[e.id,label(e)+" · "+e.id]));
    comparison();training(true);cases();archives();await showLog();
    el("stamp").textContent=new Date().toLocaleTimeString("ko-KR")+" 갱신";
    el("warning").textContent=data.warnings.join(" / ");
  }catch(err){el("warning").textContent="결과 갱신 실패 · "+err.message+" · 서버 상태를 확인하고 새로고침하세요.";}
  finally{busy=false;el("refresh").disabled=false;}
}
el("comparison").onclick=event=>{
  const b=event.target.closest("[data-record]");
  if(b){el("evaluation").value=b.dataset.record;cases();el("cases").scrollIntoView();el("evaluation").focus({preventScroll:true});}
};
el("save").onclick=()=>{
  const svg=el("chart").querySelector("svg");
  if(!svg)return;
  const url=URL.createObjectURL(new Blob([svg.outerHTML],{type:"image/svg+xml"}));
  const link=document.createElement("a");link.href=url;link.download=el("run").value.replaceAll("/","_")+"-"+el("metric").value+".svg";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
el("refresh").onclick=refresh;el("cohort").onchange=comparison;el("run").onchange=()=>training(true);
el("metric").onchange=()=>training();el("evaluation").onchange=()=>cases();
el("filter").onchange=el("fail").onchange=()=>cases(false);
el("log").onchange=el("logDetails").ontoggle=showLog;
refresh();setInterval(()=>{if(el("auto").checked&&!document.hidden)refresh();},30000);
