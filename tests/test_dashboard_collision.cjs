// Run with: node --test tests/test_dashboard_collision.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../dashboard/dist/app.js'),'utf8');
const nodes=new Map();
const document={getElementById(id){
  if(!nodes.has(id))nodes.set(id,{value:id==='collisionSeed'?'11':'dev|same|v1',innerHTML:'',textContent:'',disabled:false});
  return nodes.get(id);
}};
const api=vm.runInNewContext(source.split('el("driveForm").onsubmit')[0]+
  ';({collisionSeries,collisionComparison,setData(value){data=value;}})',{document});
const row=(method,step,rate,extra={})=>({method,step,seed:11,panel:'dev',cohort:'same',
  run:method,representative:step==null,scenarios:{A:30,B:30,C:40},
  aggregate:{metric_version:'v1',collision_rate:rate,n_collision:rate*100,
    n_valid:100,n_planned:100,data_quality_valid:true},...extra});
const fixture=[row('B1',null,.02),row('B2',0,0),row('B2',25000,.23),row('B2',300000,.04),
  row('B3',0,0),row('B3',25000,.17),row('B3',300000,.01)];

test('compares matching seed and case set, keeping BC a fixed evaluation',()=>{
  const candidates=[...fixture,row('B1',null,.99,{seed:22}),row('B3',100,.99,{cohort:'other'}),
    row('B2',100,.99,{panel:'final'}),row('B3',100,.99,{aggregate:{...fixture[4].aggregate,metric_version:'v2'}})];
  const result=api.collisionSeries(candidates,'dev|same|v1');
  assert.equal(result.series.length,3);
  assert.equal(result.series[0].baseline,true);
  assert.equal(result.series[0].points[0][0],null);
  assert.equal(result.series[0].latest.aggregate.collision_rate,.02);
  assert.deepEqual(Array.from(result.series[1].points,p=>Array.from(p)),[[0,0],[25000,23],[300000,4]]);
  assert.equal(result.series[2].latest.aggregate.collision_rate,.01);
});

test('incomplete or invalid evaluations leave gaps, not zero collision rates',()=>{
  const invalid=row('B2',50000,.1,{aggregate:{...fixture[1].aggregate,n_valid:99}});
  const bad=row('B2',75000,.1,{aggregate:{...fixture[1].aggregate,data_quality_valid:false}});
  const result=api.collisionSeries([...fixture,invalid,bad],'dev|same|v1');
  const sac=result.series.find(s=>s.method==='B2');
  assert.equal(sac.points.find(p=>p[0]===50000)[1],null);
  assert.equal(sac.points.find(p=>p[0]===75000)[1],null);
  assert.match(result.issues.join(' '),/2건 제외/);
});

test('multiple runs or duplicate checkpoint evaluations are not silently merged',()=>{
  const multiple=api.collisionSeries([...fixture,row('B2',50000,.1,{run:'another'})],'dev|same|v1');
  assert.equal(multiple.series.some(s=>s.method==='B2'),false);
  const duplicate=api.collisionSeries([...fixture,row('B3',25000,.1)],'dev|same|v1');
  assert.equal(duplicate.series.some(s=>s.method==='B3'),false);
});

test('renders three distinct SVG series and keeps existing training chart untouched',()=>{
  const old=document.getElementById('chart');old.innerHTML='existing training chart';
  api.setData({evaluations:fixture});api.collisionComparison();
  const svg=document.getElementById('collisionChart').innerHTML;
  for(const method of ['B1','B2','B3'])assert.match(svg,new RegExp('data-method="'+method+'"'));
  assert.match(svg,/stroke-dasharray="8 5"/);
  assert.equal((svg.match(/<circle /g)||[]).length,6);
  assert.equal(old.innerHTML,'existing training chart');
  assert.equal(document.getElementById('collisionSave').disabled,false);
  assert.doesNotMatch(svg,/NaN|Infinity/);
});

test('missing RL evaluations disable export and show the empty state',()=>{
  api.setData({evaluations:[fixture[0]]});api.collisionComparison();
  assert.equal(document.getElementById('collisionSave').disabled,true);
  assert.match(document.getElementById('collisionChart').innerHTML,/평가 기록이 없습니다/);
});

test('selects v2.1 seed 22 independently of seed 11 and v1 records',()=>{
  const rows=[...fixture,row('B3',300000,0,{seed:22}),row('B3',300000,.2,{seed:22,training:'v1'})];
  const {series}=api.collisionSeries(rows,'dev|same|v1',22);
  assert.equal(series.length,1);
  assert.equal(series[0].latest.aggregate.collision_rate,0);
});
