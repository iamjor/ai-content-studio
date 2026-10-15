(async function(){
const KEY='aics_workspace_v2';
const defaultProject=()=>({id:'sample-series',title:'Sample series',genre:'AI microdrama',description:'A fictional starter project. Replace or edit it for your own story.',stage:'Planning',episodes:structuredClone(seed.episodes),characters:structuredClone(seed.characters),gates:structuredClone(seed.gates)});
function migrate(value){
 if(value&&Array.isArray(value.projects)&&value.projects.length){
  value.projects.forEach(p=>{p.episodes??=[];p.characters??=[];p.gates??=[]});
  return value;
 }
 if(value&&Array.isArray(value.episodes))return {projects:[{...defaultProject(),id:'imported-series',title:'Imported series',episodes:value.episodes,characters:value.characters||[],gates:value.gates||[]}],activeId:'imported-series'};
 return {projects:[defaultProject()],activeId:'sample-series'};
}
let state, revision=0, saveQueue=Promise.resolve(), saveFailed=false;
const response=await fetch('/api/workspace');
if(!response.ok)throw Error('Could not load workspace');
const loaded=await response.json();
revision=loaded.revision;
state=loaded.data?migrate(loaded.data):migrate(null);
const syncStatus=document.getElementById('syncStatus');
async function writeSnapshot(snapshot){
 const result=await fetch('/api/workspace',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,data:snapshot})});
 if(!result.ok)throw Error((await result.json().catch(()=>({}))).error||'Save failed');
 revision=(await result.json()).revision;
 syncStatus.textContent='Saved to studio database';
}
function persist(){
 if(saveFailed)return;
 const snapshot=structuredClone(state);
 syncStatus.textContent='Saving…';
 saveQueue=saveQueue.then(()=>writeSnapshot(snapshot)).catch(error=>{
  saveFailed=true;
  syncStatus.textContent='Save failed. Export a backup, then reload before editing.';
  alert('Your changes could not be saved: '+error.message+' Export a backup before reloading.');
 });
}
if(!loaded.data)persist();else syncStatus.textContent='Saved to studio database';
const $=id=>document.getElementById(id);
const safeLink=s=>{try{const u=new URL(s);return ['http:','https:'].includes(u.protocol)?u.href:''}catch{return ''}};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function active(){return state.projects.find(p=>p.id===state.activeId)||state.projects[0]}
function go(tab){document.querySelectorAll('.nav button,.section').forEach(x=>x.classList.remove('active'));document.querySelector(`.nav button[data-tab="${tab}"]`)?.classList.add('active');$(tab)?.classList.add('active');render()}
const statuses=['Script draft','60s script ready','References approved','Assets generated','Editing','Ready for review','Approved','Published'];
function render(){const p=active();$('projectCount').textContent=state.projects.length;$('episodeCount').textContent=state.projects.reduce((n,x)=>n+x.episodes.length,0);$('readyCount').textContent=state.projects.reduce((n,x)=>n+x.episodes.filter(e=>['Approved','Published'].includes(e.status)).length,0);$('sheetCount').textContent=state.projects.reduce((n,x)=>n+x.characters.filter(c=>c.state==='Reference approved').length,0);
 const projects=state.projects.map(x=>`<article class="card projectcard"><div class="kicker">${esc(x.genre||'New project')}</div><h3>${esc(x.title)}</h3><p>${esc(x.description||'Your next creative world begins here.')}</p><div class="cardfooter"><span class="badge ${x.stage==='Published'?'green':'amber'}">${esc(x.stage||'Planning')} · ${x.episodes.length} episodes</span><button class="btn" data-open="${esc(x.id)}">Open project</button></div></article>`).join('');$('homeProjects').innerHTML=projects;$('projectGrid').innerHTML=projects;$('activeTitle').textContent=p.title;$('activeMeta').textContent=`${p.genre||'Untitled format'} · ${p.episodes.length} episodes · ${p.stage||'Planning'}`;$('characterTitle').textContent=p.title;
 $('episodeGrid').innerHTML=p.episodes.length?p.episodes.map((e,i)=>`<article class="card"><div class="kicker">${esc(e.id)} · ${esc(e.duration||60)} seconds</div><h3>${esc(e.title)}</h3><p>${esc(e.hook)}</p><div class="meter"><i style="width:${Math.max(9,(statuses.indexOf(e.status)+1)*12)}%"></i></div><div class="cardfooter"><span class="badge ${['Approved','Published'].includes(e.status)?'green':'amber'}">${esc(e.status||'Script draft')}</span><button class="btn" data-edit="${i}">Open script</button></div></article>`).join(''):'<div class="card empty"><h3>No episodes yet</h3><p>Add the first episode to begin its script.</p></div>';
 $('characterGrid').innerHTML=p.characters.length?p.characters.map((c,i)=>`<article class="card"><div class="kicker">${esc(c.role||'Character')} · ${esc(c.age||'')}</div><h3>${esc(c.name)}</h3><p>${esc(c.look)}</p><div class="cardfooter"><span class="badge ${c.state==='Reference approved'?'green':'amber'}">${esc(c.state||'Written canon only')}</span><button class="btn" data-character="${i}">Edit</button></div>${safeLink(c.link)?`<p><a href="${esc(safeLink(c.link))}" target="_blank" rel="noopener noreferrer">Reference ↗</a></p>`:''}</article>`).join(''):'<div class="card empty"><h3>No characters yet</h3><p>Add a cast member or recurring asset.</p></div>'}
