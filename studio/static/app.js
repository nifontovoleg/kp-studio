const $ = id => document.getElementById(id);
let uploadId = null;
let goodCount = 0;
let busy = false;
let pollTimer;
const rubles = new Intl.NumberFormat('ru-RU', {style:'currency',currency:'RUB',maximumFractionDigits:0});
function message(text, kind='') { $('message').hidden = !text; $('message').textContent = text; $('message').className = 'message ' + kind; }
function setBusy(value) { busy=value; $('file').disabled=value; $('example').disabled=value; $('generate').disabled=value || !uploadId || !goodCount; document.querySelectorAll('[name=mode]').forEach(el=>el.disabled=value); $('generate').textContent=value?'Генерация идёт…':'Создать предложения'; }
async function jsonRequest(path,options={}) { const response=await fetch(path,options); const result=await response.json(); if(!response.ok) throw new Error(result.error || 'Не удалось выполнить запрос.'); return result; }
async function checkFile(file) {
  if (!file || busy) return;
  uploadId=null;goodCount=0;setBusy(true);$('results-section').hidden=true;message('Проверяем таблицу…','busy');
  try {
    const result=await jsonRequest('/api/check?name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Studio-Request':'1'},body:file});
    uploadId=result.upload_id;goodCount=result.clients.length;$('filename').textContent=file.name;$('clientcount').textContent=`Готово к обработке: ${goodCount}`;
    $('clients').replaceChildren();
    for(const client of result.clients) {
      const tr=document.createElement('tr');const info=document.createElement('td');const name=document.createElement('strong');name.textContent=client.company;const contact=document.createElement('small');contact.textContent=client.contact;info.append(name,contact);
      const needs=document.createElement('td');needs.textContent=client.needs;const budget=document.createElement('td');budget.className='amount';budget.textContent=rubles.format(client.budget);tr.append(info,needs,budget);$('clients').append(tr);
    }
    $('empty').hidden=!!goodCount;$('tablewrap').hidden=!goodCount;$('validation').replaceChildren();$('validation').hidden=!result.errors.length;
    for(const error of result.errors){const p=document.createElement('p');p.textContent=`Строка ${error.row}: ${error.error}`;$('validation').append(p);}
    message(result.errors.length ? `Таблица проверена. Ошибок: ${result.errors.length}. Корректные строки можно обработать; ошибочные будут отмечены в журнале.` : 'Таблица проверена. Можно создавать предложения.',result.errors.length?'error':'');
  } catch(error) { $('clientcount').textContent='Таблица не загружена';$('empty').hidden=false;$('tablewrap').hidden=true;$('validation').hidden=true;message(error.message,'error'); }
  finally {setBusy(false);}
}
$('file').addEventListener('change',event=>checkFile(event.target.files[0]));
$('example').addEventListener('click',async()=>{try{const response=await fetch('/api/example');if(!response.ok)throw new Error('Не удалось загрузить пример.');await checkFile(new File([await response.blob()],'Пример клиентов.csv'));}catch(error){message(error.message,'error');}});
document.querySelectorAll('[name=mode]').forEach(el=>el.addEventListener('change',()=>{$('modehint').textContent=el.value==='demo'?'В демо PDF будут помечены как демонстрационные.':'Данные таблицы будут переданы ProxyAPI. Запросы оплачиваются с вашего баланса.';}));
$('generate').addEventListener('click',async()=>{
  if(busy||!uploadId)return;
  setBusy(true);$('results-section').hidden=true;
  const mode=document.querySelector('[name=mode]:checked').value;
  message(mode==='demo'?'Создаём демонстрационные PDF…':'AI готовит предложения. Дождитесь результата; не закрывайте окно запуска.','busy');
  try{await jsonRequest('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Request':'1'},body:JSON.stringify({upload_id:uploadId,mode})});await poll();}catch(error){message(error.message,'error');setBusy(false);}
});
async function poll() {
  clearTimeout(pollTimer);
  try {
    const {job}=await jsonRequest('/api/status');
    if(!job)return;
    if(job.status==='running'){setBusy(true);pollTimer=setTimeout(poll,700);return;}
    setBusy(false);
    const success=job.success||0,failed=job.failed||0;
    message(job.error || (job.status==='completed'?`Готово. Создано документов: ${success}.`:job.status==='partial'?`Создано документов: ${success}. Не обработано: ${failed}. Проверьте ошибки ниже.`:'Предложения не созданы. Причина указана ниже.'),job.status==='completed'?'':'error');
    $('results-section').hidden=false;$('resultcount').textContent=`Создано: ${success} · Ошибок: ${failed}`;$('results').replaceChildren();
    $('results-title').textContent=success?'Готовые документы':'Результат обработки';
    $('resultnote').textContent=job.mode==='demo'?'Демонстрация: текст из локального шаблона, без AI.':success?'Предложения подготовлены с помощью AI. Проверьте содержание перед отправкой.':'AI-предложения не созданы. Исправьте причину ошибки и повторите обработку.';
    for(const entry of job.results||[]){
      const li=document.createElement('li');const info=document.createElement('div');const strong=document.createElement('strong');strong.textContent=entry.company||`Строка ${entry.row}`;const detail=document.createElement('small');detail.textContent=entry.status==='ok'?'PDF сохранён в папке компании':entry.error;if(entry.status!=='ok')detail.className='error';info.append(strong,detail);li.append(info);
      if(entry.download){const a=document.createElement('a');a.href=entry.download;a.className='download';a.download='Предложение.pdf';a.textContent='Скачать PDF';li.append(a);}$('results').append(li);
    }
  } catch(error) {setBusy(false);message('Связь с локальной программой потеряна. Проверьте окно запуска и обновите страницу.','error');}
}
poll();
