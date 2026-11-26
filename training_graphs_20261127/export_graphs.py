"""Save only the charts offered by the dashboard, per model and seed."""
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/kcity-graph-cache')
from pathlib import Path
import sys
import json
import html
import shutil
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from dashboard.server import scan
OUT=Path(__file__).resolve().parent
data=scan()
catalog=[]

def save(series, folder, name, title, xlabel, ylabel, rate=False):
    fig, ax=plt.subplots(figsize=(9,4),constrained_layout=True)
    for label,points,baseline in series:
        if baseline:
            ax.axhline(points[0][1],ls='--',label=label)
        else:
            ax.plot([x for x,y in points],[y if y is not None else math.nan for x,y in points],
                    marker='.',label=label)
    ax.set(xlabel=xlabel,ylabel=ylabel)
    if rate:ax.set_ylim(0,100)
    ax.grid(alpha=.25);ax.legend(fontsize=9);fig.suptitle(title)
    folder.mkdir(parents=True,exist_ok=True)
    for ext in ['png','svg']:
        fig.savefig(folder/(name+'.'+ext),dpi=160,bbox_inches='tight')
    plt.close(fig)
    catalog.append(dict(title=title,file=str((folder/(name+'.png')).relative_to(OUT)),
                        svg=str((folder/(name+'.svg')).relative_to(OUT))))

# Remove the prior export's generated plot directories.
for name in ['BC','SAC','RLPD','comparison']:
    path=OUT/name
    if path.exists():shutil.rmtree(path)

for r in data['runs']:
    if r['id'] not in {f'dense_v2_1_main/{m}_seed{s}' for m in ['B1','B2','B3'] for s in [11,22,33]}:
        continue
    bc=r['method']=='B1'
    method={'B1':'BC','B2':'SAC','B3':'RLPD'}[r['method']]
    folder=OUT/method/f'seed{r["seed"]}'
    title=f'{method} seed {r["seed"]}'
    sections=['training','validation'] if bc else ['metrics']
    keys=sorted({k for row in r['curve'] for section in sections for k in (row.get(section) or {})})
    xkey='updates' if bc else 'transitions'
    xlabel='Optimizer updates' if bc else 'Environment transitions'
    for key in keys:
        series=[(section,[(p[xkey],(p.get(section) or {}).get(key)) for p in r['curve']],False)
                for section in sections]
        save(series,folder,key,title+' / '+key,xlabel,key)
    dev=sorted([e for e in data['evaluations'] if e['run']==r['id'] and e['step'] is not None],
               key=lambda e:e['step'])
    if dev:
        series=[(label,[(e['step'],100*e['aggregate'][key]) for e in dev],False)
                for label,key in [('Rule-compliant completion','compliant_completion_rate'),
                                  ('Collision','collision_rate')]]
        save(series,folder,'dev_completion_collision',title+' / Dev completion and collision',
             xlabel,'Rate (%)',True)

# The dashboard collision comparison groups identical panels, cases and metric versions.
for seed in [11,22,33]:
    selected=[e for e in data['evaluations'] if e['seed']==seed and e['panel']=='dev']
    cohorts=sorted({(e['cohort'],e['aggregate']['metric_version']) for e in selected})
    for cohort,version in cohorts:
        entries=[e for e in selected if (e['cohort'],e['aggregate']['metric_version'])==(cohort,version)]
        series=[]
        for method,label in [('B1','BC selected model'),('B2','SAC'),('B3','RLPD')]:
            rows=[e for e in entries if e['method']==method and
                  (e['representative'] and e['step'] is None if method=='B1' else isinstance(e['step'],(int,float)))]
            if not rows or len({e['run'] for e in rows})>1:continue
            if method=='B1' and len(rows)>1:continue
            if method!='B1' and len({e['step'] for e in rows})!=len(rows):continue
            rows.sort(key=lambda e:e['step'] or 0)
            points=[]
            for e in rows:
                a=e['aggregate']
                valid=(isinstance(a.get('collision_rate'),(int,float)) and 0<=a['collision_rate']<=1
                       and a['n_valid']>0 and a['n_valid']==a['n_planned'] and a.get('data_quality_valid') is not False)
                points.append((e['step'],100*a['collision_rate'] if valid else None))
            if not any(y is not None for x,y in points):continue
            series.append((label,points,method=='B1'))
        if any(not baseline for _,_,baseline in series):
            name=f'collision_rate_seed{seed}'
            if len(cohorts)>1:name+='_'+cohort[:8]
            save(series,OUT/'comparison',name,f'Collision comparison / seed {seed}',
                 'SAC / RLPD environment transitions','Collision rate (%)')

(OUT/'MANIFEST.json').write_text(json.dumps(dict(plots=catalog),ensure_ascii=False,indent=2)+'\n')
text="""<!doctype html><meta charset="utf-8"><title>Dashboard training graphs</title>
<style>body{font:16px sans-serif;max-width:1100px;margin:40px auto;padding:0 20px}
img{max-width:100%}details{margin:12px 0}summary{cursor:pointer}a{margin-right:15px}</style>
<h1>대시보드 학습 그래프</h1>
<p>모델·시드별 지표 선택 메뉴에 있는 학습 곡선과 Dev 완주율·충돌률,
학습 방법별 충돌률 비교를 저장했습니다. PNG와 SVG로 열 수 있습니다.</p>"""
last=None
for item in catalog:
    group=str(Path(item['file']).parent)
    if group!=last:
        text+='<h2>'+html.escape(group)+'</h2>';last=group
    text+=f'<details><summary>{html.escape(item["title"])}</summary><p><a href="{item["file"]}">PNG</a><a href="{item["svg"]}">SVG</a></p><img loading="lazy" src="{item["file"]}"></details>'
(OUT/'index.html').write_text(text)
print('Saved',len(catalog),'dashboard charts')