document.querySelectorAll('.nav button').forEach(b=>b.addEventListener('click',()=>go(b.dataset.tab)));
document.querySelectorAll('dialog [data-cancel]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close('cancel')));
document.body.addEventListener('click',e=>{const g=e.target.closest('[data-go]');if(g)go(g.dataset.go);const n=e.target.closest('[data-new]');if(n)$('projectDialog').showModal();const op=e.target.closest('[data-open]');if(op){state.activeId=op.dataset.open;persist();go('episodes')}});
document.querySelectorAll('#newProject,[data-new]').forEach(b=>b.addEventListener('click',()=>{if(!$('projectDialog').open)$('projectDialog').showModal()}));
$('createProject').addEventListener('click',e=>{const title=$('pTitle').value.trim();if(!title){e.preventDefault();$('pTitle').focus();return}const id='p-'+crypto.randomUUID();const p={id,title,genre:$('pGenre').value.trim(),description:$('pDescription').value.trim(),stage:'Planning',episodes:[],characters:[],gates:[]};state.projects.push(p);state.activeId=id;persist();$('projectForm').reset();go('episodes')});
let editIndex=-1;
function openEpisode(i){editIndex=i;const e=active().episodes[i];$('modalKicker').textContent=e.id;$('modalTitle').textContent=e.title;$('eTitle').value=e.title;$('hook').value=e.hook||'';$('status').value=e.status||'Script draft';$('duration').value=e.duration||60;$('script').value=e.script||'';$('assetLink').value=e.assetLink||'';$('editor').showModal()}
$('episodeGrid').addEventListener('click',e=>{const b=e.target.closest('[data-edit]');if(b)openEpisode(Number(b.dataset.edit))});
$('addEpisode').addEventListener('click',()=>{const p=active();const id='EP'+String(p.episodes.length+1).padStart(2,'0');p.episodes.push({id,title:'Untitled episode',hook:'',status:'Script draft',duration:60,script:'',assetLink:''});persist();render();openEpisode(p.episodes.length-1)});
$('save').addEventListener('click',e=>{const title=$('eTitle').value.trim();if(!title){e.preventDefault();$('eTitle').focus();return}const o=active().episodes[editIndex];if(!o)return;o.title=title;o.hook=$('hook').value.trim();o.status=$('status').value;o.duration=Number($('duration').value)||60;o.script=$('script').value;o.assetLink=$('assetLink').value;persist();render()});
let characterIndex=-1;
function openCharacter(i){characterIndex=i;const c=i>=0?active().characters[i]:{name:'',role:'',age:'',look:'',state:'Written canon only',link:''};$('characterModalTitle').textContent=i>=0?'Edit character':'Add character';$('cName').value=c.name;$('cRole').value=c.role;$('cAge').value=c.age;$('cLook').value=c.look;$('cState').value=c.state;$('cLink').value=c.link||'';$('characterDialog').showModal()}
$('addCharacter').addEventListener('click',()=>openCharacter(-1));$('characterGrid').addEventListener('click',e=>{const b=e.target.closest('[data-character]');if(b)openCharacter(Number(b.dataset.character))});
$('saveCharacter').addEventListener('click',e=>{const name=$('cName').value.trim();if(!name){e.preventDefault();$('cName').focus();return}const c={name,role:$('cRole').value.trim(),age:$('cAge').value.trim(),look:$('cLook').value.trim(),state:$('cState').value,link:$('cLink').value.trim()};if(characterIndex<0)active().characters.push(c);else active().characters[characterIndex]=c;persist();render()});
const toolsData=[['ChatGPT','Story bible, scripts, prompts and optional image references. Account allowance is not an unlimited free API.'],['Google Flow','Image-to-video experiments. Free daily credits; shot cost varies by model and length.'],['Vibes AI / Meta Vibes','Optional test. vibes.ai and Meta Vibes are separate tools; check the exact service and export terms.'],['Google AI Studio','Filipino text-to-speech tests; verify model free tier, pronunciation and timing.'],['CapCut','Assemble clips, effects, music and captions. Pro-marked material may block free export.'],['Kdenlive','Open-source editing fallback and clean master exports.']];$('toolGrid').innerHTML=toolsData.map(([name,description])=>`<article class="card"><div class="kicker">Production tool</div><h3>${esc(name)}</h3><p>${esc(description)}</p></article>`).join('');
$('export').addEventListener('click',()=>{const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));a.href=url;a.download='ai-content-studio-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
$('import').addEventListener('click',()=>$('file').click());$('file').addEventListener('change',async e=>{const f=e.target.files?.[0];if(!f)return;try{const v=migrate(JSON.parse(await f.text()));if(!Array.isArray(v.projects)||!v.projects.every(p=>Array.isArray(p.episodes)&&Array.isArray(p.characters)))throw Error('Invalid');if(confirm('Replace all projects in the shared studio database with this backup? This changes what you see on every device.')){state=v;persist();render();go('overview')}}catch{alert('This is not a valid AI Content Studio backup.')}e.target.value=''});
render();

})().catch(error=>{document.getElementById("syncStatus").textContent="Could not load workspace. Refresh after checking the server.";console.error(error)});
