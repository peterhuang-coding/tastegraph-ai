const $=id=>document.getElementById(id);
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL=value=>{try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:'#';}catch{return '#';}};
const apiRoot='/api/v1/editorial';
let page=1,items=[],current=null,picked=new Set(),activePack=null,reviewRows=[];
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
async function api(path,data){const r=await fetch(apiRoot+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail||d));return d;}
async function act(fn){try{await fn();}catch(e){status(e.message,true);}}
function syncPicked(){$('pickCount').textContent='已选 '+picked.size+' 张';$('create').disabled=!picked.size;}
async function loadImages(){
 const d=await api('/images?page='+page+'&limit=24&q='+encodeURIComponent($('search').value)+'&annotated='+$('onlyTagged').checked);
 items=d.items;$('grid').innerHTML=items.map(i=>'<article class="tile '+(i.id===current?'current':'')+'" data-id="'+escapeHTML(i.id)+'"><img loading="lazy" src="'+i.image_url+'" alt="原始素材"><footer><small>'+escapeHTML(i.annotation.image_form||new URL(safeURL(i.page_url),'http://localhost').hostname||'待补出处')+'</small><input type="checkbox" aria-label="加入图集" '+(picked.has(i.id)?'checked':'')+'></footer><small>'+escapeHTML(({candidate:'候选',priority:'优先',needs_context:'待补出处',excluded:'排除'})[i.annotation.availability]||'待打标')+'</small></article>').join('');
 $('pageLabel').textContent=page+' / '+Math.max(1,Math.ceil(d.total/24));$('prev').disabled=page===1;$('next').disabled=page*24>=d.total;
 document.querySelectorAll('.tile').forEach(el=>{el.onclick=e=>{if(e.target.type==='checkbox'){if(e.target.checked){if(picked.size>=18){e.target.checked=false;status('一个图集最多18张',true);return;}picked.add(el.dataset.id);}else picked.delete(el.dataset.id);syncPicked();return;}editImage(el.dataset.id);};});
 status('素材按已标注优先显示。保存标签后，下次推荐生效。');
}
function field(id,label,value='',area=false){return '<label for="'+id+'">'+label+'</label>'+(area?'<textarea id="'+id+'">'+escapeHTML(value)+'</textarea>':'<input id="'+id+'" value="'+escapeHTML(value)+'">');}
function editImage(id){
 current=id;document.querySelectorAll('.tile').forEach(el=>el.classList.toggle('current',el.dataset.id===id));
 const i=items.find(x=>x.id===id),a=i.annotation||{},dates=a.dates||{};
 $('editor').innerHTML='<h2>素材标注</h2><p><a target="_blank" rel="noreferrer" href="'+safeURL(i.page_url)+'">查看保存的来源页 ↗</a></p><p class="small">'+escapeHTML(a.actor==='assistant'?'助手样张':a.actor?'运营标注':'尚未标注')+' · 入库 '+escapeHTML(i.created_at)+'</p>'
 +field('form','画面用途',a.image_form)+field('scene','场景 / 使用关系',a.scene)+field('topic','适合讲什么',a.topic_hint)
 +'<label for="availability">运营决定</label><select id="availability">'+Object.entries({candidate:'保留为候选',priority:'优先研究',needs_context:'先补上下文',excluded:'排除常规候选'}).map(([k,v])=>'<option value="'+k+'" '+((a.availability||'candidate')===k?'selected':'')+'>'+v+'</option>').join('')+'</select>'
 +field('reason','取舍理由',a.reason,true)+field('sourceEvidence','核验出处的链接',a.source_evidence||i.page_url)
 +'<label><input type="checkbox" id="verified" '+(a.source_verified?'checked':'')+'> 已核对原图与出处</label>'
 +'<details><summary>年代与证据</summary><p class="small">未知留空。作品年份、网页日期和拍摄日期分别填写。</p>'
 +Object.entries({photo_created:'照片创作',object_original_design:'物件原设计',project_release:'项目 / 当前版本',page_published:'来源网页发表'}).map(([k,v])=>field(k,v,dates[k]?.value||'')+field(k+'Evidence','证据链接',dates[k]?.evidence_url||'')).join('')+'</details>'
 +'<details><summary>采集到的原始上下文</summary>'+((i.provenance||[]).length?(i.provenance||[]).map(p=>'<p>'+escapeHTML(p.page_title)+'</p><p class="small">图注：'+escapeHTML(p.caption||'尚无')+'<br>图片替代文字：'+escapeHTML(p.alt_text||'尚无')+'<br>作者：'+escapeHTML(p.image_author||p.page_author||'尚无')+'<br>页面类型：'+escapeHTML(({entry:'入口 / 栏目',detail:'具体作品 / 文章',unknown:'待确认'})[p.page_kind]||'待确认')+'</p>').join(''):'<p class="small">历史素材还没有逐图上下文。请先核对来源。</p>')+'</details><p><button id="saveImage" class="primary">保存标签</button></p>';
 $('saveImage').onclick=()=>act(async()=>{const values={};for(const k of ['photo_created','object_original_design','project_release','page_published'])values[k]=$(k).value.trim()?{value:$(k).value.trim(),evidence_url:$(k+'Evidence').value.trim()}:null;
 const saved=await api('/images/'+encodeURIComponent(id),{image_form:$('form').value,scene:$('scene').value,topic_hint:$('topic').value,availability:$('availability').value,reason:$('reason').value,source_evidence:$('sourceEvidence').value,source_verified:$('verified').checked,dates:values});i.annotation=saved;editImage(id);status('已保存。此记录属于素材编辑判断。');});
}
async function showPacks(){ $('imagesView').classList.add('hidden');$('packsView').classList.remove('hidden');$('tabImages').classList.remove('primary');$('tabPacks').classList.add('primary');const d=await api('/packs');$('packList').innerHTML=d.items.map(p=>'<button data-pack="'+escapeHTML(p.id)+'">'+escapeHTML(p.theme||'待定选题')+'<br><small>'+escapeHTML(p.date)+' · '+escapeHTML(({approved:'审核通过',candidate:'待审核',rejected:'已退回'})[p.editorial_status]||'待审核')+'</small></button>').join('');document.querySelectorAll('[data-pack]').forEach(b=>b.onclick=()=>act(()=>editPack(b.dataset.pack)));status('每张图都需要说明其作用；图数由内容决定。');}
async function editPack(id){const d=await api('/packs/'+encodeURIComponent(id));activePack=d;const byId=new Map((d.review.images||[]).map(r=>[r.image_id,r]));const imageIds=new Set(d.images.map(i=>i.id)); const ordered=[...(d.review.images||[]).map(r=>r.image_id).filter(id=>imageIds.has(id)),...d.images.map(i=>i.id).filter(id=>!byId.has(id))];reviewRows=ordered.map(id=>({image_id:id,role:'',evidence:'',reason:'',...byId.get(id)}));renderPack();}
function collectPack(){reviewRows.forEach((r,i)=>{for(const k of ['role','evidence','reason']){const el=$('note'+i+k);if(el)r[k]=el.value;}});activePack.review.thesis=$('thesis').value;activePack.review.sequence_reason=$('sequenceReason').value;}
function renderPack(){
 const d=activePack,r=d.review;
 $('packEditor').innerHTML='<h1>'+escapeHTML(d.pack.theme||'待定选题')+'</h1>'+field('thesis','这一组想表达什么',r.thesis||'')+field('sequenceReason','图片如何前后连接',r.sequence_reason||'',true)
 +reviewRows.map((n,i)=>'<div class="sequence-item"><div><img src="'+apiRoot+'/images/'+encodeURIComponent(n.image_id)+'/file" alt="第'+(i+1)+'张原图"><div class="row"><span>第 '+(i+1)+' 张</span><button data-move="'+i+'" data-dir="-1" '+(!i?'disabled':'')+' aria-label="上移">↑</button><button data-move="'+i+'" data-dir="1" '+(i===reviewRows.length-1?'disabled':'')+' aria-label="下移">↓</button></div></div><div>'+field('note'+i+'role','组内角色',n.role)+field('note'+i+'evidence','画面里具体能看到什么',n.evidence,true)+field('note'+i+'reason','为什么这组需要它',n.reason,true)+'</div></div>').join('')
 +'<div class="pack-head"><button id="saveDraft">保存审核草稿</button><button id="approve" class="primary">审核通过</button><button id="exportPack" '+(r.status==='approved'?'':'disabled')+'>导出原图与文案起稿</button></div><p class="small">审核通过只记录这组图的编辑决定。导出后仍需检查标题与正文。</p>';
 document.querySelectorAll('[data-move]').forEach(b=>b.onclick=()=>{collectPack();const i=+b.dataset.move,j=i+(+b.dataset.dir);[reviewRows[i],reviewRows[j]]=[reviewRows[j],reviewRows[i]];renderPack();});
 async function save(s){collectPack();const saved=await api('/packs/'+encodeURIComponent(d.pack.id)+'/review',{status:s,thesis:r.thesis,sequence_reason:r.sequence_reason,images:reviewRows});d.review=saved;renderPack();status(s==='approved'?'图集审核通过，可导出原图与文案起稿。':'审核草稿已保存。');}
 $('saveDraft').onclick=()=>act(()=>save('candidate'));$('approve').onclick=()=>act(()=>save('approved'));$('exportPack').onclick=()=>act(async()=>{const out=await api('/packs/'+encodeURIComponent(d.pack.id)+'/export',{});status('已导出：'+out.pack_path);});
}
$('tabImages').onclick=()=>{$('imagesView').classList.remove('hidden');$('packsView').classList.add('hidden');$('tabImages').classList.add('primary');$('tabPacks').classList.remove('primary');act(loadImages);};
$('tabPacks').onclick=()=>act(showPacks);$('find').onclick=()=>{page=1;act(loadImages);};$('search').onkeydown=e=>{if(e.key==='Enter')$('find').click();};$('prev').onclick=()=>{page--;act(loadImages);};$('next').onclick=()=>{page++;act(loadImages);};$('clear').onclick=()=>{picked.clear();syncPicked();act(loadImages);};
$('create').onclick=()=>act(async()=>{const d=await api('/packs',{image_ids:[...picked]});picked.clear();syncPicked();await showPacks();await editPack(d.pack_id);});
const requestedPack=new URLSearchParams(location.search).get("pack");
act(async()=>{await loadImages();if(requestedPack){await showPacks();await editPack(requestedPack);}});
