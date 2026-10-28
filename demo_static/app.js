'use strict';
const $ = (id) => document.getElementById(id);
const state = {examples: [], input: null, result: null, busy: false, status: null, layout: 'slider', split: 50, detail: {x: .5, y: .5}, images: null, version: 0, sourceTab:'featured', library:{page:1,pages:1,items:[],sequence:0,loaded:false}};
const sizeText = (w, h) => `${w} × ${h}`;
const exampleDetails = {'ex-dog':{x:.65,y:.63},'ex-bears':{x:.39,y:.44},'ex-oldphoto':{x:.59,y:.40},'ex-bridge':{x:.50,y:.44}};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('服务返回异常，请检查启动终端后重试。'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.message || '操作未完成，请重试。'));
  return data;
}
function error(message = '') { $('error').textContent = message; $('error').hidden = !message; }
function setBusy(busy) {
  state.busy = busy;
  $('run').disabled = busy || !state.input;
  $('run-label').textContent = busy ? '正在处理…' : '开始处理';
  ['mode','seed','file-input'].forEach((id) => { $(id).disabled = busy; });
  ['dataset-filter','library-search','tab-featured','tab-library','tab-upload'].forEach((id)=>{$(id).disabled=busy;});
  document.querySelectorAll('.example').forEach((button) => { button.disabled = busy; });
  updatePagination();
  $('processing-overlay').hidden = !busy;
  $('comparison').setAttribute('aria-busy', String(busy));
}
function progress(title, message) {
  $('processing-title').textContent = title;
  $('processing-message').textContent = message;
  $('process-status').textContent = message;
}
function updateModeHint() {
  const replay=$('mode').querySelector('option[value="replay"]');
  replay.disabled=!state.input?.cached;
  if(replay.disabled && $('mode').value==='replay') $('mode').value=state.status?.live_ready?'live':'bicubic';
  const hints = {
    replay: '可离线回放',
    live: state.status?.live_ready ? '4× · 单步扩散' : 'GPU 尚未就绪',
    bicubic: '4× · Bicubic'
  };
  $('mode-hint').textContent = hints[$('mode').value];
}
function clearResult() {
  state.result = null; state.images = null; state.detail = {x:.5,y:.5};
  $('comparison').classList.add('is-empty');
  document.querySelector('.visual-workspace').classList.remove('has-result');
  ['label-after','divider','slider-control','download','reset-detail','detail-marker'].forEach((id) => { $(id).hidden = true; });
  $('stat-output').textContent = '—'; $('stat-time').textContent = '—';
  $('stat-time-label').textContent = '处理耗时';
  $('result-badge').textContent = '预览'; $('result-badge').classList.remove('ai');
  $('compare-hint').textContent = '原图预览 · 处理后可滑动比较';
  $('label-before').textContent = '原图'; $('image-before').style.imageRendering = 'auto';
  $('crop-label-before').textContent = '对照图'; $('crop-label-after').textContent = '处理结果';
  $('detail-caption').textContent = '点击主图，选择你想看的细节';
  setLayout(state.layout);
}
function selectInput(input) {
  if (state.busy) return;
  state.version++; state.input = input; clearResult(); error();
  state.detail = {...(exampleDetails[input.id] || {x:.5,y:.5})};
  $('selected-title').textContent = input.title;
  $('selected-size').textContent = sizeText(input.width,input.height);
  $('stat-input').textContent = sizeText(input.width,input.height);
  $('image-before').src = input.input_url;
  $('image-before').alt = `${input.title}，输入图像`;
  document.querySelectorAll('.example').forEach((button) => {
    const selected = button.dataset.id === input.id;
    button.classList.toggle('selected',selected); button.setAttribute('aria-pressed',String(selected));
  });
  $('run').disabled = false;
  if(!$('mode').dataset.chosen) $('mode').value=input.cached?'replay':(state.status?.live_ready?'live':'bicubic');
  $('process-status').textContent = '';
  updateModeHint();
}
function imageButton(item,index=null) {
  const button=document.createElement('button');
  button.type='button';button.className='example';button.dataset.id=item.id;button.disabled=state.busy;
  const selected=state.input?.id===item.id;
  button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));
  button.setAttribute('aria-label',item.title);
  button.title=`${item.dataset || '精选'} · ${item.title} · ${sizeText(item.width,item.height)}`;
  const frame=document.createElement('div');frame.className='example-image';
  const img=document.createElement('img');img.src=item.thumbnail_url || item.input_url;img.alt='';img.decoding='async';
  if(index===null) img.loading='lazy';
  frame.append(img);
  if(item.cached){const dot=document.createElement('span');dot.className='cache-dot';dot.title='有保存结果';frame.append(dot);}
  const name=document.createElement('span');name.className='example-title';name.textContent=item.title;
  button.append(frame,name);button.addEventListener('click',()=>selectInput(item));
  return button;
}
function renderExamples() {
  $('examples').replaceChildren();
  state.examples.forEach((item,index)=>$('examples').append(imageButton(item,index)));
}
function updatePagination(){
  $('library-prev').disabled=state.busy || state.library.page<=1;
  $('library-next').disabled=state.busy || state.library.page>=state.library.pages;
}
async function loadLibrary(page=1){
  const sequence=++state.library.sequence;
  $('library-grid').classList.add('is-loading');
  const query=new URLSearchParams({dataset:$('dataset-filter').value,q:$('library-search').value,page:String(page),page_size:'18'});
  try{
    const data=await api('/api/library?'+query);
    if(sequence!==state.library.sequence)return;
    Object.assign(state.library,{page:data.page,pages:data.pages,items:data.items,loaded:true});
    $('library-grid').replaceChildren(...data.items.map(item=>imageButton(item)));
    $('library-empty').hidden=!!data.items.length;
    $('library-count').textContent=`${data.library_total} 张`;
    $('library-total').textContent=`${data.total} 张`;
    $('library-page').textContent=`${data.page} / ${data.pages}`;
    updatePagination();
  }catch(exception){if(sequence===state.library.sequence)error(exception.message);}
  finally{if(sequence===state.library.sequence)$('library-grid').classList.remove('is-loading');}
}
function setSourceTab(name,focus=false){
  state.sourceTab=name;
  ['featured','library','upload'].forEach(tab=>{
    const active=tab===name,button=$('tab-'+tab);
    button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;
    $('panel-'+tab).hidden=!active;
  });
  if(focus)$('tab-'+name).focus();
  if(name==='library' && !state.library.loaded)loadLibrary();
}
async function refreshStatus() {
  try {
    state.status = await api('/api/status');
    const ready = state.status.live_ready;
    $('machine-status').classList.toggle('ready',ready); $('machine-status').classList.toggle('warning',!ready);
    $('machine-text').textContent = ready ? 'GPU 就绪' : '离线模式';
    $('machine-status').title = `${state.status.device || 'CPU'} · ${state.status.message || ''}`;
    if (!state.busy && !$('mode').dataset.chosen) $('mode').value = state.input?.cached ? 'replay' : (ready ? 'live' : 'bicubic');
    updateModeHint();
  } catch (exception) { $('machine-text').textContent = '连接异常'; $('machine-status').title = exception.message; }
}
async function refreshExamples() {
  state.examples = await api('/api/examples'); renderExamples();
  if (state.input) {
    const refreshed = state.examples.find((item) => item.id === state.input.id);
    if (refreshed) state.input.cached = refreshed.cached;
    document.querySelectorAll('.example').forEach((button) => { const selected=button.dataset.id === state.input.id; button.classList.toggle('selected',selected); button.setAttribute('aria-pressed',String(selected)); });
  }
  updateModeHint();
}
async function upload(file) {
  if (!file || state.busy) return;
  if (file.size > 20*1024*1024) { error('图片超过 20MB。请缩小到边长 512 像素左右后再上传。'); return; }
  error(); setBusy(true); progress('正在读取图片','检查图片尺寸与格式…');
  try {
    const data = new FormData(); data.append('file',file);
    const input = await api('/api/upload',{method:'POST',body:data});
    setBusy(false); selectInput(input);
  } catch (exception) { error(exception.message); }
  finally { setBusy(false); $('file-input').value = ''; }
}
function loadImage(url) {
  return new Promise((resolve,reject) => {
    const image = new Image(); image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('结果图片加载失败。请保留终端运行后重试。')); image.src = url;
  });
}
async function showResult(result) {
  const version = state.version;
  const baseline = result.mode === 'bicubic' ? result.input_url : result.baseline_url;
  const images = await Promise.all([loadImage(baseline),loadImage(result.output_url)]);
  if (version !== state.version) return;
  state.result = result; state.images = images;
  $('image-before').src = baseline; $('image-after').src = result.output_url;
  const isAI = result.model === 'SinSR';
  const beforeLabel = isAI ? '普通插值 ×4' : '像素放大 ×4';
  const afterLabel = isAI ? 'SinSR ×4' : '普通插值 ×4';
  $('label-before').textContent = beforeLabel; $('label-after').textContent = afterLabel;
  $('image-before').alt = `${state.input.title}，${beforeLabel}`; $('image-after').alt = `${state.input.title}，${afterLabel}`;
  $('image-before').style.imageRendering = isAI ? 'auto' : 'pixelated';
  $('result-badge').textContent = result.mode === 'replay' ? 'SinSR · 已保存' : (isAI ? 'SinSR · 实时' : '普通插值');
  $('result-badge').classList.toggle('ai',isAI);
  $('comparison').classList.remove('is-empty'); document.querySelector('.visual-workspace').classList.add('has-result');
  $('label-after').hidden = false;
  $('slider-control').hidden = state.layout !== 'slider'; $('divider').hidden = state.layout !== 'slider'; $('reset-detail').hidden = false;
  $('compare-hint').textContent = '拖动分界线比较 · 点击图片观察局部';
  $('stat-input').textContent = sizeText(result.input_width,result.input_height);
  $('stat-output').textContent = sizeText(result.output_width,result.output_height);
  $('stat-time-label').textContent = result.mode === 'replay' ? '原推理耗时' : (isAI ? 'GPU 耗时' : '处理耗时');
  $('stat-time').textContent = `${Number(result.elapsed_seconds).toFixed(2)} s`;
  $('download').href = result.download_url; $('download').hidden = false;
  $('crop-label-before').textContent = beforeLabel; $('crop-label-after').textContent = afterLabel;
  $('crop-before').setAttribute('aria-label',`${beforeLabel}局部细节`);
  $('crop-after').setAttribute('aria-label',`${afterLabel}局部细节`);
  setLayout(state.layout); setSplit(50); drawDetails();
  $('process-status').textContent = result.mode === 'replay' ? '已读取保存结果' : '处理完成';
}
async function run() {
  if (!state.input || state.busy) return;
  const seed = Number($('seed').value);
  if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647) { error('随机种子应为 0–2147483647 之间的整数。'); return; }
  const mode = $('mode').value;
  if (mode === 'live' && state.status && !state.status.live_ready) { error(state.status.message || 'GPU 尚未准备好。先运行 setup_demo.ps1，或使用普通插值模式。'); return; }
  error(); setBusy(true);
  if (window.matchMedia('(max-width:720px)').matches) {
    document.querySelector('.visual-workspace').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'start'});
  }
  const displayStarted = performance.now();
  progress(mode === 'replay' ? '正在读取已保存结果' : '正在处理图片',mode === 'live' ? '首次使用需要加载模型；已加载后将直接复用。' : '结果即将显示…');
  try {
    const created = await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input_id:state.input.id,mode,seed})});
    const deadline = Date.now()+15*60*1000;
    while (true) {
      const job = await api(`/api/jobs/${encodeURIComponent(created.job_id)}`);
      if (job.status === 'done') {
        await showResult(job.result);
        $('process-status').textContent += ` · 本次 ${((performance.now()-displayStarted)/1000).toFixed(2)} 秒`;
        break;
      }
      if (job.status === 'error') throw new Error(job.message || '处理失败。请检查终端日志后重试。');
      progress(mode === 'replay' ? '正在读取已保存结果' : '正在处理图片',job.message || '请稍候…');
      if (Date.now()>deadline) throw new Error('等待超过 15 分钟。任务可能仍在运行，请检查终端或模型下载网络。');
      await new Promise((resolve) => setTimeout(resolve,mode === 'live' ? 450 : 120));
    }
    if(mode==='live'){
      state.input.cached=true;
      const libraryItem=state.library.items.find(item=>item.id===state.input.id);if(libraryItem)libraryItem.cached=true;
    }
    await refreshExamples();
    if(state.sourceTab==='library')await loadLibrary(state.library.page);
  } catch (exception) { error(exception.message); $('process-status').textContent = '本次未完成。调整设置后可重新开始。'; }
  finally { setBusy(false); }
}
function setSplit(value) {
  state.split = Math.min(100,Math.max(0,Number(value)));
  $('comparison').style.setProperty('--split',`${state.split}%`);
  $('compare-range').value = state.split; $('range-value').textContent = `${Math.round(state.split)}%`;
}
function setLayout(layout) {
  state.layout = layout; $('comparison').classList.toggle('side-view',layout === 'side' && !!state.result);
  $('view-slider').classList.toggle('active',layout === 'slider'); $('view-side').classList.toggle('active',layout === 'side');
  $('view-slider').setAttribute('aria-pressed',String(layout === 'slider')); $('view-side').setAttribute('aria-pressed',String(layout === 'side'));
  $('slider-control').hidden = !state.result || layout !== 'slider'; $('divider').hidden = !state.result || layout !== 'slider'; drawDetails();
}
function imageRect(image,box) {
  const scale = Math.min(box.width/image.naturalWidth,box.height/image.naturalHeight);
  const width=image.naturalWidth*scale,height=image.naturalHeight*scale;
  return {left:box.left+(box.width-width)/2,top:box.top+(box.height-height)/2,width,height};
}
function selectDetail(event) {
  if (!state.images || state.busy) return;
  const container=$('comparison').getBoundingClientRect(); let box=container;
  if (state.layout === 'side') { const right=event.clientX>container.left+container.width/2; box={left:container.left+(right?container.width/2:0),top:container.top,width:container.width/2,height:container.height}; }
  const rect=imageRect(state.images[1],box);
  if (event.clientX<rect.left || event.clientX>rect.left+rect.width || event.clientY<rect.top || event.clientY>rect.top+rect.height) return;
  state.detail={x:(event.clientX-rect.left)/rect.width,y:(event.clientY-rect.top)/rect.height}; drawDetails();
}
function drawDetails() {
  if (!state.images) return;
  ['crop-before','crop-after'].forEach((id,i) => {
    const canvas=$(id),context=canvas.getContext('2d'),image=state.images[i];
    let cropW=image.naturalWidth*.22,cropH=cropW*canvas.height/canvas.width;
    if (cropH>image.naturalHeight) { cropH=image.naturalHeight; cropW=cropH*canvas.width/canvas.height; }
    const sx=Math.max(0,Math.min(image.naturalWidth-cropW,state.detail.x*image.naturalWidth-cropW/2));
    const sy=Math.max(0,Math.min(image.naturalHeight-cropH,state.detail.y*image.naturalHeight-cropH/2));
    context.clearRect(0,0,canvas.width,canvas.height); context.imageSmoothingEnabled=!(state.result.mode==='bicubic' && i===0);
    context.drawImage(image,sx,sy,cropW,cropH,0,0,canvas.width,canvas.height);
  });
  $('detail-caption').textContent='同一位置 · 同一视野 · 放大观察';
  const box=$('comparison').getBoundingClientRect(),rect=imageRect(state.images[1],box),marker=$('detail-marker');
  const ratio=$('crop-after').height/$('crop-after').width;
  let fractionX=.22,fractionY=state.images[1].naturalWidth*fractionX*ratio/state.images[1].naturalHeight;
  if(fractionY>1){fractionY=1;fractionX=state.images[1].naturalHeight/ratio/state.images[1].naturalWidth;}
  const centerX=Math.max(fractionX/2,Math.min(1-fractionX/2,state.detail.x));
  const centerY=Math.max(fractionY/2,Math.min(1-fractionY/2,state.detail.y));
  marker.hidden=state.layout!=='slider';
  marker.style.width=`${rect.width*fractionX}px`;marker.style.height=`${rect.height*fractionY}px`;
  marker.style.left=`${rect.left-box.left+centerX*rect.width}px`;marker.style.top=`${rect.top-box.top+centerY*rect.height}px`;
}
async function toggleFullscreen() {
  try { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); else await document.exitFullscreen(); }
  catch { document.body.classList.toggle('presentation'); $('fullscreen').querySelector('span').textContent=document.body.classList.contains('presentation')?'退出全屏':'全屏'; requestAnimationFrame(drawDetails); }
}
$('file-input').addEventListener('change',(event)=>upload(event.target.files[0]));
for (const event of ['dragenter','dragover']) $('upload-zone').addEventListener(event,(e)=>{e.preventDefault();$('upload-zone').classList.add('dragover');});
for (const event of ['dragleave','drop']) $('upload-zone').addEventListener(event,(e)=>{e.preventDefault();$('upload-zone').classList.remove('dragover');});
$('upload-zone').addEventListener('drop',(event)=>upload(event.dataTransfer.files[0]));
$('run').addEventListener('click',run);
$('mode').addEventListener('change',()=>{$('mode').dataset.chosen='true';updateModeHint();error();});
$('compare-range').addEventListener('input',(event)=>setSplit(event.target.value));
$('view-slider').addEventListener('click',()=>setLayout('slider')); $('view-side').addEventListener('click',()=>setLayout('side'));
$('reset-detail').addEventListener('click',()=>{state.detail={...(exampleDetails[state.input?.id] || {x:.5,y:.5})};drawDetails();});
let dragging=false,dragged=false,startX=0;
$('comparison').addEventListener('pointerdown',(event)=>{
  if (!state.result || state.busy || state.layout!=='slider') return;
  startX=event.clientX;dragged=false;const box=$('comparison').getBoundingClientRect();
  if (Math.abs(event.clientX-(box.left+box.width*state.split/100))<30) {dragging=true;$('comparison').setPointerCapture(event.pointerId);}
});
$('comparison').addEventListener('pointermove',(event)=>{if(dragging){dragged ||= Math.abs(event.clientX-startX)>3;const box=$('comparison').getBoundingClientRect();setSplit((event.clientX-box.left)/box.width*100);}});
$('comparison').addEventListener('pointerup',(event)=>{dragging=false;if(!dragged)selectDetail(event);});
$('comparison').addEventListener('pointercancel',()=>{dragging=false;});
$('fullscreen').addEventListener('click',toggleFullscreen);
document.addEventListener('fullscreenchange',()=>{document.body.classList.toggle('presentation',!!document.fullscreenElement);$('fullscreen').querySelector('span').textContent=document.fullscreenElement?'退出全屏':'全屏';requestAnimationFrame(drawDetails);});
['featured','library','upload'].forEach(name=>$('tab-'+name).addEventListener('click',()=>setSourceTab(name)));
document.querySelector('.source-tabs').addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight'].includes(event.key))return;
  event.preventDefault();const tabs=['featured','library','upload'];
  const index=tabs.indexOf(state.sourceTab);setSourceTab(tabs[(index+(event.key==='ArrowRight'?1:2))%3],true);
});
$('dataset-filter').addEventListener('change',()=>loadLibrary(1));
let searchTimer;
$('library-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadLibrary(1),180);});
$('library-prev').addEventListener('click',()=>loadLibrary(state.library.page-1));
$('library-next').addEventListener('click',()=>loadLibrary(state.library.page+1));
document.addEventListener('keydown',(event)=>{
  if (/INPUT|SELECT|TEXTAREA/.test(event.target.tagName) || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key>='1' && event.key<='4' && !state.busy) {const item=state.examples[Number(event.key)-1];if(item)selectInput(item);}
  if(event.key==='Enter' && !['BUTTON','A','SUMMARY'].includes(event.target.tagName)){event.preventDefault();run();}
  if(event.key.toLowerCase()==='f'){event.preventDefault();toggleFullscreen();}
  if(event.target.id==='comparison' && ['ArrowLeft','ArrowRight'].includes(event.key) && state.result){event.preventDefault();setSplit(state.split+(event.key==='ArrowLeft'?-5:5));}
});
window.addEventListener('resize',drawDetails);
(async function init(){
  try {await refreshExamples();if(state.examples.length)selectInput(state.examples[0]);$('mode').value=state.examples.some((item)=>item.cached)?'replay':'bicubic';updateModeHint();}
  catch(exception){error(exception.message);}
  refreshStatus();
  loadLibrary();
})();
