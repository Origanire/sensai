import requests, time, json, subprocess, pathlib
out=pathlib.Path('doc/evaluations/defense-2026-11-01')
base='http://localhost:11434'
report={'hardware':{k:subprocess.check_output(['sysctl','-n',v],text=True).strip() for k,v in [('ram_bytes','hw.memsize'),('model','hw.model'),('cpu','machdep.cpu.brand_string')]},'models':requests.get(base+'/api/tags',timeout=5).json(),'runs':[]}
question='Un viewer dit : encore mort au même boss. Réponds avec une seule courte phrase complice, sans inventer le jeu ni le nombre de tentatives.'
for model in ['llama3.2:latest','qwen3:14b','ministral-3:14b']:
 for limit in [32,128]:
  payload={'model':model,'messages':[{'role':'user','content':question}], 'stream':False,'think':False,'keep_alive':'2m','options':{'temperature':0.3,'seed':42,'num_ctx':8192,'num_predict':limit}}
  start=time.monotonic(); r=requests.post(base+'/api/chat',json=payload,timeout=180);r.raise_for_status();data=r.json()
  report['runs'].append({'request':payload,'seconds':time.monotonic()-start,'response':data,'loaded_models':requests.get(base+'/api/ps',timeout=5).json()})
  (out/'benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
  print(model,limit,data.get('eval_count'),round(report['runs'][-1]['seconds'],2),flush=True)
print('done')
# Expérience séparée : sortie assez longue pour atteindre le plafond.
report['parameter_experiment'] = []
for limit in [16,128]:
 payload={'model':'ministral-3:14b','messages':[{'role':'user','content':'Explique en trois phrases comment un bot Twitch peut mémoriser les préférences déclarées sans inventer de faits.'}], 'stream':False,'think':False,'options':{'temperature':0.3,'seed':42,'num_ctx':8192,'num_predict':limit}}
 start=time.monotonic();response=requests.post(base+'/api/chat',json=payload,timeout=180);response.raise_for_status()
 report['parameter_experiment'].append({'request':payload,'seconds':time.monotonic()-start,'response':response.json()})
(out/'benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
