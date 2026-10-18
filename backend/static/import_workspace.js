/* Private native import operations. Imported source strings are always text. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), V1 = window.V1;
  const businessId = location.pathname.split('/')[3], root = `/api/v1/businesses/${businessId}/imports`;
  const PREFIX = 'munimjee.v1.import-command:', fields = ['title','description','price','stock','options'];
  const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value,k));
  const clone = value => JSON.parse(JSON.stringify(value));
  // Facts compare semantically; immutable command serialization remains exact.
  const canonical = value => Array.isArray(value)?value.map(canonical):object(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
  const same = (a,b) => JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
  let identity = null, access = null, stopped = false, busy = false, preparing = false, command = null, blocked = false, storageKey;
  let jobs = [], candidates = [], selected = null, baseline = null, jobsCursor = null, candidateCursor = null;
  let preview = null, previewEpoch = 0, fenceGeneration = 0;
  const csvDocuments = new Map();
  let instagramAvailable=false, originalEpoch=0;
  let sessionRequest=0, sessionApplied=0, latestSession=null;
  let jobHistory = [], candidateHistory = [], candidateNext = null, timer = null, pollCount = 0, loadEpoch = 0;
  const canWrite = () => !stopped && Boolean(access?.capabilities.includes('catalogue.write'));
  function el(tag, text, className) {const node = document.createElement(tag);if(text !== undefined)node.textContent = text;if(className)node.className = className;return node;}
  async function hash(value) {const bytes = typeof value === 'string' ? new TextEncoder().encode(value) : value;return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');}
  function clearCommands() {try {for(let i=sessionStorage.length-1;i>=0;i--){const key=sessionStorage.key(i);if(key?.startsWith(PREFIX))sessionStorage.removeItem(key);}}catch(_) {}}
  function fence(message) {
    stopped = true;latestSession=null;fenceGeneration++;loadEpoch++;previewEpoch++;preview=null;clearTimeout(timer);clearCommands();command=null;selected=null;jobs=[];candidates=[];baseline=null;
    originalEpoch++;$('candidate-originals').replaceChildren();$('instagram-form').reset();$('instagram-form').hidden=true;$('instagram-status').textContent='Sign in again to check source availability.';$('workspace').hidden=true;$('access-needed').hidden=false;$('loading').hidden=true;$('business-name').textContent='PRIVATE CATALOGUE';
    $('candidate-list').replaceChildren();$('job-list').replaceChildren();$('candidate-evidence').textContent='';$('candidate-source').textContent='';$('candidate-state').textContent='';$('review-heading').textContent='Choose a candidate';$('confirmations').replaceChildren();$('recovery-facts').textContent='';$('recovery-message').textContent='';$('recovery-file').value='';$('notice').textContent='';
    $('allocation-form').reset();$('allocation-rows').replaceChildren();$('allocation-confirmations').replaceChildren();$('allocation-issues').replaceChildren();$('receipt-details').textContent='';$('bridge-note').hidden=true;$('allocation-form').hidden=true;$('allocation-status').textContent='';$('facts-form').reset();$('reject-form').reset();$('website-form').reset();$('upload-form').reset();$('csv-form').reset();csvDocuments.clear();$('csv-document').replaceChildren(new Option('Create a new named source','new'));csvMode();$('option-rows').replaceChildren();$('global-error').textContent=message;
  }
  async function session(write=false) {
    if(stopped)throw Error('Your session ended. Sign in again.');
    const sequence=++sessionRequest;
    const latest=()=>{if(write&&!canWrite())throw Object.assign(Error('Your current role is read-only. Ask a manager or owner to continue.'),{status:403});return latestSession;};
    let data;try {data=await V1.session();}catch(error){if([401,403,404].includes(error.status))fence('Your session or business access ended. Sign in again.');throw error;}
    if(stopped)throw Error('Your session ended. Sign in again.');
    if(sequence<sessionApplied)return latest();
    const membership=data.businesses?.find(b=>b.id===businessId);
    if(data.auth_method!=='v1_user'||!uuid(data.user_id)||!data.csrf_token||!membership?.capabilities?.includes('catalogue.read')) {fence('Sign in with your own V1 account for this business.');throw Error('Native business access required.');}
    const fingerprint=await hash(data.csrf_token);if(stopped)throw Error('Your session ended. Sign in again.');
    if(sequence<sessionApplied)return latest();
    if(identity && (identity.user!==data.user_id || identity.fingerprint!==fingerprint)) {fence('Your sign-in changed. Private import details were cleared. Sign in again.');throw Error('Your sign-in changed.');}
    if(!identity) {identity={user:data.user_id,fingerprint};storageKey=PREFIX+data.user_id+':'+businessId;}
    sessionApplied=sequence;latestSession=data;access=membership;$('business-name').textContent=membership.name || membership.business_name || 'PRIVATE CATALOGUE';sync();
    if(write&&!canWrite())throw Object.assign(Error('Your current role is read-only. Ask a manager or owner to continue.'),{status:403});
    return data;
  }
  async function api(path, options={}) {
    const generation=fenceGeneration,write=Boolean(options.method&&options.method!=='GET');await session(write);current(generation);
    let data;try {data=await V1.api(path,{...options,redirect:'error'});}catch(error){if(error.status===401)fence('Your session ended. Private import details were cleared. Sign in again.');else if([403,404].includes(error.status))await session();throw error;}
    await session();current(generation);return data;
  }
  function message(error, target='global-error') {if(!stopped)$(target).textContent=error.status===409 ? (['import_revision_stale','candidate_already_created'].includes(error.code)?'This record changed before the saved action was accepted. Refresh and review its current facts.':'The action result is unconfirmed. Its exact request is saved. Retry that same action; ask your business owner to review repeated conflicts.') : error.message || 'The request could not be confirmed. Refresh or retry the saved action.';}
  function sync() {
    const disabled=!canWrite()||busy||preparing||Boolean(command)||blocked;
    for(const id of ['website-fields','upload-fields','csv-fields','instagram-fields','facts-fields','approve-fields','reject-fields','allocation-fields'])$(id).disabled=disabled;
    $('instagram-fields').disabled=disabled||!instagramAvailable;$('role-note').hidden=canWrite();$('retry-command').disabled=!canWrite()||busy||!command||blocked;
    $('recovery').hidden=!command&&!blocked;
    $('jobs-previous').disabled=busy||!jobHistory.length;$('jobs-next').disabled=busy||jobs.length<50;
    $('candidates-previous').disabled=busy||!candidateHistory.length;$('candidates-next').disabled=busy||!candidateNext;
    if(selected) {
      const state=selected.candidate.state;
      $('facts-fields').disabled=disabled||!['review_required','approved'].includes(state);
      $('approve-fields').disabled=disabled||state!=='review_required';$('reject-fields').disabled=disabled||!['pending','review_required'].includes(state);
    }
    $('allocation-fields').disabled=disabled||!preview||!['needs_review','ready_for_allocation'].includes(preview.state);
    for(const button of document.querySelectorAll('.job-actions button'))button.disabled=disabled;
  }
  function validFacts(facts) {
    if(!object(facts)||fields.some(k=>!Object.hasOwn(facts,k)))return false;
    if(facts.title!==null&&(typeof facts.title!=='string'||!facts.title.trim()||facts.title.length>200))return false;
    if(facts.description!==null&&(typeof facts.description!=='string'||!facts.description.trim()||facts.description.length>4000))return false;
    if(facts.price!==null&&(!exact(facts.price,['amount','currency'])||typeof facts.price.amount!=='string'||!/^\d{1,10}(\.\d{1,2})?$/.test(facts.price.amount)||Number(facts.price.amount)<=0||Number(facts.price.amount)>999999999.99||!['INR','USD','EUR','GBP','AED'].includes(facts.price.currency)))return false;
    if(facts.stock!==null&&(!Number.isInteger(facts.stock)||facts.stock<0||facts.stock>1000000))return false;
    if(facts.options!==null&&(!Array.isArray(facts.options)||facts.options.length>8||facts.options.some(o=>!exact(o,['name','values'])||typeof o.name!=='string'||!o.name.trim()||o.name.length>80||!Array.isArray(o.values)||!o.values.length||o.values.length>30||o.values.some(v=>typeof v!=='string'||!v.trim()||v.length>80)||new Set(o.values.map(v=>v.trim().toLowerCase())).size!==o.values.length)||new Set(facts.options.map(o=>o.name.trim().toLowerCase())).size!==facts.options.length))return false;
    return true;
  }
  function validateCommand(value) {
    if(!exact(value,['version','user','business','fingerprint','created','kind','path','body','digest'])||value.version!==1||value.user!==identity.user||value.business!==businessId||value.fingerprint!==identity.fingerprint||!Number.isFinite(Date.parse(value.created))||Date.now()-Date.parse(value.created)>7*86400000||Date.parse(value.created)>Date.now()+300000) return false;
    const b=value.body;
    if(value.kind==='upload') {const csv=b?.content_type==='text/csv';return value.path==='/uploads'&&exact(b,['idempotency_key','job_key','content_type','size','sha256','name',...(csv?['document_id','document_label']:[])])&&uuid(b.idempotency_key)&&uuid(b.job_key)&&(csv?uuid(b.document_id)&&validDocumentLabel(b.document_label):['image/jpeg','image/png','video/mp4'].includes(b.content_type))&&Number.isInteger(b.size)&&b.size>0&&b.size<=(csv?256000:5000000)&&typeof b.name==='string'&&b.name.length<=255&&/^[a-f0-9]{64}$/.test(b.sha256);}
    if(value.kind!=='json'||!object(b)||!uuid(b.idempotency_key))return false;
    if(value.path==='/jobs')return b.source_authorized===true&&((exact(b,['idempotency_key','source_authorized','source_kind','source_url'])&&b.source_kind==='website'&&typeof b.source_url==='string'&&b.source_url.length<=2048&&b.source_url.startsWith('https://'))||(exact(b,['idempotency_key','source_authorized','source_kind','media_id'])&&b.source_kind==='instagram'&&typeof b.media_id==='string'&&/^[0-9]{1,64}$/.test(b.media_id))||(exact(b,['idempotency_key','source_authorized','source_kind','asset_id'])&&b.source_kind==='uploaded_media'&&uuid(b.asset_id))||(exact(b,['idempotency_key','source_authorized','source_kind','asset_id','document_id','document_label'])&&b.source_kind==='csv'&&uuid(b.asset_id)&&uuid(b.document_id)&&validDocumentLabel(b.document_label)));
    if(!Number.isInteger(b.expected_revision)||b.expected_revision<1)return false;
    if(/^\/jobs\/[0-9a-f-]{36}\/(cancel|retry)$/i.test(value.path))return exact(b,['expected_revision','idempotency_key']);
    if(/^\/candidates\/[0-9a-f-]{36}\/catalogue-draft$/i.test(value.path))return exact(b,['expected_revision','idempotency_key','seller_reviewed','confirmed_fields','allocations'])&&b.seller_reviewed===true&&Array.isArray(b.confirmed_fields)&&b.confirmed_fields.length===5&&fields.every(f=>b.confirmed_fields.includes(f))&&Array.isArray(b.allocations)&&b.allocations.length>0&&b.allocations.length<=500&&b.allocations.every(a=>exact(a,['options','stock_available','active'])&&validOptions(a.options)&&Number.isInteger(a.stock_available)&&a.stock_available>=0&&a.stock_available<=1000000&&typeof a.active==='boolean')&&new Set(b.allocations.map(a=>optionIdentity(a.options))).size===b.allocations.length;
    if(!/^\/candidates\/[0-9a-f-]{36}\/review$/i.test(value.path)||!['edit','approve','reject'].includes(b.action))return false;
    if(b.action==='edit')return exact(b,['expected_revision','idempotency_key','action','overrides'])&&Array.isArray(b.overrides)&&b.overrides.length>0&&b.overrides.length<=5&&new Set(b.overrides.map(o=>o.field)).size===b.overrides.length&&b.overrides.every(o=>exact(o,['field','value'])&&fields.includes(o.field)&&validFacts({...Object.fromEntries(fields.map(f=>[f,null])),[o.field]:o.value}));
    if(b.action==='approve')return exact(b,['expected_revision','idempotency_key','action','confirmed_fields'])&&Array.isArray(b.confirmed_fields)&&b.confirmed_fields.length===5&&fields.every(f=>b.confirmed_fields.includes(f));
    return exact(b,['expected_revision','idempotency_key','action','reason'])&&typeof b.reason==='string'&&b.reason.trim().length>0&&b.reason.length<=1000;
  }
  function readStorage() {try{return sessionStorage.getItem(storageKey);}catch(_){throw Error('Browser session storage is unavailable. Enable it and reload before sending an import action.');}}
  function current(generation) {if(stopped||generation!==fenceGeneration)throw Error('Your session ended. Sign in again.');}
  function persist(value) {current(fenceGeneration);const encoded=JSON.stringify(value);try{sessionStorage.setItem(storageKey,encoded);if(sessionStorage.getItem(storageKey)!==encoded)throw Error();}catch(_){throw Error('The action could not be preserved for recovery. No new request was sent. Enable browser session storage and reload.');}}
  function remove() {try{sessionStorage.removeItem(storageKey);if(sessionStorage.getItem(storageKey)!==null)throw Error();}catch(_){throw Error('The confirmed action could not be cleared from recovery. Keep this page open and retry after enabling browser storage.');}}
  async function decode(raw) {const generation=fenceGeneration;let value;try{value=JSON.parse(raw);}catch(_){throw Error('Saved action cannot be read. Review import activity with your business owner before starting another action.');}if(!validateCommand(value)||value.digest!==await hash(JSON.stringify([value.kind,value.path,value.body])))throw Error('Saved action is invalid, expired or belongs to a different sign-in. Review import activity with your owner before starting another action.');current(generation);return value;}
  function showRecovery() {
    if(stopped)return;
    $('recovery-message').textContent=command?'This action may already have completed. Its exact request and idempotency key are preserved for this sign-in. Retry to confirm the result. Reload never sends it automatically.':'Recovery state needs reconciliation. Review activity with your owner; no new action will be sent.';
    const b=command?.body, labels={title:'Title',description:'Description',price:'Price',stock:'Stock',options:'Options'};
    const fact=(field,value)=>value===null?'Unknown':field==='price'?value.amount+' '+value.currency:field==='options'?(value.length?value.map(option=>option.name+': '+option.values.join(', ')).join('; '):'No options'):String(value);
    let summary='';
    if(command?.kind==='upload')summary=(b.content_type==='text/csv'?'Upload product CSV\nSource: '+b.document_label:'Upload original media')+'\nFile: '+b.name+'\nType: '+({'image/jpeg':'JPEG image','image/png':'PNG image','video/mp4':'MP4 video','text/csv':'CSV product file'}[b.content_type])+'\nSize: '+b.size.toLocaleString()+' bytes';
    else if(command?.path==='/jobs')summary=b.source_kind==='instagram'?'Retrieve owned Instagram original\nMedia reference: '+b.media_id+'\nPrivate factual review required.':b.source_kind==='website'?'Start website import\nWebsite: '+b.source_url+'\nSource permission confirmed.':b.source_kind==='csv'?'Start CSV import\nSource: '+b.document_label+'\nSource permission confirmed.':'Start import from the original uploaded media.\nSource permission confirmed.';
    else if(command?.path.startsWith('/jobs/'))summary=(command.path.endsWith('/cancel')?'Cancel':'Retry')+' the selected import job.\nSaved revision: '+b.expected_revision;
    else if(command?.path.endsWith('/catalogue-draft'))summary='Create the reviewed private catalogue draft.\nSaved revision: '+b.expected_revision+'\n'+b.allocations.map(row=>(Object.entries(row.options).map(([name,value])=>name+': '+value).join(' / ')||'No options')+' — '+row.stock_available+' units · '+(row.active?'Include when this product is activated':'Do not include when this product is activated')).join('\n');
    else if(command)summary=(b.action==='edit'?'Save factual changes':b.action==='approve'?'Approve the reviewed candidate':'Reject the selected candidate')+'.\nSaved revision: '+b.expected_revision+'\n'+(b.action==='edit'?b.overrides.map(value=>labels[value.field]+': '+fact(value.field,value.value)).join('\n'):b.action==='approve'?'Confirmed facts: '+b.confirmed_fields.map(field=>labels[field]).join(', '):'Reason: '+b.reason);
    $('recovery-facts').textContent=summary;
    $('recovery-file-label').hidden=command?.kind!=='upload';sync();
  }
  async function makeCommand(kind,path,body) {
    if(stopped||command||blocked||busy||preparing)throw Error('Confirm the saved action before starting another.');preparing=true;$('notice').textContent='';sync();const generation=fenceGeneration;try {await session(true);
    const value={version:1,user:identity.user,business:businessId,fingerprint:identity.fingerprint,created:new Date().toISOString(),kind,path,body:clone(body),digest:await hash(JSON.stringify([kind,path,body]))};
    current(generation);if(!validateCommand(value))throw Error('The entered facts are outside the supported import contract.');persist(value);command=value;showRecovery();
    } finally {preparing=false;sync();}
  }
  function validJob(job) {return object(job)&&uuid(job.job_id)&&job.business_id===businessId&&['pending','running','review_required','failed','cancelled'].includes(job.state)&&Number.isInteger(job.revision)&&job.revision>0&&object(job.source)&&Number.isInteger(job.attempts)&&job.attempts>=0&&Number.isInteger(job.candidate_count)&&job.candidate_count>=0;}
  function validCandidate(record) {const c=record?.candidate;return uuid(record?.candidate_id)&&Number.isInteger(record.revision)&&record.revision>0&&c?.id===record.candidate_id&&c.provenance?.business_id===businessId&&uuid(c.provenance.import_job_id)&&object(c.provenance.source)&&['pending','review_required','approved','rejected'].includes(c.state)&&validFacts(c.extracted)&&Array.isArray(c.overrides)&&c.overrides.every(o=>fields.includes(o.field)&&validFacts({...Object.fromEntries(fields.map(f=>[f,null])),[o.field]:o.value}));}
  async function rawUpload(file) {
    const generation=fenceGeneration,b=command.body;
    if(!file||file.size!==b.size||(b.content_type==='text/csv'?csvFileType(file):file.type)!==b.content_type||await hash(await file.arrayBuffer())!==b.sha256)throw Error('Reselect the exact original file saved for this upload. Its size, type and SHA-256 must match.');
    await session(true);current(generation);
    const response=await fetch(root+'/uploads?idempotency_key='+b.idempotency_key+'&source_authorized=true',{method:'POST',body:file,headers:{'Content-Type':b.content_type,'X-CSRF-Token':V1.csrf},credentials:'same-origin',cache:'no-store',redirect:'error'});
    if(response.status===401){fence('Your session ended. Private import details were cleared. Sign in again.');throw Object.assign(Error('Session ended.'),{status:401});}
    const result=await response.json().catch(()=>({}));if(!response.ok)throw Object.assign(Error(typeof result.detail==='string'?result.detail:result.detail?.message||'The upload could not be confirmed.'),{status:response.status,code:typeof result.detail?.code==='string'?result.detail.code:null});await session();current(generation);
    if(!uuid(result.asset_id)||result.sha256!==b.sha256||result.size_bytes!==b.size||result.content_type!==b.content_type)throw Error('The upload response did not confirm the original media. Retry the saved upload.');
    const body={idempotency_key:b.job_key,source_authorized:true,source_kind:b.content_type==='text/csv'?'csv':'uploaded_media',asset_id:result.asset_id,...(b.content_type==='text/csv'?{document_id:b.document_id,document_label:b.document_label}:{})};
    const next={...command,kind:'json',path:'/jobs',body,digest:await hash(JSON.stringify(['json','/jobs',body]))};current(generation);persist(next);command=next;showRecovery();
  }
  async function sendCommand(file) {
    if(!command||blocked||busy)return;busy=true;sync();$('recovery-error').textContent='';
    try {
      await session(true);const saved=await decode(readStorage());if(JSON.stringify(saved)!==JSON.stringify(command))throw Error('Saved action changed. Reload and reconcile it before continuing.');
      if(command.kind==='upload')await rawUpload(file);
      const sent=command,viewEpoch=loadEpoch,result=await api(root+sent.path,{method:'POST',body:sent.body});
      if(sent.path==='/jobs'||sent.path.startsWith('/jobs/')) {if(!validJob(result)||(sent.path!=='/jobs'&&sent.path.split('/')[2]!==result.job_id)||(sent.path==='/jobs'&&sent.body.source_kind==='instagram'&&(result.source.kind!=='instagram'||result.source.media_id!==sent.body.media_id))||(sent.path==='/jobs'&&sent.body.source_kind==='csv'&&(result.source.kind!=='csv'||result.source.document_id!==sent.body.document_id||result.source.document_label!==sent.body.document_label||result.source.media_id!=='csv-document:'+sent.body.document_id||!/^[a-f0-9]{64}$/.test(result.source.upload_sha256))))throw Error('The response did not confirm an import job in this business. Retry the saved action.');}
      else if(sent.path.endsWith('/catalogue-draft')) {if(!validReceipt(result,sent.path.split('/')[2])||![sent.body.expected_revision,sent.body.expected_revision+1].includes(result.candidate_revision))throw Error('The response did not confirm a private draft receipt for this candidate. Retry the saved action.');}
      else if(!validCandidate(result)||result.candidate_id!==sent.path.split('/')[2]||result.revision!==sent.body.expected_revision+1)throw Error('The response did not confirm the reviewed candidate. Retry the saved action.');
      remove();command=null;$('recovery-facts').textContent='';$('recovery-file').value='';$('website-form').reset();$('upload-form').reset();$('csv-form').reset();$('instagram-form').reset();csvMode();
      if(viewEpoch===loadEpoch&&selected?.candidate_id===result.candidate_id&&sent.path.startsWith('/candidates/')&&!sent.path.endsWith('/catalogue-draft')) {selected=result;renderCandidate();}
      $('notice').textContent=sent.path.endsWith('/catalogue-draft')?'Private catalogue draft confirmed. Review it in Catalogue; activation and publication remain separate.':sent.path==='/jobs'?'Import request confirmed. Waiting for worker progress; no completion time is promised.':sent.path.startsWith('/candidates/')?'Review action confirmed. This candidate remains private.':'Job action confirmed. Refresh to check durable progress.';
      pollCount=0;await load(false);
    } catch(error) {
      // Only the server's receipt-first, pre-write stale-revision rejection
      // proves this exact action was not accepted. Bare 4xx may be intermediaries.
      if(command&&error.status===409&&(error.code==='import_revision_stale'||(command.path.endsWith('/catalogue-draft')&&error.code==='candidate_already_created'))) {const refreshReceipt=command.path.endsWith('/catalogue-draft');try{remove();command=null;}catch(storageError){blocked=true;message(storageError,'recovery-error');}if(refreshReceipt&&!blocked){try{await load(false);}catch(refreshError){message(refreshError,'allocation-error');}}}
      if(command)showRecovery();message(error,command?'recovery-error':'global-error');
    } finally {busy=false;sync();}
  }
  function sourceLabel(source) {return source.kind==='website' ? String(source.url||'Website') : source.kind==='instagram' ? 'Instagram media · '+String(source.media_id||'') : source.kind==='csv'?'CSV · '+(source.document_label||'Product source'):'Original uploaded media';}
  function validDocumentLabel(value) {return typeof value==='string'&&value.trim()===value&&value.length>0&&value.length<=100&&!/[\u0000-\u001f\u007f]/.test(value);}
  function csvFileType(file) {return file&&/\.csv$/i.test(file.name)&&['','text/csv','application/vnd.ms-excel'].includes(file.type)?'text/csv':null;}
  function csvMode() {const fresh=$('csv-document').value==='new';$('csv-name-label').hidden=!fresh;$('csv-name').required=fresh;}
  function renderDocuments() {
    const previous=$('csv-document').value;
    for(const job of jobs)if(job.source.kind==='csv'&&uuid(job.source.document_id)&&validDocumentLabel(job.source.document_label)) {
      // Bound cached history while allowing More jobs to reveal older sources.
      // Retain the seller's explicit selection across paging and polling.
      const id=job.source.document_id;
      if(!csvDocuments.has(id)&&csvDocuments.size>=200){const old=[...csvDocuments.keys()].find(key=>key!==previous);if(old)csvDocuments.delete(old);}
      csvDocuments.delete(id);csvDocuments.set(id,{label:job.source.document_label});
    }
    const select=$('csv-document');select.replaceChildren(new Option('Create a new named source','new'));
    let number=0;for(const [id,doc] of csvDocuments)select.add(new Option(doc.label+' — source '+(++number),id));
    select.value=csvDocuments.has(previous)?previous:'new';csvMode();
  }
  function jobError(code) {
    if(code==='instagram_original_unavailable')return 'Instagram did not provide a downloadable original for this media. This can happen with licensed audio. Upload an original you are authorized to use, or choose another source; reconnecting does not guarantee a download.';
    if(code==='instagram_api_error')return 'Instagram did not return a usable media response. This does not establish an authentication failure. Review source availability and current access, or use an authorized original upload.';
    if(code==='instagram_media_not_owned')return 'The requested media was not found in the checked account responses within the retrieval budget. Confirm the connected account and media ID, or upload an authorized original.';
    const match=/^csv_([a-z_]+):line_([0-9]+)(?::([a-z_]+))?$/.exec(code);
    if(!match)return code==='provider_capability_pending'?'Instagram retrieval is awaiting provider capability. Use original media or an authorized website.':'Import issue: '+code+'. Review source permission and format before retrying.';
    const reasons={size:'File must be nonempty and no larger than 256,000 bytes.',encoding:'Save the file as UTF-8 CSV.',control:'Remove unsupported control characters or embedded byte-order marks.',quoting:'Check CSV quotes and comma separators.',headers:'Use supported column names exactly, including product_ref; remove duplicates.',row_limit:'Use at most 200 product records.',column_count:'Every record must match the header column count.',field_limit:'A field exceeds its supported length.',invalid_fact:'Check the literal value against the column format.',duplicate_ref:'Each trimmed product_ref must be unique within this file.',price_currency_pair:'Supply both price and a recognized currency, or leave both blank.',no_products:'Include at least one product record.',content_type:'Select a CSV original.'};
    return 'CSV line '+match[2]+(match[3]?' · '+match[3]:'')+': '+(reasons[match[1]]||'Check the supported CSV format.')+' No candidates from this file were saved. Correct the file and start a new import for the same source.';
  }
  function renderJobs() {
    renderDocuments();
    const list=$('job-list');list.replaceChildren();if(!jobs.length)list.append(el('p','No import jobs on this page.','muted'));
    for(const job of jobs) {
      const row=el('article',undefined,'job-row');row.append(el('h3',sourceLabel(job.source)),el('p',job.state.replaceAll('_',' ')+' · '+job.candidate_count+' candidates'),el('p','Attempt '+job.attempts+' · revision '+job.revision,'hint'),el('small','Job '+job.job_id));
      if(job.state==='pending')row.append(el('p','Waiting for worker progress. Refresh to check.','hint'));
      if(job.error_code)row.append(el('p',jobError(job.error_code),'error'));
      const actions=el('div',undefined,'job-actions');
      for(const action of ['cancel','retry']) {
        const allowed=action==='cancel'?['pending','running','failed'].includes(job.state):job.state==='failed'&&job.attempts<3&&!['authorization_revoked','source_connection_changed','provider_capability_pending'].includes(job.error_code);
        if(!allowed)continue;const button=el('button',action==='cancel'?'Cancel job':'Retry job','button secondary');button.type='button';button.addEventListener('click',()=>run(async()=>{await makeCommand('json','/jobs/'+job.job_id+'/'+action,{expected_revision:job.revision,idempotency_key:crypto.randomUUID()});await sendCommand();}));actions.append(button);
      }
      if(job.state==='failed'&&job.attempts>=3)row.append(el('p','Retry limit reached. Ask your import operator to inspect the source and failure.','hint'));
      if(job.state==='failed')row.append(el('p','Eligible retries wait for server-controlled backoff; a retry request is not a completed import.','hint'));
      row.append(actions);list.append(row);
    }
    sync();
  }
  function effective(record) {const facts=clone(record.candidate.extracted);for(const override of record.candidate.overrides)facts[override.field]=clone(override.value);return facts;}
  function renderCandidates() {
    const list=$('candidate-list');list.replaceChildren();if(!candidates.length)list.append(el('p','No candidates on this page. Refresh after a job finishes extraction.','muted'));
    for(const record of candidates) {const row=el('div',undefined,'candidate-row'),button=el('button',undefined,'candidate-select');button.type='button';if(selected?.candidate_id===record.candidate_id)button.setAttribute('aria-current','true');button.append(el('strong',effective(record).title||'Untitled candidate'),el('small',record.candidate.state.replaceAll('_',' ')),el('small',sourceLabel(record.candidate.provenance.source)));button.addEventListener('click',()=>{selected=record;renderCandidate();renderCandidates();if(matchMedia('(max-width:720px)').matches)$('review-panel').scrollIntoView({behavior:'instant'});});row.append(button);list.append(row);}
    sync();
  }
  function optionRow(option={name:'',values:[]}) {const row=el('div',undefined,'option-row');const name=el('label','Option name'),input=el('input');input.name='option-name';input.maxLength=80;input.value=option.name;name.append(input);const values=el('label','Values (one per line)'),textarea=el('textarea');textarea.name='option-values';textarea.rows=3;textarea.maxLength=2500;textarea.value=option.values.join('\n');values.append(textarea);const remove=el('button','Remove option','button secondary');remove.type='button';remove.addEventListener('click',()=>{row.remove();dirty();});row.append(name,values,remove);$('option-rows').append(row);dirty();}
  function optionsMode() {const specified=$('options-mode').value==='specified';$('option-rows').hidden=!specified;$('add-option').hidden=!specified;if(specified&&!$('option-rows').children.length)optionRow();dirty();}
  function dirty() {for(const box of $('confirmations').querySelectorAll('input'))box.checked=false;}
  function readFacts() {
    const price=$('fact-price').value.trim(),stock=$('fact-stock').value;
    if($('options-mode').value==='specified'&&!$('option-rows').children.length)throw Error('Add at least one option, or explicitly choose No options after checking this product.');
    const result={title:$('fact-title').value.trim()||null,description:$('fact-description').value.trim()||null,price:price?{amount:price,currency:$('fact-currency').value}:null,stock:stock===''?null:Number(stock),options:$('options-mode').value==='unknown'?null:$('options-mode').value==='none'?[]:[...$('option-rows').children].map(row=>({name:row.querySelector('input').value.trim(),values:row.querySelector('textarea').value.split('\n').map(v=>v.trim()).filter(Boolean)}))};
    if(!validFacts(result))throw Error('Check factual values: a positive decimal price, whole stock from 0 to 1,000,000, and distinct bounded options. Blank values remain unknown.');return result;
  }
  function renderCandidate() {
    originalEpoch++;$('candidate-originals').replaceChildren();previewEpoch++;preview=null;$('allocation-form').hidden=true;$('bridge-note').hidden=true;$('allocation-rows').replaceChildren();$('allocation-confirmations').replaceChildren();$('allocation-issues').replaceChildren();$('allocation-error').textContent='';$('receipt-details').textContent='';$('review-empty').hidden=Boolean(selected);$('review-content').hidden=!selected;if(!selected)return;
    const c=selected.candidate;baseline=effective(selected);$('review-heading').textContent=baseline.title||'Untitled candidate';$('candidate-state').textContent=c.state.replaceAll('_',' ')+' · revision '+selected.revision;
    $('candidate-source').textContent=sourceLabel(c.provenance.source)+' · captured '+String(c.provenance.captured_at)+' · job '+c.provenance.import_job_id;
    $('candidate-evidence').textContent=JSON.stringify({evidence:c.provenance.evidence,source_product_id:c.provenance.source_product_id,extracted:c.extracted,seller_overrides:c.overrides},null,2);
    $('fact-title').value=baseline.title||'';$('fact-description').value=baseline.description||'';$('fact-price').value=baseline.price?.amount||'';$('fact-currency').value=baseline.price?.currency||'INR';$('fact-stock').value=baseline.stock===null?'':baseline.stock;
    $('option-rows').replaceChildren();$('options-mode').value=baseline.options===null?'unknown':baseline.options.length?'specified':'none';for(const option of baseline.options||[])optionRow(option);optionsMode();
    $('confirmations').replaceChildren();for(const field of fields){const label=el('label',undefined,'check'),box=el('input');box.type='checkbox';box.required=true;box.name='confirm-'+field;label.append(box,el('span','I checked '+field+(baseline[field]===null?' (currently unknown)':'')));$('confirmations').append(label);}
    const unknown=['title','price','stock','options'].filter(f=>baseline[f]===null);$('approval-blockers').textContent=unknown.length?'Resolve before approval: '+unknown.join(', ')+'. Unknown is not zero, untracked stock or no options.':'Check every factual field, then approve in a separate decision.';$('approve').disabled=Boolean(unknown.length);
    void loadOriginals();void loadPreview();$('facts-error').textContent='';$('review-error').textContent='';$('reject-form').reset();sync();
  }
  async function loadOriginals() {
    const epoch=originalEpoch, id=selected?.candidate_id, box=$('candidate-originals');
    if(!id)return;
    box.textContent='Checking retained originals…';
    try {
      const result=await api(root+'/candidates/'+id+'/originals');
      if(stopped||epoch!==originalEpoch||selected?.candidate_id!==id)return;
      if(result?.contract_version!=='instagram-originals.v1'||!Array.isArray(result.items)||result.items.length>10)throw Error('Original media could not be verified.');
      box.replaceChildren();
      if(!result.items.length){box.append(el('p','No retrieved Instagram original is attached to this accepted source version.','muted'));return;}
      for(const item of result.items){
        if(!uuid(item.asset_id)||item.candidate_id!==id||!['image/jpeg','image/png','video/mp4'].includes(item.content_type)||!Number.isInteger(item.size_bytes)||item.size_bytes<1||item.size_bytes>5000000)throw Error('Original media could not be verified.');
        const link=el('a','Download original '+({'image/jpeg':'JPEG','image/png':'PNG','video/mp4':'MP4'}[item.content_type])+' · '+Math.ceil(item.size_bytes/1000)+' KB','button secondary');
        link.href=root+'/candidates/'+id+'/originals/'+item.asset_id;link.download='';box.append(link);
      }
      box.append(el('p','Exact retained source bytes. Check the media independently; it does not confirm product facts or authorize publication.','hint'));
    }catch(error){if(!stopped&&epoch===originalEpoch){box.replaceChildren(el('p','Original media is unavailable or could not be verified. Refresh before relying on it.','error'));}}
  }
  async function loadInstagram() {
    try {const result=await api(root+'/sources/instagram');if(stopped)return;
      instagramAvailable=result?.contract_version==='instagram-import-readiness.v1'&&result.available===true&&result.carousel_available===false;
      $('instagram-form').hidden=!instagramAvailable;
      $('instagram-status').textContent=instagramAvailable?'Retrieve one original image or video from your connected professional account for private review.':result?.reason==='current_connection_required'?'Connect a current Instagram account in Channels before retrieval.':'Connected media retrieval awaits provider capability. No retrieval date is confirmed.';sync();
    }catch(error){if(!stopped){instagramAvailable=false;$('instagram-form').hidden=true;$('instagram-status').textContent='Retrieval availability could not be checked. Other source imports remain available.';}}
  }
  function validOptions(options) {return object(options)&&Object.keys(options).length<=8&&Object.entries(options).every(([k,v])=>k.length>0&&k.length<=64&&typeof v==='string'&&v.length>0&&v.length<=80);}
  function optionIdentity(options) {return JSON.stringify(Object.entries(options).sort(([a],[b])=>a.localeCompare(b)));}
  function combinations(facts) {
    if(['title','price','stock','options'].some(f=>facts[f]===null)||facts.price.currency!=='INR'||Math.round(Number(facts.price.amount)*100)>2000000000)return null;
    let rows=[{}];for(const option of facts.options){if(option.name.length>64||rows.length*option.values.length>500)return null;rows=rows.flatMap(row=>option.values.map(value=>({...row,[option.name]:value})));}return rows;
  }
  function validReceipt(value,id) {return object(value)&&value.contract_version==='import-catalogue.v1'&&value.creation_mode==='private_draft'&&uuid(value.receipt_id)&&value.candidate_id===id&&Number.isInteger(value.candidate_revision)&&value.candidate_revision>0&&uuid(value.product_id)&&typeof value.replayed==='boolean'&&value.catalogue_url===`/v1/businesses/${businessId}/catalogue`;}
  function validPreview(value,record) {
    if(!object(value)||value.contract_version!=='import-catalogue-preview.v1'||value.candidate_id!==record.candidate_id||value.candidate_revision!==record.revision||!['needs_review','ready_for_allocation','already_created','unsupported'].includes(value.state)||!validFacts(value.facts)||fields.some(f=>!same(value.facts[f],effective(record)[f]))||!Array.isArray(value.issues)||value.issues.length>30||value.issues.some(i=>typeof i!=='string'||i.length>4000)||!Array.isArray(value.allocations)||value.allocations.length>500)return false;
    if(value.state==='already_created')return validReceipt(value.existing,record.candidate_id)&&value.existing.candidate_revision<=record.revision;
    if(value.existing!==null||!value.allocations.every(a=>exact(a,['options','stock_available','active'])&&validOptions(a.options)&&(a.stock_available===null||Number.isInteger(a.stock_available)&&a.stock_available>=0&&a.stock_available<=1000000)&&typeof a.active==='boolean'))return false;
    const expected=combinations(value.facts);
    if(value.state==='unsupported')return value.issues.length>0;
    if(value.issues.length||!expected||!['pending','review_required','approved'].includes(record.candidate.state)||(record.candidate.state==='approved'?value.state!=='ready_for_allocation':value.state!=='needs_review'))return false;
    const identities=value.allocations.map(a=>optionIdentity(a.options));return identities.length===expected.length&&new Set(identities).size===expected.length&&expected.every(a=>identities.includes(optionIdentity(a)));
  }
  async function loadPreview() {
    const epoch=++previewEpoch,record=selected;$('allocation-status').textContent='Loading the current reviewed allocation preview…';
    try {const value=await api(root+'/candidates/'+record.candidate_id+'/catalogue-preview');if(stopped||epoch!==previewEpoch||selected!==record)return;if(!validPreview(value,record))throw Error('The allocation preview is malformed or stale. Refresh current candidate facts before continuing.');preview=value;renderPreview();}
    catch(error){if(stopped||epoch!==previewEpoch||selected!==record)return;preview=null;$('allocation-status').textContent='Allocation preview unavailable. Refresh to try again.';message(error,'allocation-error');}finally{sync();}
  }
  function renderPreview() {
    $('allocation-issues').replaceChildren();for(const issue of preview.issues)$('allocation-issues').append(el('p',issue));
    if(preview.existing){$('allocation-status').textContent='This source already has a private catalogue draft.';$('bridge-note').hidden=false;$('receipt-details').textContent='Product '+preview.existing.product_id+' · approved revision '+preview.existing.candidate_revision;$('bridge-catalogue').href=preview.existing.catalogue_url;return;}
    if(preview.state==='unsupported'){$('allocation-status').textContent='Resolve the listed facts or setup requirements, then refresh. No draft can be created yet.';return;}
    $('allocation-status').textContent=preview.allocations.length+' SKU combination'+(preview.allocations.length===1?'':'s')+' · confirmed stock '+preview.facts.stock+' · INR '+preview.facts.price.amount+'. The product remains private until separate catalogue activation.';
    for(const [i,row] of preview.allocations.entries()) {const node=el('div',undefined,'allocation-row'),name=Object.entries(row.options).map(([k,v])=>k+': '+v).join(' / ')||'No options';node.append(el('strong',name));const label=el('label','Quantity'),input=el('input');input.type='number';input.min='0';input.max='1000000';input.step='1';input.required=true;input.name='allocation-'+i;input.setAttribute('aria-label','Quantity for '+name);input.value=row.stock_available===null?'':row.stock_available;label.append(input);node.append(label);const eligible=el('label',undefined,'check allocation-eligible'),box=el('input');box.type='checkbox';box.name='allocation-active-'+i;box.checked=row.active;box.setAttribute('aria-label','Include '+name+' when this product is activated');eligible.append(box,el('span','Include when this product is activated'));node.append(eligible);$('allocation-rows').append(node);}
    for(const field of fields){const label=el('label',undefined,'check'),box=el('input');box.type='checkbox';box.required=true;box.name='allocation-confirm-'+field;label.append(box,el('span','I checked the saved '+field));$('allocation-confirmations').append(label);}
    $('allocation-form').hidden=false;allocationTotal();sync();
  }
  function readAllocations() {
    if(!preview||preview.facts.stock===null)throw Error('Unknown stock blocks draft creation. Save an explicit confirmed total first.');
    const inputs=[...$('allocation-rows').querySelectorAll('input[type=number]')];if(inputs.length!==preview.allocations.length)throw Error('Refresh the complete SKU allocation preview.');
    const allocations=inputs.map((input,i)=>{if(!/^\d+$/.test(input.value)||!Number.isInteger(Number(input.value))||Number(input.value)>1000000)throw Error('Enter a whole quantity, including explicit zero, for every combination.');return {options:clone(preview.allocations[i].options),stock_available:Number(input.value),active:$('allocation-rows').querySelector('[name=allocation-active-'+i+']').checked};});
    if(allocations.reduce((sum,a)=>sum+a.stock_available,0)!==preview.facts.stock)throw Error('Allocated stock must equal the confirmed total of '+preview.facts.stock+'.');return allocations;
  }
  function allocationTotal() {
    const inputs=[...$('allocation-rows').querySelectorAll('input[type=number]')],complete=inputs.every(input=>/^\d+$/.test(input.value)&&Number(input.value)<=1000000),sum=inputs.reduce((total,input)=>total+(Number(input.value)||0),0),valid=complete&&sum===preview?.facts.stock;
    $('allocation-total').textContent=sum+' of '+preview?.facts.stock+' units allocated'+(!complete?' · enter every quantity':valid?' · total matches':' · total must match');$('allocation-total').classList.toggle('invalid',!valid);$('create-draft').disabled=!valid;const included=[...$('allocation-rows').querySelectorAll('input[type=checkbox]')].some(box=>box.checked);$('allocation-eligibility-warning').hidden=included;$('allocation-eligibility-warning').textContent=included?'':'No combinations are included for activation. This draft will need SKU eligibility reconciliation in Catalogue before it can be activated.';
  }
  async function load(resetPoll=true) {
    if(stopped)return;if(resetPoll){pollCount=0;$('notice').textContent='Refreshed current server state. Unsaved factual changes were replaced.';}
    previewEpoch++;preview=null;sync();const epoch=++loadEpoch;const [j,c]=await Promise.all([api(root+'/jobs?limit=50'+(jobsCursor?'&after='+jobsCursor:'')),api(root+'/candidates?limit=50'+(candidateCursor?'&after='+candidateCursor:''))]);
    if(stopped||epoch!==loadEpoch)return;
    if(!Array.isArray(j)||j.length>50||!j.every(validJob)||!Array.isArray(c?.items)||c.items.length>50||!c.items.every(validCandidate)||(c.next_after!==null&&!uuid(c.next_after)))throw Error('The server returned an invalid import page. Private facts were withheld.');
    jobs=j;candidates=c.items;candidateNext=c.next_after;if(selected){selected=candidates.find(v=>v.candidate_id===selected.candidate_id)||null;}renderJobs();renderCandidates();renderCandidate();schedulePoll();
  }
  function schedulePoll() {
    clearTimeout(timer);const active=jobs.some(j=>['pending','running'].includes(j.state));
    if(!active){$('poll-status').textContent='Durable state loaded. Refresh to check for new activity.';return;}
    if(pollCount>=12||document.hidden){$('poll-status').textContent='Automatic checks paused. Use Refresh to check durable progress.';return;}
    $('poll-status').textContent='Checking durable job state for a bounded time. No completion time is promised.';
    timer=setTimeout(async()=>{if(stopped||document.hidden)return;const epoch=loadEpoch,cursor=jobsCursor;pollCount++;try{const result=await api(root+'/jobs?limit=50'+(cursor?'&after='+cursor:''));if(stopped||epoch!==loadEpoch||cursor!==jobsCursor)return;if(!Array.isArray(result)||!result.every(validJob))throw Error('Invalid job state.');jobs=result;renderJobs();}catch(error){if(stopped||epoch!==loadEpoch||cursor!==jobsCursor)return;message(error);pollCount++;}schedulePoll();},Math.min(2000*1.5**pollCount,15000));
  }
  async function run(action,target='global-error') {$(target).textContent='';try{await action();}catch(error){message(error,target);}finally{sync();}}
  $('catalogue-link').href=$('bridge-catalogue').href=`/v1/businesses/${businessId}/catalogue`;
  $('instagram-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{if(!instagramAvailable||!$('instagram-consent').checked)throw Error('Current retrieval access and explicit source permission are required.');await makeCommand('json','/jobs',{idempotency_key:crypto.randomUUID(),source_authorized:true,source_kind:'instagram',media_id:$('instagram-media').value.trim()});await sendCommand();});});
  $('website-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{if(!$('website-consent').checked)throw Error('Explicit source permission is required.');await makeCommand('json','/jobs',{idempotency_key:crypto.randomUUID(),source_authorized:true,source_kind:'website',source_url:$('website-url').value.trim()});await sendCommand();});});
  $('upload-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{const file=$('upload-file').files[0];if(!$('upload-consent').checked)throw Error('Explicit media permission is required.');if(!file||!['image/jpeg','image/png','video/mp4'].includes(file.type)||!file.size||file.size>5000000)throw Error('Choose a nonempty original JPEG, PNG or MP4 no larger than 5 MB.');await makeCommand('upload','/uploads',{idempotency_key:crypto.randomUUID(),job_key:crypto.randomUUID(),content_type:file.type,size:file.size,sha256:await hash(await file.arrayBuffer()),name:file.name.slice(0,255)});await sendCommand(file);});});
  $('csv-document').addEventListener('change',csvMode);
  $('csv-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
    const file=$('csv-file').files[0],id=$('csv-document').value,fresh=id==='new',label=fresh?$('csv-name').value.trim():csvDocuments.get(id)?.label;
    if(!$('csv-consent').checked)throw Error('Explicit permission to import this CSV is required.');
    if(!file||csvFileType(file)!=='text/csv'||!file.size||file.size>256000)throw Error('Choose a nonempty UTF-8 .csv file no larger than 256,000 bytes.');
    if(!validDocumentLabel(label)||(!fresh&&!csvDocuments.has(id)))throw Error('Name a new source or explicitly choose an existing source.');
    if(fresh&&[...csvDocuments.values()].some(doc=>doc.label===label))throw Error('This source name already appears in loaded activity. Choose that source to reimport, or use a distinct name for a separate source.');
    await makeCommand('upload','/uploads',{idempotency_key:crypto.randomUUID(),job_key:crypto.randomUUID(),content_type:'text/csv',size:file.size,sha256:await hash(await file.arrayBuffer()),name:file.name.slice(0,255),document_id:fresh?crypto.randomUUID():id,document_label:label});await sendCommand(file);
  });});
  $('retry-command').addEventListener('click',()=>run(()=>sendCommand($('recovery-file').files[0]),'recovery-error'));
  $('facts-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{const facts=readFacts(),overrides=fields.filter(f=>!same(facts[f],baseline[f])).map(field=>({field,value:facts[field]}));if(!overrides.length)throw Error('No factual changes to save.');await makeCommand('json','/candidates/'+selected.candidate_id+'/review',{expected_revision:selected.revision,idempotency_key:crypto.randomUUID(),action:'edit',overrides});await sendCommand();},'facts-error');});
  $('approve-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{if(!same(readFacts(),baseline))throw Error('Save factual changes first, then review and confirm the saved facts.');if(['title','price','stock','options'].some(f=>baseline[f]===null)||![...$('confirmations').querySelectorAll('input')].every(box=>box.checked))throw Error('Resolve unknown required facts and explicitly confirm all five factual fields.');await makeCommand('json','/candidates/'+selected.candidate_id+'/review',{expected_revision:selected.revision,idempotency_key:crypto.randomUUID(),action:'approve',confirmed_fields:fields});await sendCommand();},'review-error');});
  $('reject-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{await makeCommand('json','/candidates/'+selected.candidate_id+'/review',{expected_revision:selected.revision,idempotency_key:crypto.randomUUID(),action:'reject',reason:$('reject-reason').value.trim()});await sendCommand();},'review-error');});
  $('allocation-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{if(!preview||!['needs_review','ready_for_allocation'].includes(preview.state)||preview.candidate_id!==selected?.candidate_id||preview.candidate_revision!==selected.revision)throw Error('Refresh the current allocation preview before creating a draft.');if(!same(readFacts(),baseline))throw Error('Save factual changes first, then review the current allocations.');const allocations=readAllocations();if(![...$('allocation-confirmations').querySelectorAll('input')].every(box=>box.checked))throw Error('Explicitly confirm all five saved factual fields before creating a draft.');await makeCommand('json','/candidates/'+selected.candidate_id+'/catalogue-draft',{expected_revision:preview.candidate_revision,idempotency_key:crypto.randomUUID(),seller_reviewed:true,confirmed_fields:fields,allocations});await sendCommand();},'allocation-error');});
  $('allocation-rows').addEventListener('input',allocationTotal);
  $('facts-form').addEventListener('input',()=>{dirty();for(const box of $('allocation-confirmations').querySelectorAll('input'))box.checked=false;});$('options-mode').addEventListener('change',optionsMode);$('add-option').addEventListener('click',()=>{if($('option-rows').children.length<8)optionRow();});
  $('refresh').addEventListener('click',()=>run(()=>load()));
  for(const type of ['jobs','candidates'])for(const direction of ['previous','next'])$(type+'-'+direction).addEventListener('click',()=>run(async()=>{const isJobs=type==='jobs',history=isJobs?jobHistory:candidateHistory;let cursor=isJobs?jobsCursor:candidateCursor;if(direction==='next'){history.push(cursor);cursor=isJobs?jobs.at(-1).job_id:candidateNext;}else cursor=history.pop()||null;if(isJobs)jobsCursor=cursor;else{candidateCursor=cursor;selected=null;}await load();}));
  window.addEventListener('focus',()=>run(()=>session()));document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(timer);}else run(()=>session());});window.addEventListener('pagehide',()=>clearTimeout(timer));
  (async()=>{try{await session();const raw=readStorage();if(raw!==null){try{const generation=fenceGeneration,value=await decode(raw);current(generation);command=value;}catch(error){if(stopped)return;blocked=true;message(error,'recovery-error');}showRecovery();}await load(false);await loadInstagram();if(!stopped)$('workspace').hidden=false;}catch(error){if(storageKey&&!stopped){blocked=true;showRecovery();$('workspace').hidden=false;}message(error);}finally{$('loading').hidden=true;sync();}})();
})();
