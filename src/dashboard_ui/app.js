'use strict';
(() => {
  const capabilities = [
    ['messages-square','Conversation sur Twitch','Validé en direct','ready','Répond aux mentions avec le compte bot dédié, en citant le viewer. La connexion et une réponse réelle ont été validées avec toi.','@LumiTheBoat salut'],
    ['brain','Mémoire des viewers','Présent dans le code','','Historique, faits, résumés et statistiques conservés dans SQLite. Un changement de pseudo conserve la mémoire grâce à l’identifiant Twitch. La mémoire est actuellement commune à toutes les chaînes.','!remember pseudo préfère les jeux coopératifs · streamer/modos'],
    ['layers','Compression de l’historique','Présent dans le code','','Les anciens échanges sont résumés lorsque le budget de contexte est dépassé. Budget actuel : 2 500 tokens ; cela limite le contexte, pas la longueur visible de chaque réponse.','Automatique après dépassement du budget'],
    ['globe','Recherche web avec sources','Présent dans le code','','Recherche Internet déclenchée par commande ou par le routeur. La commande !search a une pause globale de 30 s. Toutes les sollicitations respectent également la cadence générale configurée. Internet et le modèle sont nécessaires.','!search ta question'],
    ['book-open','FAQ et documents','Préparation nécessaire','proposed','Lit TXT, Markdown, PDF et Word puis recherche des passages avec sources. Le modèle bge-m3 n’a pas été installé pendant la mise en route ; la FAQ fournie est fictive et doit être remplacée.','CLI : /ingest puis /ask ta question'],
    ['route','Orientation des questions','Présent dans le code','','Le routeur choisit conversation, documents ou web. Ce mécanisme est intégré aux mentions ; sa qualité dépend du modèle et des connaissances disponibles.','Automatique à chaque mention'],
    ['shield-check','Filtres de sécurité','Présent dans le code','','Filtres dans le code pour plusieurs attaques et masquage de données personnelles. Ils complètent le prompt ; des contournements et des faux positifs sont documentés.','Rapport de tests adversariaux : 48/53 conformes (résultat documenté)'],
    ['notebook-pen','Compte-rendu vivant','Présent dans le code','','Un événement met à jour la section pertinente du compte-rendu. !event est réservé au streamer et aux modérateurs. Le résumé ne provient pas d’une analyse audio ou vidéo du live.','!event description de ce qui vient de se passer'],
    ['sparkles','Moments forts et pics','Présent dans le code','','Les viewers peuvent signaler un moment. Le bot détecte aussi les pics de messages : ce sont des signaux du chat, pas des clips vidéo automatiquement extraits.','!moment description · pause de 60 s par viewer'],
    ['calendar-clock','Veille planifiée','Présent dans le code','','Recherche et résume des sujets web selon un intervalle. Les rapports se lancent depuis la CLI ; ce n’est pas encore un tableau de tendances Twitch ni une analyse d’audience.','CLI : /reports start · /reports status · /reports stop'],
    ['file-down','Exports et partage','Présent dans le code','','Exporte la conversation CLI ou le compte-rendu en Markdown, JSON, PDF ou HTML. Le lien de partage est local ; ce n’est pas un export automatique de tout le chat Twitch.','CLI : /export pdf report · /share report'],
    ['history','Conseils sur les lives passés','Préparation nécessaire','proposed','Archive les rapports et les recherche pour proposer des conseils sourcés. Nécessite des rapports réels, le modèle d’embeddings et l’indexation. Ne prouve pas encore un gain d’engagement.','CLI : /stream end puis /strategy'],
    ['wrench','Outils MCP','Présent dans le code','','La CLI peut appeler les outils de mémoire, de documents et de compte-rendu, ainsi qu’un serveur de fichiers. Les écritures demandent confirmation ; Node.js est requis pour le serveur de fichiers.','CLI : /tools'],
    ['monitor','Overlay OBS','Préparation nécessaire','proposed','Un résultat de recherche peut être affiché dans une source texte OBS via WebSocket. Intégration non testée dans cette session ; secondaire pour la première version du dashboard.','OBS + serveur WebSocket + source SensaiOverlay']
  ];
  const root = document.getElementById('lumi-studio');
  const $ = id => document.getElementById(id);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const fields = {channel:'ls-channel',trigger:'ls-trigger',reply_cooldown:'ls-cadence',mentions_only:'ls-mention',stream_topic:'ls-game',stream_context:'ls-context',tone:'ls-tone',reply_length:'ls-length',avoid_spoilers:'ls-spoilers'};
  let latest = null;
  let dirty = false;
  let busy = false;
  let initialized = false;
  let refreshing = false;
  let page = 'pilot';
  const phases = {stopped:'Arrêté',checking:'Vérification…',starting:'Connexion…',running:'Connecté au chat',stopping:'Arrêt en cours…',error:'Connexion interrompue'};
  const iconPaths = {
    sailboat:'M12 3v14M12 3 4 14h8M15 5l5 9h-5M3 18h18l-3 3H6z',
    'sliders-horizontal':'M3 6h6m4 0h8M3 12h12m4 0h2M3 18h3m4 0h11M9 3v6m6 0v6M6 15v6',
    'notebook-pen':'M4 3h13v18H4zM8 7h5M8 11h3m5 3 4-4 2 2-4 4-3 1z',
    blocks:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
    'chart-no-axes-combined':'M3 20V4m0 16h18M6 15l5-5 4 2 6-7',
    info:'M12 11v6m0-10v1M12 2a10 10 0 1 0 0 20 10 10 0 1 0 0-20',
    'messages-square':'M3 3h15v12H8l-5 4zM18 7h3v14l-5-3h-5',
    brain:'M9 4C3 1 1 9 5 11c-5 4 0 11 5 8V4m5 0c6-3 8 5 4 7 5 4 0 11-5 8V4',
    layers:'M12 3 2 8l10 5 10-5zM2 12l10 5 10-5M2 16l10 5 10-5',
    globe:'M12 2a10 10 0 1 0 0 20 10 10 0 1 0 0-20M2 12h20M12 2c-6 6-6 14 0 20 6-6 6-14 0-20',
    'book-open':'M12 5C8 2 4 3 2 4v16c4-2 7-2 10 0 3-2 6-2 10 0V4c-2-1-6-2-10 1v15',
    route:'M4 4h12a4 4 0 0 1 0 8H8a4 4 0 0 0 0 8h12M17 17l3 3-3 3',
    'shield-check':'M12 2 3 6v6c0 5 5 8 9 10 4-2 9-5 9-10V6zM8 12l3 3 5-6',
    sparkles:'m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3z',
    'calendar-clock':'M4 5h16v16H4zM8 2v6m8-6v6M4 10h16m-8 3v4h3',
    'file-down':'M4 2h11l5 5v15H4zM15 2v6h5M12 11v7m-3-3 3 3 3-3',
    history:'M3 5v5h5M3 10a9 9 0 1 1 1 8M12 7v6l3 2',
    wrench:'m14 3-3 5 5 5 5-3c1 7-7 10-11 6l-6 6-3-3 6-6C3 8 7 1 14 3',
    monitor:'M3 3h18v14H3zM12 17v4m-5 0h10'
  };
  function icons() {
    root.querySelectorAll('i[data-lucide]').forEach(el => {
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',iconPaths[el.dataset.lucide] || iconPaths.blocks);svg.append(path);el.replaceWith(svg);
    });
  }
  function error(message) {$('global-error').textContent=message;$('global-error').hidden=!message;}
  async function api(path, data, raw=false) {
    const response=await fetch(path,{method:data===undefined?'GET':'POST',headers:{'X-CSRF-Token':csrf,...(data===undefined?{}:{'Content-Type':'application/json'})},...(data===undefined?{}:{body:JSON.stringify(data)})});
    if(!response.ok) {const detail=await response.json().catch(()=>({}));throw new Error(detail.error || 'Action impossible. Recharge la page puis réessaie.');}
    return raw ? response : response.json();
  }
  function settings() {
    const values={};
    Object.entries(fields).forEach(([key,id])=>{const el=$(id);values[key]=el.type==='checkbox'?el.checked:el.type==='range'?Number(el.value):el.value;});
    return values;
  }
  function fillSettings(values) {
    Object.entries(fields).forEach(([key,id])=>{if(values[key]===undefined)return;const el=$(id);if(el.type==='checkbox')el.checked=values[key];else el.value=values[key];});
    previewContext();
  }
  function previewContext() {
    const s=settings();
    $('ls-cadence-value').textContent=s.reply_cooldown===0?'Sans pause':s.reply_cooldown+' s';
    const tones={friendly:'amical et naturel',calm:'calme et discret',energetic:'enthousiaste'};
    $('ls-context-preview').textContent='Lumi répond avec un ton '+tones[s.tone]+', '+(s.reply_length==='brief'?'en une phrase courte':'en une ou deux phrases')+'. '+(s.stream_topic?'Sujet : '+s.stream_topic+'. ':'')+'Il n’invente aucune information sur le live'+(s.avoid_spoilers?' et évite les spoilers.':'.')+(s.stream_context?' Contexte : '+s.stream_context:'');
  }
  function displayState(state) {
    latest=state;
    if(!initialized){fillSettings(state.settings);initialized=true;}
    const active=['checking','starting','running','stopping'].includes(state.phase);
    $('ls-pause-text').textContent=active?'Arrêter le bot':'Démarrer le bot';
    $('ls-pause').disabled=busy || ['checking','starting','stopping'].includes(state.phase) || state.external_bot;
    $('ls-channel').disabled=active;
    $('ls-pause').classList.toggle('ls-main',!active);
    $('ls-pause').removeAttribute('aria-pressed');
    $('bot-state-text').textContent=state.external_bot?'Actif dans un autre terminal':phases[state.phase] || state.phase;
    $('connection-status').textContent='Local · '+(state.external_bot?'Bot externe':phases[state.phase]);
    $('connection-status').className='ls-tag'+(state.phase==='running'?' ls-ready':'');
    const health=state.health;
    $('model-name').textContent=health.model || 'Non vérifié';
    const expired=health.expires_at && health.expires_at<Date.now()/1000;
    $('twitch-status').textContent=health.twitch==='ready'&&!expired?'Compte autorisé':health.twitch==='unchecked'?'Accès à vérifier':'À reconnecter';
    $('twitch-status').className='ls-tag '+(health.twitch==='ready'&&!expired?'ls-ready':'ls-proposed');
    $('check-access').disabled=busy;
    $('connect-account').disabled=busy || active || state.auth?.phase==='pending';
    $('auth-box').hidden=!state.auth || !['pending','error'].includes(state.auth.phase);
    if(state.auth){$('auth-message').textContent=state.auth.message || ''; $('auth-code').textContent=state.auth.code || '';}
    const metrics=state.metrics;
    const hasSession=metrics.started_at!==null;
    $('metric-rate').textContent=metrics.received_per_minute===null?'—':metrics.received_per_minute.toLocaleString('fr-FR');
    $('metric-replies').textContent=hasSession?metrics.replies:'—';
    $('metric-latency').textContent=metrics.median_latency===null?'—':metrics.median_latency.toLocaleString('fr-FR')+' s';
    $('pilot-latency').textContent=metrics.median_latency===null?'Aucune mesure':metrics.median_latency+' s (médiane)';
    $('session-label').textContent=hasSession?(metrics.ended_at?'Dernière session · ':'Session · ')+Math.floor(metrics.duration_seconds/60)+' min':'Aucune session démarrée';
    $('session-counts').textContent=hasSession?metrics.received+' messages · '+metrics.viewers+' chatteurs · '+metrics.cooldown_skipped+' sollicitations ignorées (pause)':'Pas encore de session';
    const events=state.events.slice(-8).reverse();
    $('event-log').replaceChildren();
    if(!events.length){const p=document.createElement('p');p.className='ls-muted';p.textContent='Les événements apparaîtront au démarrage du bot.';$('event-log').append(p);}
    events.forEach(event=>{const row=document.createElement('div');row.className='ls-event';const time=document.createElement('time');time.textContent=new Date(event.at*1000).toLocaleTimeString('fr-FR');const text=document.createElement('span');text.textContent=event.message;row.append(time,text);$('event-log').append(row);});
    const account=state.account || 'Compte à connecter';
    root.querySelector('.ls-account h3').textContent=state.settings.bot_name || account;
    root.querySelector('.ls-side-foot').textContent=account+' · '+(state.active_channel && active?state.active_channel:state.settings.channel);
    if(state.external_bot)$('ls-footer-note').textContent='Un bot est déjà actif dans un autre terminal. Arrête-le avant de le piloter ici.';
    else if(expired)$('ls-footer-note').textContent='L’autorisation Twitch a expiré. Arrête le bot puis utilise Reconnecter Twitch.';
    else $('ls-footer-note').textContent='Dashboard local · fermer cet onglet ne coupe pas le bot. Les statistiques portent sur les sessions lancées ici.';
  }
  async function refresh() {
    if(refreshing)return;refreshing=true;
    try{displayState(await api('/api/state'));}
    catch(err){$('connection-status').textContent='Dashboard déconnecté';error('Le serveur local ne répond plus. Relance le dashboard puis recharge cette page.');}
    finally{refreshing=false;}
  }
  function showPage(next) {
    page=next;
    root.querySelectorAll('[data-screen]').forEach(el=>{el.hidden=el.dataset.screen!==next;});
    root.querySelectorAll('[data-page]').forEach(el=>{if(el.dataset.page===next)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
    $('ls-save').hidden=['features','review'].includes(next);$('ls-save-state').hidden=$('ls-save').hidden;
    if(next==='review')loadReport();
  }
  async function action(work) {
    if(busy)return;busy=true;error('');if(latest)displayState(latest);
    try{await work();}catch(err){error(err.message || 'Connexion au serveur local impossible.');}
    finally{busy=false;await refresh();}
  }
  async function save() {
    const state=await api('/api/settings',settings());dirty=false;$('ls-save-state').textContent='Enregistré · appliqué aux prochains messages';displayState(state);
  }
  async function loadReport() {
    try {const data=await api('/api/report');$('export-report').disabled=!data.report;
      $('ls-report-preview').textContent=data.report?Object.entries(data.titles).map(([key,title])=>title+'\n'+data.report[key]).join('\n\n'):'Aucun compte-rendu pour le moment. Utilise !moment ou !event dans le chat. Les statistiques sont écrites à l’arrêt du bot.';
    }catch(err){error(err.message);}
  }
  for(const [index,feature] of capabilities.entries()){
    const button=document.createElement('button');button.className='ls-feature cursor-interaction';button.type='button';button.setAttribute('aria-pressed',String(index===0));
    button.innerHTML='<i data-lucide="'+feature[0]+'" aria-hidden="true"></i><span class="ls-feature-text"><strong>'+feature[1]+'</strong><span class="ls-tag '+(feature[3]?'ls-'+feature[3]:'')+'">'+feature[2]+'</span></span>';
    button.addEventListener('click',()=>{root.querySelectorAll('.ls-feature').forEach(el=>el.setAttribute('aria-pressed',String(el===button)));$('ls-detail-title').textContent=feature[1];$('ls-detail-description').textContent=feature[4];$('ls-detail-command').textContent=feature[5];});
    $('ls-features').append(button);
  }
  icons();
  root.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',()=>showPage(el.dataset.page)));
  root.querySelectorAll('[data-go]').forEach(el=>el.addEventListener('click',()=>showPage(el.dataset.go)));
  Object.values(fields).forEach(id=>$(id).addEventListener('input',()=>{dirty=true;previewContext();$('ls-save-state').textContent='Modifications non enregistrées';}));
  $('ls-save').addEventListener('click',()=>action(save));
  $('ls-pause').addEventListener('click',()=>action(async()=>{
    if(latest && ['running','starting'].includes(latest.phase)) await api('/api/stop',{});
    else {if(dirty)await save();await api('/api/start',{});}
  }));
  $('check-access').addEventListener('click',()=>action(async()=>{const health=await api('/api/check',{});if(health.twitch!=='ready'||health.ollama!=='ready')error([health.twitch_error,health.ollama_error].filter(Boolean).join(' '));else $('ls-save-state').textContent='Twitch et Ollama sont prêts.';}));
  $('connect-account').addEventListener('click',()=>action(async()=>{await api('/api/auth',{});}));
  $('ls-simulate').addEventListener('click',async()=>{
    $('ls-simulate').disabled=true;error('');$('ls-answer').textContent='Lumi prépare sa réponse…';$('ls-viewer-text').textContent=$('ls-message').value;
    try{const response=await api('/api/preview',{message:$('ls-message').value,settings:settings()});$('ls-answer').textContent=response.reply;$('ls-sim-status').textContent='Essai privé · '+(response.route==='web'?'Recherche web · ':'Conversation · ')+response.seconds+' s'+(response.blocked?' · filtré':'');}
    catch(err){$('ls-answer').textContent='Essai interrompu.';error(err.message || 'Connexion impossible.');}
    finally{$('ls-simulate').disabled=false;}
  });
  $('ls-report').addEventListener('click',loadReport);
  $('export-report').addEventListener('click',()=>action(async()=>{
    const format=$('ls-export').value;const response=await api('/api/export',{format},true);const blob=await response.blob();const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='StreamReport.'+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
  }));
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  refresh().then(()=>api('/api/check',{}).then(refresh).catch(err=>error(err.message)));
  setInterval(()=>{if(!document.hidden)refresh();},2500);
})();
