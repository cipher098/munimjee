'use strict';
(() => {
  const $ = id => document.getElementById(id), businessId = location.pathname.split('/')[3];
  const api = `/api/v1/businesses/${encodeURIComponent(businessId)}/channels`;
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const prefix = 'munimjee.v1.channel-command:', MAX_AGE = 86400000;
  let capabilities = new Set(), cursor = null, cursors = [], nextCursor = null, selected = null, busy = false;
  let ended = false, preparing = false, context = null, latestSession = null, sessionRequest = 0, sessionApplied = 0, epoch = 0;
  let listVersion = 0, detailVersion = 0, connectionVersion = 0, connections = [], pending = null, blocked = false, journalKey = null, reviewedVersion = null;
  const labels = {error:'Needs review', pending:'Waiting', retry:'Retry queued', processing:'Processing', completed:'Handled', resolved:'Closed after review', access_verified:'Access verified', paused:'Sending paused', not_checked:'Not checked', setup_needed:'Setup needed', disconnected:'Not connected', needs_reconnect:'Reconnect needed'};
  const node = (tag, text, className) => {const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n;};
  const date = value => value ? new Date(value).toLocaleString(undefined, {dateStyle:'medium',timeStyle:'short'}) : 'Not available';
  const exact = (value, fields) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === fields.length && fields.every(k => Object.hasOwn(value,k));
  const digest = async value => [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(n=>n.toString(16).padStart(2,'0')).join('');
  const failure = (message,status=0) => Object.assign(new Error(message),{status});
  function eraseDialogs() {
    for (const id of ['review-dialog','wa-dialog','confirm-dialog']) $(id).close();
    $('wa-form').reset(); $('review-form').reset(); $('confirm-action').onclick = null; selected = null; detailVersion++;
    for (const id of ['review-meta','review-reason','review-components','review-history','review-error','replay-block','view-only','wa-error','confirm-title','confirm-description']) $(id).replaceChildren();
  }
  function erasePrivate() {
    epoch++; listVersion++; connectionVersion++; eraseDialogs(); connections = [];
    for (const id of ['receipt-rows','connections-list','global-status','command-message','command-current']) $(id).replaceChildren();
    $('business-name').textContent = 'Your business'; $('page-label').textContent = ''; $('table-wrap').hidden = true;
    $('channel-workspace').hidden = true; $('command-recovery').hidden = true; $('command-confirm').checked = false;
    $('next').disabled = $('previous').disabled = true; cursor = nextCursor = null; cursors = [];
  }
  function closeAccess(message) {
    if (ended) return;
    ended = true; erasePrivate(); latestSession = null; context = null; capabilities.clear();
    try {if (journalKey) sessionStorage.removeItem(journalKey);} catch (_) {}
    pending = null; blocked = true; $('refresh').disabled = true; $('logout').hidden = true;
    $('access-needed').hidden = false; $('access-message').textContent = message; $('global-error').textContent = message;
  }
  async function identity(capability='inbox.read') {
    if (ended) throw failure('Your access ended. Sign in again.',401);
    const sequence = ++sessionRequest;
    let data;
    try {data = await window.V1.session();} catch (error) {if (error.status === 401) closeAccess('Your session ended. Sign in again.'); throw error;}
    if (ended) throw failure('Your access ended.',401);
    if (!data || data.auth_method !== 'v1_user' || typeof data.user_id !== 'string' || !UUID.test(data.user_id) || typeof data.csrf_token !== 'string' || data.csrf_token.length < 16 || !Array.isArray(data.businesses)) {
      closeAccess('Native sign-in could not be checked. Sign in again.'); throw failure('Native sign-in required.',401);
    }
    const fingerprint = await digest(data.csrf_token);
    if (ended) throw failure('Your access ended.',401);
    if (sequence >= sessionApplied) {
      const business = data.businesses.find(item => item.id === businessId);
      if (!business || !Array.isArray(business.capabilities) || !business.capabilities.includes('inbox.read')) {
        closeAccess('This business is unavailable with your current access.'); throw failure('Business access ended.',403);
      }
      if (context && (context.user !== data.user_id || context.session !== fingerprint)) {
        closeAccess('Your sign-in changed. Reopen channels from your business.'); throw failure('Your sign-in changed.',401);
      }
      const next = {user:data.user_id,session:fingerprint,business,capabilities:new Set(business.capabilities)};
      if (context && [...capabilities].sort().join('|') !== [...next.capabilities].sort().join('|')) {
        epoch++; eraseDialogs(); $('connections-list').replaceChildren(); $('command-current').replaceChildren();
      }
      context = next; capabilities = next.capabilities; latestSession = next; sessionApplied = sequence;
      journalKey = `${prefix}${next.user}:${businessId}:${next.session}`;
    }
    if (ended || !latestSession) throw failure('Your access ended.',401);
    if (!latestSession.capabilities.has(capability)) throw failure('Your current role cannot perform this action.',403);
    return latestSession;
  }
  async function request(path, options={}, capability='inbox.read') {
    await identity(capability);
    if (ended) throw failure('Your access ended. No request was sent.',401);
    const generation = epoch;
    try {
      const result = await window.V1.api(path,options);
      await identity(capability);
      if (ended || generation !== epoch) throw failure('Your access changed. Refresh status before continuing.');
      return result;
    } catch (error) {
      if (error.status === 401) closeAccess('Your session ended. Sign in again.');
      else if (!options.method || options.method === 'GET') {if (!ended) {erasePrivate(); $('global-error').textContent=error.message;}}
      throw error;
    }
  }
  const actionCapability = action => action === 'instagram_receipt_review' || action.startsWith('automation_') ? 'automation.manage' : action.startsWith('disconnect_') ? 'channels.disconnect' : 'channels.connect';
  const actions = new Set(['instagram_receipt_review','disconnect_instagram','disconnect_whatsapp','verify_instagram','verify_whatsapp','automation_instagram','automation_whatsapp','connect_whatsapp','start_instagram']);
  function validCommand(command) {
    if (!exact(command,['action','path','body','version','secret']) || !actions.has(command.action) || typeof command.path !== 'string' || typeof command.secret !== 'boolean' || !command.body || typeof command.body !== 'object' || Array.isArray(command.body) || typeof command.body.idempotency_key !== 'string' || !UUID.test(command.body.idempotency_key)) return false;
    const body = command.body;
    if (command.action === 'connect_whatsapp') return command.secret === true && exact(body,['idempotency_key','waba_id','phone_number_id']) && [body.waba_id,body.phone_number_id].every(x=>typeof x==='string'&&/^[0-9]{1,40}$/.test(x)) && Number.isSafeInteger(command.version) && command.version >= 0 && command.version <= 2000000000 && command.path === '/whatsapp/connect';
    if (command.secret || command.version !== null) return false;
    if (command.action === 'instagram_receipt_review') return /^\/instagram\/receipts\/[0-9a-f-]{36}\/review$/.test(command.path) && exact(body,['idempotency_key','decision','reviewed','reason','expected_updated_at']) && ['resolve','replay'].includes(body.decision) && body.reviewed === true && typeof body.reason === 'string' && body.reason.length >= 10 && body.reason.length <= 500 && typeof body.expected_updated_at === 'string' && body.expected_updated_at.length <= 64;
    if (command.action.startsWith('automation_')) return exact(body,['idempotency_key','enabled']) && typeof body.enabled === 'boolean' && command.path === `/${command.action.slice(11)}/automation`;
    const action = command.action === 'start_instagram' ? 'connect' : command.action.split('_')[0], channel = command.action === 'start_instagram' ? 'instagram' : command.action.split('_')[1];
    return exact(body,['idempotency_key']) && command.path === `/${channel}/${action}`;
  }
  function recovery() {
    if (ended) return;
    const canAct = pending && capabilities.has(actionCapability(pending.action));
    $('command-recovery').hidden = !pending && !blocked;
    $('command-message').textContent = busy ? 'Checking the saved action. Do not submit another action while its result is being checked.' : blocked ? 'A saved action cannot safely be recovered. No new action will be sent. Sign out and reopen this workspace.' : pending ? pending.secret ? 'A credential-save result is uncertain. The password was erased. Checking current status cannot prove which secret was saved. Review the current connection and explicitly re-enter credentials to replace it.' : 'An earlier action needs checking. Retry only the saved action with its original details and key.' : '';
    $('command-retry').hidden = !canAct || pending.secret; $('command-retry').disabled = busy;
    $('command-check').hidden = !canAct || !pending.secret; $('command-check').disabled = busy;
    $('command-confirm-label').hidden = !canAct || !pending.secret || reviewedVersion === null;
    $('command-replace').hidden = $('command-confirm-label').hidden; $('command-replace').disabled = busy || !$('command-confirm').checked;
    document.querySelectorAll('#connections-list button').forEach(button=>button.disabled=ended || preparing || busy || blocked || Boolean(pending));
  }
  async function recover() {
    if (ended || !context) return;
    try {
      const raw = sessionStorage.getItem(journalKey); if (raw === null) return;
      if (raw.length > 8192) throw Error();
      const saved = JSON.parse(raw);
      if (!exact(saved,['user','business','session','created_at','command','checksum']) || saved.user !== context.user || saved.business !== businessId || saved.session !== context.session || !Number.isSafeInteger(saved.created_at) || saved.created_at > Date.now()+60000 || Date.now()-saved.created_at > MAX_AGE || !validCommand(saved.command)) throw Error();
      const {checksum,...core} = saved, actual = await digest(JSON.stringify(core));
      if (ended) return;
      if (actual !== checksum) throw Error();
      pending = saved.command;
    } catch (_) {blocked = true;}
    recovery();
  }
  async function saveCommand(command) {
    if (preparing || pending || blocked || busy || !validCommand(command)) throw failure('Check the earlier action before starting another one.');
    preparing = true; recovery(); updateReviewButtons();
    try {
    await identity(actionCapability(command.action));
    const core = {user:context.user,business:businessId,session:context.session,created_at:Date.now(),command};
    const encoded = JSON.stringify({...core,checksum:await digest(JSON.stringify(core))});
    await identity(actionCapability(command.action));
    if (ended || core.user !== context.user || core.session !== context.session) throw failure('Your sign-in changed.');
    try {sessionStorage.setItem(journalKey,encoded); if (sessionStorage.getItem(journalKey) !== encoded) throw Error();}
    catch (_) {blocked = true; recovery(); throw failure('Recovery storage is unavailable. No action was sent.');}
    pending = command;
    } finally {preparing = false; recovery(); updateReviewButtons();}
  }
  function clearCommand() {
    try {sessionStorage.removeItem(journalKey); if (sessionStorage.getItem(journalKey) !== null) throw Error();}
    catch (_) {blocked = true; throw failure('The acknowledgement was received, but recovery state could not be cleared. Reopen this workspace before another action.');}
    pending = null; reviewedVersion = null; $('command-current').replaceChildren(); $('command-confirm').checked = false; recovery();
  }
  async function dispatch(command, secret=null) {
    if (ended || blocked || busy || pending !== command) throw failure('The saved action is unavailable.');
    busy = true; recovery(); updateReviewButtons();
    let body = command.secret ? {...command.body,access_token:secret} : command.body;
    try {
      if (command.secret && (typeof secret !== 'string' || secret.length < 10)) throw failure('Re-enter credentials after reviewing the current connection.');
      const result = await request(api+command.path,{method:'POST',body,headers:command.version === null ? {} : {'X-Channel-Version':String(command.version)}},actionCapability(command.action));
      if (!result || result.business_id !== businessId || result.idempotency_key !== command.body.idempotency_key || result.action !== command.action) throw failure('The acknowledgement could not be verified.');
      const allowed = command.action.startsWith('disconnect_') ? ['disconnected'] : command.action.startsWith('verify_') ? ['verified','needs_reconnect'] : command.action.startsWith('automation_') ? ['enabled','paused'] : command.action === 'connect_whatsapp' ? ['paused','connection_failed'] : command.action === 'start_instagram' ? ['authorization_started'] : ['resolved','retry'];
      if (!allowed.includes(result.status)) throw failure('The action state could not be verified.');
      if (command.action === 'instagram_receipt_review' && (result.receipt_id !== command.path.split('/')[3] || result.delivery_confirmed !== false || result.queued !== (command.body.decision === 'replay'))) throw failure('The review acknowledgement could not be verified.');
      if (command.action === 'start_instagram') {
        const target = new URL(result.authorization_url);
        if (target.protocol !== 'https:' || target.hostname !== 'www.instagram.com' || target.pathname !== '/oauth/authorize' || target.username || target.password || target.hash || typeof result.attempt_id !== 'string' || !UUID.test(result.attempt_id)) throw failure('The authorization address could not be verified.');
      }
      if (command.secret && result.status !== 'connection_failed' && (result.status !== 'paused' || !Number.isSafeInteger(result.connection_version) || result.connection_version <= command.version)) throw failure('The credential acknowledgement could not be verified.');
      clearCommand(); $('global-status').textContent = result.message || 'Action acknowledged. Check current status below.';
      try {await loadConnections(); await loadList();} catch (error) {if (!ended) {$('global-status').textContent = 'Action acknowledged. Current status could not be checked.'; $('global-error').textContent = error.message;}}
      return result;
    } catch (error) {
      if (!ended && error.code === 'channel_generation_stale' && command.secret) {
        clearCommand(); $('global-error').textContent = 'The connection changed before this save. Refresh status and review it before re-entering credentials.';
      } else if (!ended) {$('global-error').textContent = 'The result is uncertain. Keep the saved action until it can be checked. '+error.message;}
      throw error;
    } finally {body = null; secret = null; $('wa-form').reset(); busy = false; if (!ended) {recovery(); updateReviewButtons();}}
  }
  async function command(action,path,body,secret=null,version=null) {
    const saved = {action,path,body:secret === null ? body : {idempotency_key:body.idempotency_key,waba_id:body.waba_id,phone_number_id:body.phone_number_id},version,secret:secret !== null};
    await saveCommand(saved); return dispatch(saved,secret);
  }
  function showTab(name) {const review = name === 'review'; $('review-section').hidden = !review; $('connections-section').hidden = review; document.querySelectorAll('[data-tab]').forEach(button => button.dataset.tab === name ? button.setAttribute('aria-current','page') : button.removeAttribute('aria-current'));}
  async function loadList() {
    const version = ++listVersion; $('next').disabled = $('previous').disabled = true;
    try {
      const params = new URLSearchParams({status:$('status-filter').value,limit:'20'}); if (cursor) params.set('cursor',cursor);
      const data = await request(`${api}/instagram/receipts?${params}`);
      if (ended || version !== listVersion) return;
      if (!data || !Array.isArray(data.items) || data.items.length > 20 || !(data.next_cursor === null || typeof data.next_cursor === 'string')) throw failure('Saved messages could not be checked.');
      nextCursor = data.next_cursor; $('receipt-rows').replaceChildren();
      for (const item of data.items) {
        const row = node('tr'), message = node('td'), received = node('td'), status = node('td'), action = node('td');
        message.append(node('strong',`Customer •${item.customer_ref}`),node('span',item.message_preview || (item.kinds.includes('image') ? 'Customer sent an image' : 'Customer shared media'),'message-preview'),node('small',item.reason));
        received.append(node('time',date(item.created_at))); status.append(node('span',labels[item.status] || item.status,`badge ${item.status}`));
        const button = node('button',item.status === 'error' ? 'Review message' : 'View details','button secondary'); button.type='button'; button.addEventListener('click',()=>openReview(item.id)); action.append(button); row.append(message,received,status,action); $('receipt-rows').append(row);
      }
      $('table-wrap').hidden = !data.items.length; $('list-state').hidden = Boolean(data.items.length); $('list-state').textContent = 'No saved messages match this status.';
      if (!data.items.length && $('status-filter').value === 'error') $('list-state').textContent = 'No messages need review. New held items will appear here.';
      $('next').disabled = !nextCursor; $('previous').disabled = !cursors.length; $('page-label').textContent = `Page ${cursors.length+1}`;
    } catch (error) {if (!ended && version === listVersion) {erasePrivate(); $('global-error').textContent = error.message;}}
  }
  async function openReview(id) {
    const version = ++detailVersion;
    try {
      const data = await request(`${api}/instagram/receipts/${encodeURIComponent(id)}`);
      if (ended || version !== detailVersion) return;
      if (!data || data.id !== id || !Array.isArray(data.components) || !Array.isArray(data.history) || typeof data.can_review !== 'boolean') throw failure('The message could not be checked.');
      selected = data; $('review-meta').textContent = `Customer •${data.customer_ref} · ${date(data.created_at)} · ${labels[data.status] || data.status}`;
      $('review-reason').textContent = data.reason; $('review-components').replaceChildren();
      data.components.forEach(item=>{const box=node('div',null,'message-component'); box.append(node('small',`${item.kind === 'text' ? 'Customer message' : item.kind === 'image' ? 'Image attachment' : 'Shared media'} · ${item.handled ? 'Handled' : 'Saved'}`),node('p',item.text || 'An attachment was recorded. Check the original conversation in Instagram.')); $('review-components').append(box);});
      $('review-form').reset(); $('review-error').textContent = ''; $('replay-block').textContent = data.replay_block_reason ? `Retry unavailable: ${data.replay_block_reason}` : 'A retry is a new attempt, subject to checks again when processing starts.';
      $('review-form').hidden = !data.can_review || !capabilities.has('automation.manage'); $('view-only').hidden = !$('review-form').hidden; $('view-only').textContent = 'Your role or this item’s state does not allow a review action here.';
      $('review-history').replaceChildren(); if (!data.history.length) $('review-history').append(node('p','No operator decision has been recorded yet.','muted'));
      data.history.forEach(item=>{const entry=node('div',null,'audit-entry'); entry.append(node('strong',item.action === 'ingress_resolve' ? 'Closed without retry' : 'Retry requested'),node('p',item.reason),node('small',`${date(item.created_at)} · Reviewer •${item.actor_id.slice(-6)}`)); $('review-history').append(entry);});
      updateReviewButtons(); $('review-dialog').showModal();
    } catch (error) {if (!ended) {eraseDialogs(); $('global-error').textContent = error.message;}}
  }
  function updateReviewButtons() {const enabled = !ended && !preparing && !busy && !pending && !blocked && capabilities.has('automation.manage') && $('review-confirm').checked && $('review-note').value.trim().length >= 10; $('resolve').disabled = !enabled; $('replay').disabled = !enabled || Boolean(selected?.replay_block_reason);}
  function confirmAction(title,description,action) {
    if (ended || pending || blocked || busy) {recovery(); return;}
    $('confirm-title').textContent=title; $('confirm-description').textContent=description; $('confirm-action').disabled=false;
    $('confirm-action').onclick=async()=>{if (ended || busy) return; $('confirm-action').disabled=true; try {await action(); if (!ended) $('confirm-dialog').close();} catch(error) {if (!ended) $('confirm-description').textContent=error.message;} finally {if (!ended) $('confirm-action').disabled=false;}};
    $('confirm-dialog').showModal();
  }
  async function channelAction(channel,action,extra={}) {return command(`${action}_${channel}`,`/${channel}/${action}`,{idempotency_key:crypto.randomUUID(),...extra});}
  async function loadConnections() {
    const version=++connectionVersion;
    const data=await request(api);
    if (ended || version !== connectionVersion) return;
    if (!data || data.business_id !== businessId || typeof data.business_name !== 'string' || !Array.isArray(data.channels) || data.channels.length !== 2 || new Set(data.channels.map(x=>x.channel)).size !== 2 || data.channels.some(x=>!['instagram','whatsapp'].includes(x.channel)||!Number.isSafeInteger(x.connection_version)||x.connection_version<0)) throw failure('Current connections could not be checked.');
    connections=data.channels; $('business-name').textContent=data.business_name; $('connections-list').replaceChildren(); $('channel-workspace').hidden=false; $('logout').hidden=false;
    for (const item of connections) {
      const row=node('section',null,'channel-row'),info=node('div'),heading=node('h3',item.channel === 'instagram' ? 'Instagram' : 'WhatsApp'),buttons=node('div',null,'channel-actions');
      heading.append(node('span',labels[item.status] || item.status,'badge')); info.append(heading);
      const descriptions={disconnected:'Connect an account you own or are authorized to manage.',needs_reconnect:'Reconnect and check access before enabling sending.',not_checked:'Account details are saved. Check current account access.',paused:'Account access is saved. Sending is paused.',setup_needed:'Account details are saved, but this app’s webhook configuration is incomplete.',access_verified:'Account access was verified. Message delivery and provider approvals need separate checks.'};
      info.append(node('p',descriptions[item.status] || 'Check this connection before enabling sending.','muted'),node('p',`${item.account_hint ? `Account ${item.account_hint} · ` : ''}Last access check: ${date(item.checked_at)}`,'channel-detail'),node('p',`Webhook configuration: ${item.webhook_configured ? 'present' : 'missing'} · Provider approval: not evaluated · Message test: not performed here`,'channel-detail'));
      const add=(label,action,primary=false)=>{const b=node('button',label,`button ${primary ? 'primary' : 'secondary'}`); b.type='button'; b.disabled=Boolean(pending || blocked || busy); b.addEventListener('click',async()=>{if (ended || pending || blocked || busy) return; b.disabled=true; try {await action();} catch(error) {if (!ended) $('global-error').textContent=error.message;} finally {if (!ended) b.disabled=Boolean(pending || blocked || busy);}}); buttons.append(b);};
      if (capabilities.has('channels.connect')) {
        add(item.configured?'Reconnect':'Connect',async()=>{await identity('channels.connect'); if (item.channel === 'whatsapp') {$('wa-form').reset(); $('wa-error').textContent=''; $('wa-dialog').showModal();} else {if (!item.oauth_configured) throw failure('Instagram authorization is not configured for this application yet.'); const result=await command('start_instagram','/instagram/connect',{idempotency_key:crypto.randomUUID()}); const url=new URL(result.authorization_url); if (url.protocol !== 'https:' || url.hostname !== 'www.instagram.com' || url.pathname !== '/oauth/authorize' || url.username || url.password) throw failure('The authorization address could not be verified.'); if (!ended) location.assign(url.href);}},!item.configured);
        if (item.configured) add('Check connection',()=>channelAction(item.channel,'verify'));
      }
      if (item.configured && capabilities.has('automation.manage')) add(item.automation_enabled?'Pause sending':'Enable sending',()=>confirmAction(item.automation_enabled?'Pause channel sending?':'Enable channel sending?',item.automation_enabled?'New incoming messages remain saved. Automated replies will wait.':'Enable only after checking account authorization and webhook setup. Conversation and uncertainty checks still apply.',()=>channelAction(item.channel,'automation',{enabled:!item.automation_enabled})));
      if (item.configured && capabilities.has('channels.disconnect')) add('Disconnect',()=>confirmAction(`Disconnect ${item.channel === 'instagram' ? 'Instagram' : 'WhatsApp'}?`,'Remove saved authorization and pause sending. Saved conversations remain. Revoking provider permissions is a separate Meta action.',()=>channelAction(item.channel,'disconnect')));
      if (!buttons.children.length) buttons.append(node('p','Only an owner can connect or disconnect accounts.','muted'));
      row.append(info,buttons); $('connections-list').append(row);
    }
    recovery();
  }
  $('review-form').addEventListener('submit',async event=>{event.preventDefault(); if (ended || busy || pending || blocked || !selected) return; const decision=event.submitter?.value; if (!['resolve','replay'].includes(decision)) return; const id=selected.id,body={idempotency_key:crypto.randomUUID(),decision,reviewed:$('review-confirm').checked,reason:$('review-note').value.trim(),expected_updated_at:selected.updated_at}; try {await command('instagram_receipt_review',`/instagram/receipts/${id}/review`,body); if (!ended) $('review-dialog').close();} catch(error) {if (!ended) $('review-error').textContent=error.message;}});
  $('wa-form').addEventListener('submit',async event=>{event.preventDefault(); if (ended || busy || pending || blocked) return; const values=new FormData(event.currentTarget),wa=connections.find(x=>x.channel==='whatsapp'); let secret=values.get('access_token'); const body={idempotency_key:crypto.randomUUID(),waba_id:values.get('waba_id'),phone_number_id:values.get('phone_number_id')}; $('wa-form').reset(); try {if (!wa) throw failure('Refresh the current connection before saving.'); await command('connect_whatsapp','/whatsapp/connect',body,secret,wa.connection_version); if (!ended) $('wa-dialog').close();} catch(error) {if (!ended) $('wa-error').textContent=error.message;} finally {secret=null; $('wa-form').reset();}});
  $('command-retry').addEventListener('click',async()=>{if (!pending || pending.secret) return; try {await dispatch(pending);} catch (_) {}});
  $('command-check').addEventListener('click',async()=>{try {await identity('channels.connect'); await loadConnections(); const wa=connections.find(x=>x.channel==='whatsapp'); if (!wa || ended) return; reviewedVersion=wa.connection_version; $('command-current').textContent=`Current local connection: ${labels[wa.status] || wa.status}. This does not confirm the earlier secret save.`; $('command-confirm').checked=false; recovery();} catch(error) {reviewedVersion=null; if (!ended) {$('command-current').replaceChildren(); $('global-error').textContent=error.message; recovery();}}});
  $('command-confirm').addEventListener('change',recovery);
  $('command-replace').addEventListener('click',async()=>{if (!pending?.secret || !$('command-confirm').checked || reviewedVersion === null) return; try {await identity('channels.connect'); await loadConnections(); const wa=connections.find(x=>x.channel==='whatsapp'); if (!wa || wa.connection_version !== reviewedVersion) {reviewedVersion=null; $('command-current').textContent='The current connection changed. Check it again before replacing credentials.'; recovery(); return;} const body=pending.body; clearCommand(); $('wa-form').reset(); $('wa-form').elements.waba_id.value=body.waba_id; $('wa-form').elements.phone_number_id.value=body.phone_number_id; $('wa-error').textContent='Re-enter the access token. A new conditional replacement will use the reviewed current version.'; $('wa-dialog').showModal();} catch(error) {if (!ended) $('global-error').textContent=error.message;}});
  $('review-note').addEventListener('input',updateReviewButtons); $('review-confirm').addEventListener('change',updateReviewButtons);
  $('review-close').addEventListener('click',eraseDialogs); $('wa-close').addEventListener('click',()=>{$('wa-form').reset(); $('wa-dialog').close();}); $('wa-dialog').addEventListener('close',()=> $('wa-form').reset());
  $('confirm-cancel').addEventListener('click',()=>{$('confirm-action').onclick=null; $('confirm-dialog').close();});
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>showTab(b.dataset.tab)));
  $('status-filter').addEventListener('change',()=>{cursor=null;cursors=[];loadList();});
  $('next').addEventListener('click',()=>{if(nextCursor){cursors.push(cursor);cursor=nextCursor;loadList();}}); $('previous').addEventListener('click',()=>{if(cursors.length){cursor=cursors.pop();loadList();}});
  async function refresh() {try {await identity(); await loadConnections(); await loadList();} catch(error) {if (!ended) {erasePrivate(); $('global-error').textContent=error.message;}}}
  $('refresh').addEventListener('click',refresh);
  let focusRunning=false,focusAgain=false;
  async function focusCheck() {if (document.visibilityState !== 'visible' || ended) return; if (focusRunning) {focusAgain=true;return;} focusRunning=true; do {focusAgain=false; await refresh();} while(focusAgain && !ended); focusRunning=false;}
  window.addEventListener('focus',focusCheck); document.addEventListener('visibilitychange',()=>{if (document.visibilityState !== 'visible') $('wa-form').reset(); else focusCheck();});
  $('logout').addEventListener('click',async()=>{try {await identity(); await window.V1.api('/api/v1/auth/logout',{method:'POST'}); closeAccess('Signed out. Sign in to continue.');} catch(error) {closeAccess('Sign-out could not be confirmed. This page was cleared; return to sign in.');}});
  (async()=>{try {await identity(); await recover(); await loadConnections(); await loadList(); if (!ended && new URLSearchParams(location.search).get('connection')) {showTab('connections'); $('global-status').textContent='Authorization returned. Review the current connection status; delivery and provider approvals remain separate.'; history.replaceState(null,'',location.pathname);}} catch(error) {if (!ended) {erasePrivate(); $('global-error').textContent=error.message;}}})();
})();
