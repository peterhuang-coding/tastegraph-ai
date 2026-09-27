(function(){
'use strict';
const $=(id)=>document.getElementById(id);
const API='/api/v1/collections';
let items=[],doc=null,currentId=null,loadingId=null,uploadRows=[],pollTimer=null,modalClaim=null,capabilities=null,ocrChoice={ids:[],language:'en',mode:'identify'};
const dirty={details:false,draft:false,target:false};
let uploadChain=Promise.resolve();
const els={};
function escapeHTML(s){
  return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function safeUrl(u){
  try{const x=new URL(u,location.origin);return (x.protocol==='http:'||x.protocol==='https:')?x.href:'';}
  catch(e){return '';}
}
function photoUrl(id,pid){return `${API}/${encodeURIComponent(id)}/photos/${encodeURIComponent(pid)}`;}
function exportUrl(id,eid){return `${API}/${encodeURIComponent(id)}/exports/${encodeURIComponent(eid)}`;}
function setStatus(msg,warn){
  const s=$('status'); s.textContent=msg||''; s.className=warn?'warn':'';
}
function show(which){
  ['wsEmpty','wsLoading','wsError','wsPanels'].forEach(id=>$(id).classList.toggle('hidden',id!==which));
}
async function request(method,url,body,isBlob){
  const opt={method,headers:{},credentials:'same-origin'};
  if(body!==undefined){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(body);}
  const r=await fetch(url,opt);
  if(isBlob){
    if(!r.ok){let m='请求失败';try{const j=await r.json();m=j.detail||m;}catch(e){}throw new Error(m);}
    return {url:URL.createObjectURL(await r.blob())};
  }
  const text=await r.text(), data=text?JSON.parse(text):null;
  if(!r.ok){const e=new Error((data&&data.detail)||'请求失败');e.status=r.status;throw e;}
  return data;
}
function apiList(){return request('GET',API);}
function apiGet(id){return request('GET',`${API}/${encodeURIComponent(id)}`);}
function apiCreate(p){return request('POST',API,p);}
function apiUpdate(id,p){return request('POST',`${API}/${encodeURIComponent(id)}`,p);}
function apiAction(id,p){return request('POST',`${API}/${encodeURIComponent(id)}/actions`,p);}
function apiCapabilities(){return request('GET',`${API}/capabilities`);}
function stateLabel(s){return {idle:'未开始',pending:'等待开始',running:'进行中',awaiting_review:'待人工复核',completed:'已完成',succeeded:'已完成',failed:'失败',cancelled:'已取消',canceled:'已取消',interrupted:'已中断',needs_info:'待补资料',ready:'可研究'}[s]||s||'未开始';}
function snapshotPanel(){
  const snap={};
  for(const [part,id] of Object.entries({details:'pDetails',draft:'pDraft',target:'pTarget'}))
    snap[part]=[...$(id).querySelectorAll('input,textarea,select')].map(x=>({id:x.id,name:x.name,value:x.value,checked:x.checked,type:x.type}));
  return snap;
}
function restorePanel(snap){
  for(const [part,id] of Object.entries({details:'pDetails',draft:'pDraft',target:'pTarget'})){
    if(!dirty[part])continue;
    for(const v of snap[part]||[]){const x=v.id?$(v.id):[...$(id).querySelectorAll('input')].find(x=>x.name===v.name&&x.value===v.value);if(!x)continue;if(v.type==='checkbox')x.checked=v.checked;else x.value=v.value;}
  }
}
function renderList(){
  if(!items.length){$('listBody').innerHTML='<p class="muted small">还没有档案。</p>';return;}
  $('listBody').innerHTML=renderListItems();
}
function renderListItems(){
  return '<ol class="item-list">'+items.map(x=>`<li><button type="button" class="item-link${x.id===currentId?' active':''}" data-id="${escapeHTML(x.id)}"><span>${escapeHTML(x.title||'未命名')}</span><small>${stateLabel(x.research_state)} · 照片 ${Number(x.photo_count)||0}</small></button></li>`).join('')+'</ol>';
}
function renderWorkspace(){
  if(!doc)return;
  const snap=snapshotPanel();
  $('pLedger').innerHTML=renderLedger();
  if(!$('pPhotos').querySelector('.shot-edit'))$('pPhotos').innerHTML=renderPhotos();
  if(!dirty.details)$('pDetails').innerHTML=renderDetails();
  if(!dirty.target)$('pTarget').innerHTML=renderTarget();
  $('pResearch').innerHTML=renderResearch();
  $('pClaims').innerHTML=renderClaims();
  if(!dirty.draft)$('pDraft').innerHTML=renderDraft();
  $('pExports').innerHTML=renderExports();
  restorePanel(snap);bindWorkspace();
}
function renderLedger(){
  const q=(doc.questions||[]).map(x=>`<li>${escapeHTML(x)}</li>`).join('');
  return `<h2>档案台账</h2><div class="ledger-id">记录编号 <code>${escapeHTML(doc.id)}</code></div>
  <dl class="meta"><dt>修订</dt><dd>${escapeHTML(doc.revision)}</dd><dt>更新时间</dt><dd>${escapeHTML(doc.updated_at)}</dd><dt>研究状态</dt><dd>${stateLabel(doc.research.state)}</dd></dl>
  <button type="button" id="refreshItem">重新读取（保留当前输入）</button><h3>待研究问题</h3>${q?'<ol>'+q+'</ol>':'<p class="muted small">尚未填写问题。目标确认且至少有一个问题、一张可读照片后，才能开始研究。</p>'}`;
}
function renderPhotos(){
  const ps=doc.photos||[];
  const cards=ps.map((p,i)=>`<figure class="shot" data-pid="${escapeHTML(p.id)}">
  <img src="${photoUrl(doc.id,p.id)}" alt="${escapeHTML(p.caption||p.name||'藏品照片')}">
  <figcaption><span class="shot-no">${i+1}</span>${escapeHTML(p.name)}<br><small>${p.private?'私有':'公开'} · 模型${p.allow_model?'可用':'不可用'}</small>
  <button type="button" data-act="photoEdit" data-id="${escapeHTML(p.id)}" class="small-btn">权限/说明</button>
  <button type="button" data-act="photoUp" data-id="${escapeHTML(p.id)}" ${i===0?'disabled':''}>上移</button><button type="button" data-act="photoDown" data-id="${escapeHTML(p.id)}" ${i===ps.length-1?'disabled':''}>下移</button>
  <button type="button" data-act="photoRemove" data-id="${escapeHTML(p.id)}" class="small-btn danger">移除</button></figcaption></figure>`).join('');
  const rows=uploadRows.map((r,i)=>`<li class="up ${r.state}"><span>${escapeHTML(r.file.name)}</span><b>${r.state==='done'?'已加入':r.state==='error'?'失败':'上传中'}</b>${r.state==='error'?`<button type="button" class="small-btn" data-retry="${i}">重试</button>`:''}${r.message?`<small>${escapeHTML(r.message)}</small>`:''}</li>`).join('');
  return `<h2>照片联系表</h2><p class="muted small">仅支持 JPG、PNG、WEBP；单个文件不超过 10MiB、2000 万像素，每件最多 18 张。照片默认私有，且不提供给模型。</p>
  <input type="file" id="photoFiles" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" multiple>
  <ul class="upload-rows">${rows}</ul><div class="contact">${cards||'<p class="muted small">还没有照片。</p>'}</div>`;
}
function renderDetails(){
  const q=(doc.questions||[]).join('\n');
  return `<h2>事实与私人记录</h2>
  <label for="dTitle">名称</label><input id="dTitle" name="title" value="${escapeHTML(doc.title)}" maxlength="120">
  <label for="dKnown">已知信息</label><textarea id="dKnown" name="known_info" rows="4">${escapeHTML(doc.known_info)}</textarea>
  <label for="dQuestions">问题（每行一个）</label><textarea id="dQuestions" name="questions" rows="3">${escapeHTML(q)}</textarea>
  <label for="dStory">个人故事（只有在汇编时明确勾选才会公开）</label><textarea id="dStory" name="personal_story" rows="3">${escapeHTML(doc.personal_story)}</textarea>
  <label for="dNotes">私人笔记（不会公开，也不会提供给模型）</label><textarea id="dNotes" name="private_notes" rows="3">${escapeHTML(doc.private_notes)}</textarea>
  <button type="button" id="saveDetails" class="primary">保存资料</button>`;
}
function renderTarget(){
  const t=doc.target||{};
  return `<h2>研究对象确认</h2><label for="tLabel">对象名称</label><input id="tLabel" value="${escapeHTML(t.label||'')}" maxlength="120">
  <label class="check"><input type="checkbox" id="tConfirmed" ${t.confirmed?'checked':''}> 我确认这是本次研究对象</label>
  <button type="button" id="saveTarget" class="primary">保存确认</button><p class="muted small">确认不会自动开始研究。</p>`;
}
function phaseLabel(phase){if(phase?.startsWith('ocr:'))return '读取所选照片文字';if(phase?.startsWith('extract:'))return '读取原文：'+phase.slice(8);return {identify:'本地文字识别',research:'背景研究',search:'查找公开条目'}[phase]||phase||'';}
function renderResearch(){
  const r=doc.research||{}, running=r.state==='running', cap=capabilities||{}, ident=cap.identify||{}, res=cap.research||{};
  const photos=(doc.photos||[]).map(p=>`<label class="check"><input type="checkbox" name="ocr_photo" value="${escapeHTML(p.id)}" ${ocrChoice.ids.includes(p.id)?'checked':''}> ${escapeHTML(p.name||p.id)}（${p.private?'私有，仅本地 OCR':'公开'}）</label>`).join('');
  const boxes=v=>Array.isArray(v)?v:(v?[v]:[]);
  const result=()=>{if(!r.result)return '';const z=r.result,src=boxes(z.sources),obs=boxes(z.observations),gaps=boxes(z.gaps),errs=boxes(z.errors),snap=z.inputs||{};
    const sourceHtml=src.map(s=>{const u=safeUrl(s.url||s.link||('https://'+(s.language==='zh'?'zh':'en')+'.wikipedia.org/wiki/'+encodeURIComponent(s.title)));return `<li><strong>${escapeHTML(s.title)}</strong>${u?` <a href="${escapeHTML(u)}" target="_blank" rel="noopener noreferrer">查看原文</a>`:''}<br><small>访问：${escapeHTML(s.accessed_at||'未知')} · ${escapeHTML(s.scope||'公开百科背景检索')}</small><p>${escapeHTML(s.excerpt||'')}</p><small class="muted">局限：${escapeHTML(s.limitations||'不能证明此藏品的版本、生产或真伪')}</small></li>`;}).join('');
    const obsHtml=obs.map(o=>`<li>照片 ${escapeHTML(o.photo_id)}：${escapeHTML(o.recognized_text||'未识别到文字')}${boxes(o.candidates).map(c=>` <em>候选线索：${escapeHTML(typeof c==='string'?c:c.name)}</em>`).join('')}<br><small class="muted">OCR 只是候选线索，不是事实；不能据此判断型号、版本或真伪。${o.error?` 阶段错误：${escapeHTML(o.error)}`:''}</small></li>`).join('');
    return `<h3>运行结果（${stateLabel(z.state||r.state)}）</h3><h4>输入快照</h4><p class="muted small">对象：${escapeHTML((snap.target_label??snap.label)||'')}；问题：${escapeHTML(boxes(snap.questions).join('；'))}；照片：${escapeHTML(boxes(snap.photo_ids).join('、'))}；语言：${snap.language==='zh'?'中文':'English'}</p>
    <h4>来源</h4><ul>${sourceHtml||'<li class="muted">无可引用来源。</li>'}</ul><h4>本地 OCR 观察</h4><ul>${obsHtml||'<li class="muted">无 OCR 观察。</li>'}</ul>
    <h4>信息缺口/未回答问题</h4><ul>${gaps.map(g=>`<li>${escapeHTML(typeof g==='string'?g:(g.question||'待补证据')+'：当前背景材料尚未回答；请补充厂商目录、型号或底部标识。')}</li>`).join('')||'<li class="muted">无。</li>'}</ul>
    <h4>错误</h4><ul>${errs.map(e=>`<li>${escapeHTML(typeof e==='string'?e:[e.stage,e.source,e.error].filter(Boolean).join(' / '))}</li>`).join('')||'<li class="muted">无。</li>'}</ul>`;};
  return `<h2>证据导向研究</h2><p>当前：${stateLabel(r.state)}${r.phase?` · ${escapeHTML(phaseLabel(r.phase))}`:''}${r.error?` — ${escapeHTML(r.error)}`:''}</p>
  <label for="rMode">工作方式</label><select id="rMode" ${running?'disabled':''}><option value="identify" ${ocrChoice.mode==='identify'?'selected':''}>本地 OCR 识别辅助</option><option value="research" ${ocrChoice.mode==='research'?'selected':''}>${escapeHTML(res.scope||'公开百科背景检索')}</option></select>
  <label for="rLang">语言</label><select id="rLang" ${running?'disabled':''}><option value="en" ${ocrChoice.language==='en'?'selected':''}>English</option><option value="zh" ${ocrChoice.language==='zh'?'selected':''}>中文</option></select>
  <fieldset id="ocrBox"><legend>本地 OCR：明确选择 1–4 张照片</legend><p class="muted small">仅调用本机已安装 Tesseract，读取所选照片的预览；不会上传照片，私有照片保持私有。识别文字可能错误；空结果也是结果。无鉴真伪结论。</p><div class="claim-grid">${photos||'<p class="muted small">暂无照片。</p>'}</div><p>${ident.available?'已检测到本地 OCR：'+escapeHTML(ident.reason||'已就绪'):'<span class="inline-error">OCR 不可用：'+escapeHTML(ident.reason||'尚未读取能力')+'</span>'}</p></fieldset>
  <fieldset id="researchBox"><legend>公开百科背景检索</legend><label class="check"><input type="checkbox" id="rExternal"> 我确认允许外部检索</label><p class="muted small">只发送已确认对象名称；1–3 个问题保留为本地研究范围，当前检索只提供背景材料；不发送照片、说明、已知信息、故事、私人笔记或草稿。背景资料不能证明此藏品版本、生产或真伪；品牌目录/博物馆证据仍需在证据卡片手动添加。</p></fieldset>
  <button type="button" id="startResearch" class="primary" ${running?'disabled':''}>明确开始</button>
  <button type="button" id="cancelResearch" ${running?'':'disabled'}>取消当前运行</button>
  <p class="muted small">结果待本人复核，不自动写入证据卡片或文稿。预算 ${cap.budget?.seconds||90} 秒，最多 ${cap.budget?.max_photos||4} 张照片。</p>${result()}`;
}
function certaintyLabel(x){return {supported:'有证据支持',inferred:'推断',unknown:'未能确认'}[x]||x;}
function reviewLabel(x){return {pending:'待复核',accepted:'已接受',disputed:'有争议'}[x]||x;}
function renderClaims(){
  const cs=doc.claims||[];
  const cards=cs.map(c=>{const ev=(c.evidence||[]).map(e=>{const u=safeUrl(e.url);return `<li>${escapeHTML(e.title)}${u?` <a href="${escapeHTML(u)}" target="_blank" rel="noopener noreferrer">链接</a>`:''}<br><small>${escapeHTML(e.excerpt)}<br>访问：${escapeHTML(e.accessed_at)}<br>支持范围：${escapeHTML(e.scope)}<br>局限：${escapeHTML(e.limitations||'未填写')}</small></li>`;}).join('');
  return `<article class="claim ${escapeHTML(c.certainty)}"><h3>${escapeHTML(c.field)}</h3><p>${escapeHTML(c.text)}</p><p class="muted small">${certaintyLabel(c.certainty)} · ${reviewLabel(c.review)} · ${c.public?'公开':'私有'}</p><ul>${ev}</ul><button type="button" class="small-btn" data-claim="${escapeHTML(c.id)}">编辑</button></article>`;}).join('');
  return `<h2>证据卡片</h2><button type="button" id="newClaim" class="primary">新增卡片</button><div class="claim-grid">${cards||'<p class="muted small">还没有证据卡片。</p>'}</div>`;
}
function renderDraft(){
  const d=doc.draft||{title:'',body:'',image_ids:[],claim_ids:[],confirmed:false,needs_review:false};
  const imgs=(doc.photos||[]).filter(p=>!p.private).sort((a,b)=>{const order=[...d.image_ids,...doc.photos.map(x=>x.id)];return order.indexOf(a.id)-order.indexOf(b.id);}).map(p=>`<label class="check"><input type="checkbox" name="image_ids" value="${escapeHTML(p.id)}" ${d.image_ids.includes(p.id)?'checked':''}> 使用照片：${escapeHTML(p.name)} <button type="button" data-draft-up="${escapeHTML(p.id)}" class="small-btn">上移</button></label>`).join('')||'<p class="muted small">没有公开照片；需先明确公开至少一张。</p>';
  const claims=(doc.claims||[]).filter(c=>c.public&&c.review==='accepted').map(c=>`<label class="check"><input type="checkbox" name="claim_ids" value="${escapeHTML(c.id)}" ${d.claim_ids.includes(c.id)?'checked':''}> ${escapeHTML(c.field)}（${reviewLabel(c.review)}）</label>`).join('');
  return `<h2>可编辑文章草稿</h2><p class="muted small">${d.confirmed?'已确认，可导出当前版本。':'草稿未确认，请检查事实、图序和隐私。'}</p><label for="drTitle">标题</label><input id="drTitle" name="title" value="${escapeHTML(d.title)}" maxlength="160">
  <label for="drBody">正文</label><textarea id="drBody" name="body" rows="10">${escapeHTML(d.body)}</textarea>
  <fieldset><legend>使用的公开照片</legend>${imgs}</fieldset><fieldset><legend>引用卡片</legend>${claims||'<span class="muted small">无</span>'}</fieldset>
  <label class="check"><input type="checkbox" id="incStory"> 汇编时加入我的个人故事（默认不加入）</label>
  <label for="drAngle">汇编角度</label><select id="drAngle"><option value="观察细节">观察细节</option><option value="证据时间线">证据时间线</option><option value="待确认问题">待确认问题</option></select>
  <button type="button" id="genDraft">按已接受公开证据汇编</button>
  <button type="button" id="saveDraft" class="primary">保存草稿</button>
  <fieldset class="privacy-box"><legend>确认公开前检查</legend>
  <label class="check"><input type="checkbox" id="dc1"> 标题和正文非空</label><label class="check"><input type="checkbox" id="dc2"> 只使用公开照片</label><label class="check"><input type="checkbox" id="dc3"> 未包含私人笔记和不愿公开的故事</label></fieldset>
  <button type="button" id="confirmDraft">保存并确认</button>
  ${d.needs_review?'<p class="inline-error">引用资料或照片已变化，需要重新检查确认。</p>':''}`;
}
function renderExports(){
  const es=doc.exports||[];
  return `<h2>导出快照</h2><p class="muted small">导出后不可变；之后修改不会改变已有 ZIP。</p>
  <label class="check"><input type="checkbox" id="exCheck"> 我已检查：导出文件不含私人笔记、私有照片和原始文件名</label>
  <button type="button" id="exportBtn" class="primary">导出 ZIP</button>
  <ul class="export-list">${es.map(e=>`<li><code>${escapeHTML(e.export_id||e.id)}</code> <a href="${exportUrl(doc.id,e.export_id||e.id)}">下载</a><small>${escapeHTML(e.created_at||e.date||'')}</small></li>`).join('')||'<li class="muted small">尚无导出。</li>'}</ul>`;
}
async function loadList(keep){
  $('listLoading').classList.remove('hidden');$('listError').classList.add('hidden');
  try{items=(await apiList()).items||[];$('listBody').classList.remove('hidden');renderList();}
  catch(e){$('listErrorText').textContent=e.message;$('listError').classList.remove('hidden');}
  finally{$('listLoading').classList.add('hidden');if(!keep&&!currentId)show('wsEmpty');}
}
async function openItem(id){
  if(uploadRows.some(r=>r.state==='wait'||r.state==='sending')){setStatus('请等待当前照片上传完成后切换档案。',true);return;}
  if(isDirty()&&!confirm('有未保存的修改，切换后这些本地修改可能丢失。仍要切换吗？'))return;
  $('pPhotos').querySelector('.shot-edit')?.remove();currentId=id;sessionStorage.setItem('collectionId',id);uploadRows=[];ocrChoice.ids=[];dirty.details=dirty.draft=dirty.target=false;renderList();show('wsLoading');
  try{doc=await apiGet(id);capabilities=await apiCapabilities().catch(e=>({identify:{available:false,reason:e.message||'能力接口不可用'},research:{available:false,scope:'公开百科背景检索',max_questions:3,max_pages:3},budget:{seconds:90,max_photos:4}}));$('wsError').classList.add('hidden');show('wsPanels');renderWorkspace();ensurePolling();}
  catch(e){$('wsErrorText').textContent=e.message;show('wsError');}
}
async function refreshOnly(){
  if(!currentId)return;
  const snap=snapshotPanel();
  try{doc=await apiGet(currentId);renderList();renderWorkspace();restorePanel(snap);ensurePolling();}
  catch(e){setStatus(e.message,true);}
}
function selectedValues(root,name){return [...root.querySelectorAll(`[name="${name}"]:checked`)].map(x=>x.value);}
function bindWorkspace(){
  $('refreshItem').onclick=async()=>{await refreshOnly();setStatus('服务器版本已重新读取，当前输入保留；核对后再保存。');};
  $('pDetails').querySelectorAll('input,textarea').forEach(x=>x.oninput=()=>{dirty.details=true;});
  $('pTarget').querySelectorAll('input').forEach(x=>x.oninput=()=>{dirty.target=true;});
  $('pDraft').querySelectorAll('input,textarea,select').forEach(x=>x.oninput=()=>{dirty.draft=true;});
  $('saveDetails').onclick=saveDetails;$('saveTarget').onclick=saveTarget;
  $('photoFiles').onchange=e=>addFiles([...e.target.files]);
  $('pPhotos').onclick=e=>{const b=e.target.closest('button');if(!b)return;
    if(b.dataset.retry!==undefined)retryUpload(+b.dataset.retry);
    if(b.dataset.act==='photoRemove')removePhoto(b.dataset.id);
    if(b.dataset.act==='photoEdit')editPhoto(b.dataset.id);
    if(b.dataset.act==='photoUp'||b.dataset.act==='photoDown')movePhoto(b.dataset.id,b.dataset.act==='photoUp'?-1:1);
  };
  $('newClaim').onclick=()=>openClaim(null);
  $('pClaims').onclick=e=>{const b=e.target.closest('[data-claim]');if(b)openClaim(b.dataset.claim);};
  $('rMode').onchange=()=>{ocrChoice.mode=$('rMode').value;};
  const lang=$('rLang');if(lang)lang.onchange=()=>{ocrChoice.language=lang.value;};
  $('pResearch').querySelectorAll('[name="ocr_photo"]').forEach(x=>x.onchange=()=>{ocrChoice.ids=selectedValues($('pResearch'),'ocr_photo');});
  $('startResearch').onclick=startResearch;$('cancelResearch').onclick=cancelResearch;
  $('pDraft').querySelectorAll('[data-draft-up]').forEach(b=>b.onclick=()=>{const row=b.closest('label'),prev=row.previousElementSibling;if(prev&&prev.tagName==='LABEL'){row.parentNode.insertBefore(row,prev);dirty.draft=true;}});
  $('genDraft').onclick=generateDraft;$('saveDraft').onclick=()=>saveDraft(false);$('confirmDraft').onclick=()=>saveDraft(true);
  $('exportBtn').onclick=doExport;
}
async function mutate(fn){try{return await fn();}catch(e){setStatus(e.status===413?'内容或文件过大':e.status===409?e.message+'；可使用顶部重新读取并保留当前输入。':e.message,true);return null;}}
async function saveDetails(){
  const payload={expected_revision:doc.revision,title:$('dTitle').value,known_info:$('dKnown').value,
    questions:$('dQuestions').value.split('\n').map(s=>s.trim()).filter(Boolean),personal_story:$('dStory').value,private_notes:$('dNotes').value};
  await mutate(async()=>{doc=await apiUpdate(doc.id,payload);dirty.details=false;renderList();renderWorkspace();setStatus('资料已保存');});
}
async function saveTarget(){
  await mutate(async()=>{doc=await apiAction(doc.id,{expected_revision:doc.revision,action:'confirm_target',label:$('tLabel').value,confirmed:$('tConfirmed').checked});dirty.target=false;renderWorkspace();});
}
async function movePhoto(pid,step){
  const ids=doc.photos.map(x=>x.id),i=ids.indexOf(pid),j=i+step;if(j<0||j>=ids.length)return;[ids[i],ids[j]]=[ids[j],ids[i]];
  await mutate(async()=>{doc=await apiAction(doc.id,{expected_revision:doc.revision,action:'reorder_photos',photo_ids:ids});renderWorkspace();});
}
function editPhoto(pid){
  const p=doc.photos.find(x=>x.id===pid),figure=[...$('pPhotos').querySelectorAll('.shot')].find(x=>x.dataset.pid===pid);if(!p||!figure)return;
  figure.querySelector('.shot-edit')?.remove();const editor=document.createElement('div');editor.className='shot-edit';
  editor.innerHTML=`<label>用途<input class="role" value="${escapeHTML(p.role)}"></label><label>说明<input class="caption" value="${escapeHTML(p.caption)}"></label><label><input type="checkbox" class="private" ${p.private?'checked':''}>私有，禁止进入公开配图</label><button type="button" class="save">保存照片信息</button><button type="button" class="cancel">取消编辑</button>`;figure.append(editor);
  editor.querySelector('.cancel').onclick=()=>{editor.remove();renderWorkspace();};
  editor.querySelector('.save').onclick=()=>mutate(async()=>{doc=await apiAction(doc.id,{expected_revision:doc.revision,action:'update_photo',photo_id:pid,role:editor.querySelector('.role').value,caption:editor.querySelector('.caption').value,private:editor.querySelector('.private').checked});editor.remove();renderWorkspace();});
}
async function removePhoto(pid){
  if(!confirm('移除这张照片？引用它的草稿会需要重新确认。'))return;
  await mutate(async()=>{doc=await apiAction(doc.id,{expected_revision:doc.revision,action:'remove_photo',photo_id:pid});renderWorkspace();});
}
function validateFile(f){
  if(f.size>10*1024*1024)return '文件超过 10MiB';
  return /\.(jpe?g|png|webp)$/i.test(f.name)?'':'仅支持 JPG、PNG、WEBP';
}
function addFiles(files){
  const itemId=doc.id;
  for(const file of files){const error=validateFile(file),rec={file,itemId,state:error?'error':'wait',message:error};uploadRows.push(rec);if(!error)enqueueUpload(rec);}
  renderWorkspace();
}
function enqueueUpload(rec){
  uploadChain=uploadChain.then(async()=>{rec.state='sending';rec.message='';if(doc?.id===rec.itemId)renderWorkspace();
    try{const reader=new FileReader();await new Promise((res,rej)=>{reader.onload=res;reader.onerror=rej;reader.readAsDataURL(rec.file);});const before=await apiGet(rec.itemId);
      const after=await request('POST',`${API}/${encodeURIComponent(rec.itemId)}/photos`,{expected_revision:before.revision,name:rec.file.name,data_base64:reader.result.split(',')[1],private:true,allow_model:false});
      rec.state='done';rec.message=after.photos.length===before.photos.length?'重复照片，未另建记录':'';if(doc?.id===rec.itemId)doc=after;
    }catch(e){rec.state='error';rec.message=e.message;}
    if(doc?.id===rec.itemId)renderWorkspace();await loadList(true);
  });
}
function retryUpload(i){const rec=uploadRows[i];if(!rec||rec.state!=='error')return;rec.state='wait';enqueueUpload(rec);renderWorkspace();}
function openClaim(id){
  modalClaim=id?(doc.claims||[]).find(c=>c.id===id):null;
  $('ceField').value=modalClaim?.field||'';$('ceText').value=modalClaim?.text||'';
  $('ceOrigin').value=modalClaim?.origin||'observation';$('ceCertainty').value=modalClaim?.certainty||'unknown';
  $('ceReview').value=modalClaim?.review||'pending';$('cePublic').checked=!!modalClaim?.public;
  $('evRows').innerHTML=(modalClaim?.evidence||[]).length?renderEvidenceRows(modalClaim.evidence):renderEvidenceRows([{}]);
  $('ceError').classList.add('hidden');$('claimModal').classList.remove('hidden');
}
function renderEvidenceRows(ev){return ev.map(e=>'<div class="ev-row"><input class="ev-title" placeholder="资料标题" value="'+escapeHTML(e.title||'')+'"><input class="ev-url" placeholder="https://..." value="'+escapeHTML(e.url||'')+'"><textarea class="ev-excerpt" rows="2" placeholder="摘录">'+escapeHTML(e.excerpt||'')+'</textarea><input class="ev-time" aria-label="访问时间 ISO" placeholder="访问时间 ISO（请填写实际访问时间）" value="'+escapeHTML(e.accessed_at||'')+'"><input class="ev-scope" placeholder="适用范围" value="'+escapeHTML(e.scope||'')+'"><input class="ev-limit" placeholder="局限（可选）" value="'+escapeHTML(e.limitations||'')+'"></div>').join('');}
function collectEvidence(){
  return [...$('evRows').querySelectorAll('.ev-row')].map(r=>({title:r.querySelector('.ev-title').value.trim(),url:r.querySelector('.ev-url').value.trim(),excerpt:r.querySelector('.ev-excerpt').value,accessed_at:r.querySelector('.ev-time').value.trim(),scope:r.querySelector('.ev-scope').value.trim(),limitations:r.querySelector('.ev-limit').value.trim()})).filter(e=>e.title||e.url||e.excerpt||e.scope);
}
async function saveClaimModal(e){
  e.preventDefault();
  const claim={id:modalClaim?.id,field:$('ceField').value.trim(),text:$('ceText').value.trim(),origin:$('ceOrigin').value,certainty:$('ceCertainty').value,review:$('ceReview').value,public:$('cePublic').checked,version:modalClaim?.version||0,evidence:collectEvidence()};
  if(!claim.field||!claim.text){$('ceError').textContent='字段和说法内容不能为空';$('ceError').classList.remove('hidden');return;}
  try{doc=await apiAction(doc.id,{expected_revision:doc.revision,action:'save_claim',claim});$('claimModal').classList.add('hidden');renderWorkspace();}
  catch(err){$('ceError').textContent=err.message;$('ceError').classList.remove('hidden');}
}
async function startResearch(){
  const mode=$('rMode').value,language=$('rLang').value==='zh'?'zh':'en';
  ocrChoice.mode=mode;ocrChoice.language=language;ocrChoice.ids=selectedValues($('pResearch'),'ocr_photo');
  const payload={expected_revision:doc.revision,action:'start_research',mode,language};
  if(mode==='identify'){if(!(capabilities?.identify?.available)){setStatus('本机 OCR 不可用：'+(capabilities?.identify?.reason||'缺少已安装 Tesseract'),true);return;}if(ocrChoice.ids.length<1||ocrChoice.ids.length>4){setStatus('请明确选择 1–4 张照片进行本地 OCR',true);return;}payload.photo_ids=ocrChoice.ids;payload.allow_external=false;}
  else{if(!$('rExternal').checked){setStatus('公开背景检索必须先明确勾选外部许可',true);return;}const qs=(doc.questions||[]).map(s=>s.trim()).filter(Boolean).slice(0,3);if(!(doc.target||{}).confirmed||!(doc.target||{}).label||!qs.length){setStatus('需先保存已确认对象名称，并保留 1–3 个问题',true);return;}payload.allow_external=true;}
  try{doc=await apiAction(doc.id,payload);renderWorkspace();ensurePolling();}catch(e){setStatus(e.message||'未能开始研究',true);try{doc=await apiGet(doc.id);renderWorkspace();}catch(_){}}
}
async function cancelResearch(){try{doc=await apiAction(doc.id,{expected_revision:doc.revision,action:'cancel_research'});stopPolling();renderWorkspace();}catch(e){setStatus(e.message,true);}}
async function generateDraft(){
  if(dirty.draft){setStatus('请先保存已编辑的草稿',true);return;}
  try{doc=await apiAction(doc.id,{expected_revision:doc.revision,action:'generate_draft',include_story:$('incStory').checked,angle:$('drAngle').value||'观察细节'});dirty.draft=false;renderWorkspace();}catch(e){setStatus(e.status===409?'已有草稿，请直接在编辑器中修改':e.message,true);}
}
async function saveDraft(confirmIt){
  if(confirmIt&&(!$('dc1').checked||!$('dc2').checked||!$('dc3').checked)){setStatus('请先完成公开隐私检查',true);return;}
  const payload={expected_revision:doc.revision,action:'save_draft',title:$('drTitle').value,body:$('drBody').value,image_ids:selectedValues($('pDraft'),'image_ids'),claim_ids:selectedValues($('pDraft'),'claim_ids'),confirmed:confirmIt,privacy_checked:confirmIt};
  try{doc=await apiAction(doc.id,payload);dirty.draft=false;renderWorkspace();setStatus(confirmIt?'草稿已确认':'草稿已保存');}catch(e){setStatus(e.status===409?'保存遇到版本冲突，已保留你输入的内容，请重新读取后再试':e.message,true);}
}
async function doExport(){
  if(!$('exCheck').checked){setStatus('导出前必须勾选隐私检查',true);return;}
  try{const r=await apiAction(doc.id,{expected_revision:doc.revision,action:'export',privacy_checked:true});window.location.href=r.download_url;await refreshOnly();}catch(e){setStatus(e.message,true);}
}
function ensurePolling(){stopPolling();if(doc&&doc.research&&doc.research.state==='running')pollTimer=setInterval(refreshOnly,3000);}
function stopPolling(){if(pollTimer){clearInterval(pollTimer);pollTimer=null;}}
function isDirty(){return dirty.details||dirty.draft||dirty.target||!!$('pPhotos').querySelector('.shot-edit');}
function init(){
  ['listLoading','listError','listBody'].forEach(id=>els[id]=$(id));
  $('listRetry').onclick=()=>loadList(true);$('wsRetry').onclick=()=>currentId&&openItem(currentId);
  $('listBody').onclick=e=>{const b=e.target.closest('[data-id]');if(b)openItem(b.dataset.id);};
  $('newForm').onsubmit=createItem;$('claimForm').onsubmit=saveClaimModal;
  $('claimCancel').onclick=()=>$('claimModal').classList.add('hidden');
  $('evAdd').onclick=()=>{const d=document.createElement('div');$('evRows').insertAdjacentText;$('evRows').innerHTML=renderEvidenceRows([...collectEvidence(),{}]);};
  window.addEventListener('beforeunload',e=>{if(isDirty()){e.preventDefault();e.returnValue='';}});
  loadList().then(()=>{const saved=sessionStorage.getItem('collectionId');if(items.some(x=>x.id===saved))openItem(saved);});
}
async function createItem(e){
  e.preventDefault();const f=e.target,title=f.title.value.trim();
  if(!title){setStatus('请填写玩具名称',true);return;}
  let token=sessionStorage.getItem('createToken');if(!token){token=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random());sessionStorage.setItem('createToken',token);}
  $('createBtn').disabled=true;
  try{
    if(isDirty()&&!confirm('创建新档案将切换工作区；放弃当前未保存的输入吗？'))return;
    doc=await apiCreate({create_token:token,title,known_info:f.known_info.value,questions:[],personal_story:'',private_notes:''});
    dirty.details=dirty.draft=dirty.target=false;$('pPhotos').querySelector('.shot-edit')?.remove();
    sessionStorage.removeItem('createToken');f.reset();await loadList(true);currentId=null;await openItem(doc.id);setStatus('档案已创建');
  }catch(err){setStatus(err.status===409?'这个创建标记已用于不同内容，请刷新页面后重试':err.message,true);}
  finally{$('createBtn').disabled=false;}
}
document.addEventListener('DOMContentLoaded',init);
})();
