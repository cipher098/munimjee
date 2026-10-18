(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let mode = location.hash.startsWith('#invite=') ? 'invite' : 'signup';
  const invitation = mode === 'invite' ? location.hash.slice(8) : null;
  if (invitation) history.replaceState(null, '', '/v1');
  const requestedBusiness = new URLSearchParams(location.search).get('business');
  let actor, business, profileVersion = 0, businessLoad = 0;
  const rawApi = window.V1.api;
  let identity = null, ended = false, fenceGeneration = 0, sessionIssued = 0, sessionApplied = 0, latestSession = null, checking = false, recheckPending = false;
  const csrfCookie = () => {try {return document.cookie.split(';').map(v => v.trim()).find(v => v.startsWith('v1_csrf='))?.slice(8) || null;} catch (_) {return null;}};
  const changedError = () => Object.assign(new Error('Your sign-in or access changed. Review the current workspace.'), {stale: true});
  function endWorkspace(message) {
    if (ended) return; ended = true; fenceGeneration++; identity = null; latestSession = null; actor = null; mode = 'login'; access();
    $('business-picker').replaceChildren(); $('business-content').hidden = true; $('team').hidden = true;
    for (const id of ['profile-status','profile-error','invite-error','global-error','setup-progress']) $(id).textContent = '';
    $('access-form').reset(); $('access-error').textContent = message; $('logout-all').hidden = true;
  }
  function applyAuthority(value) {
    if (!actor) return;
    const selected = business?.id || $('business-picker').value;
    const different = JSON.stringify([actor.businesses,actor.features]) !== JSON.stringify([value.businesses,value.features]);
    actor = value;
    if (!different) return;
    businessLoad++; clearInvite(); $('business-tools').hidden = true; $('business-tools').replaceChildren();
    $('business-picker').replaceChildren(...value.businesses.map(b => {const option = text('option', b.name);option.value=b.id;return option;}));
    $('business-picker').value = value.businesses.some(b => b.id === selected) ? selected : '';
    $('business-picker-label').hidden = value.businesses.length < 2 && !(selected && !$('business-picker').value && value.businesses.length);
    business = value.businesses.find(b => b.id === selected) || null;
    if (!business) {
      $('business-content').hidden = true; $('profile-form').reset(); $('team').hidden = true; $('checklist').replaceChildren();
      $('business-heading').textContent = 'Your business'; $('setup-progress').textContent = '';
      $('no-business').hidden = false; $('no-business').textContent = 'This business is no longer available. Choose one of your businesses or ask its owner to review access.';
    } else {
      $('business-heading').textContent = business.name;
      [...$('profile-form').elements].forEach(control => control.disabled = !business.capabilities.includes('business.write'));
      $('team').hidden = !business.capabilities.includes('members.manage');
      const epoch = businessLoad;
      queueMicrotask(() => {if (!ended && epoch === businessLoad) loadBusiness().catch(e => {if (!ended) $('global-error').textContent=e.message;});});
    }
    $('assisted-access-link').hidden = !value.features?.assisted_operator;
  }
  async function checkedSession(initial = false) {
    if (ended && !initial) throw changedError();
    const generation = fenceGeneration, sequence = ++sessionIssued;
    if (identity && csrfCookie() !== identity.csrf) {endWorkspace('Your sign-in changed. Sign in again to continue.');throw changedError();}
    let value;
    try {value = await window.V1.session();} catch (e) {if (initial && !identity && !actor) throw e;if (generation === fenceGeneration) endWorkspace('Your current sign-in could not be checked. Sign in again.');throw e;}
    if (generation !== fenceGeneration || ended) throw changedError();
    if (sequence < sessionApplied) value = latestSession;
    if (!value || typeof value.user_id !== 'string' || !Array.isArray(value.businesses) || !value.businesses.every(b => b && typeof b.id === 'string' && typeof b.name === 'string' && ['owner','manager','staff','viewer'].includes(b.role) && Array.isArray(b.capabilities) && b.capabilities.every(c => typeof c === 'string')) || typeof value.csrf_token !== 'string' || !value.csrf_token || csrfCookie() !== value.csrf_token ||
        identity && (identity.user !== value.user_id || identity.csrf !== value.csrf_token)) {
      endWorkspace('Your sign-in changed. Sign in again to continue.');throw changedError();
    }
    if (sequence >= sessionApplied) {sessionApplied = sequence;latestSession = value;}
    applyAuthority(value); return value;
  }
  function pathAccess(path, options) {
    const match = path.match(/^\/api\/v1\/businesses\/([^/]+)\/(profile|onboarding|invitations|members)(?:\/|$)/);
    if (!match) return;
    const capability = ['invitations','members'].includes(match[2]) ? 'members.manage' : match[2] === 'onboarding' ? 'readiness.read' : (options.method && options.method !== 'GET') ? 'business.write' : 'business.read';
    if (!actor?.businesses.some(b => b.id === match[1] && b.capabilities.includes(capability))) throw Object.assign(new Error('Your current role does not allow this action.'), {status:403});
  }
  async function api(path, options = {}) {
    const transition = /^\/api\/v1\/auth\/(login|signup|invitations\/accept)$/.test(path);
    if (transition) {const generation = ++fenceGeneration;ended = false;identity = null;latestSession = null;const data = await rawApi(path,options);if(generation !== fenceGeneration)throw changedError();return data;}
    if (!actor) throw changedError();
    try {
      const generation = fenceGeneration;await checkedSession();if (ended || generation !== fenceGeneration) throw changedError();pathAccess(path,options);
      const data = await rawApi(path, options);
      if (/^\/api\/v1\/auth\/logout(?:-all)?$/.test(path)) return data;
      await checkedSession();if (ended || generation !== fenceGeneration) throw changedError();pathAccess(path,options);return data;
    } catch (e) {
      if (e.status === 401) endWorkspace('Your session ended. Sign in to continue.');
      else if (e.status === 403 && !ended) {try {await checkedSession();} catch (_) {}}
      throw e;
    }
  }
  const text = (tag, value, className) => {const n = document.createElement(tag); n.textContent = value; if (className) n.className = className; return n;};
  function clearInvite() {
    $('invite-result').hidden = true; $('invite-link').value = ''; $('invite-form').reset();
    $('invite-error').textContent = ''; $('team-list').replaceChildren();
    $('invite-form').querySelectorAll('button').forEach(b => b.disabled = false);
  }
  function access() {
    $('assisted-access-link').hidden = true;
    businessLoad++; business = null; clearInvite(); $('profile-form').reset(); $('checklist').replaceChildren();
    $('business-heading').textContent = 'Your business';
    $('business-tools').hidden = true; $('business-tools').replaceChildren();
    document.querySelectorAll('#access-form button, #workspace button').forEach(b => b.disabled = false);
    $('workspace').hidden = true; $('access').hidden = false; $('logout').hidden = true;
    $('access-title').textContent = mode === 'signup' ? 'Create your account' : mode === 'invite' ? 'Join your team' : 'Welcome back';
    $('business-name-label').hidden = mode !== 'signup';
    $('access-form').elements.business_name.required = mode === 'signup';
    $('access-form').elements.password.autocomplete = mode === 'signup' ? 'new-password' : 'current-password';
    $('access-submit').textContent = mode === 'signup' ? 'Create account' : mode === 'invite' ? 'Accept invitation' : 'Sign in';
    $('access-toggle').textContent = mode === 'signup' ? 'I already have an account' : 'Create a business account';
    $('access-toggle').hidden = mode === 'invite'; $('invite-note').hidden = mode !== 'invite';
  }
  async function busy(form, errorId, callback) {
    const epoch = businessLoad;
    $(errorId).textContent = '';
    const buttons = [...form.querySelectorAll('button')]; buttons.forEach(b => b.disabled = true);
    form.setAttribute('aria-busy', 'true');
    try { await callback(); } catch (e) {if (e.stale || epoch !== businessLoad) return; $(errorId).textContent = e.message;
      if (e.status === 401 && actor) {actor = null; mode = 'login'; access(); $('access-error').textContent = 'Your session ended. Sign in to continue.';}
    } finally {if (epoch === businessLoad) buttons.forEach(b => b.disabled = false);form.removeAttribute('aria-busy');}
  }
  async function loadBusiness() {
    const load = ++businessLoad; clearInvite();
    $('business-content').hidden = true;
    $('business-tools').hidden = true; $('business-tools').replaceChildren();
    $('global-error').textContent = '';
    business = actor.businesses.find(b => b.id === $('business-picker').value);
    $('no-business').hidden = Boolean(business);
    if (!business) {
      $('business-heading').textContent = 'Your business';
      $('no-business').textContent = requestedBusiness ? 'This business is unavailable with your current access. Choose one of your businesses or ask its owner for an invitation.' : 'No active business access. Ask your business owner for a new invitation.';
      return;
    }
    $('business-heading').textContent = business.name;
    const data = await api(`/api/v1/businesses/${business.id}/onboarding`);
    if (load !== businessLoad) return;
    $('business-content').hidden = false;
    if (business.capabilities.includes('catalogue.read')) {
      for (const [label, page] of [['Catalogue','catalogue'],['Imports','imports'],['Store design','themes']]) {
        const link = text('a', label, 'button secondary');
        link.href = `/v1/businesses/${business.id}/${page}`; $('business-tools').append(link);
      }
      $('business-tools').hidden = false;
    }
    for (const [capability,label,page] of [['inbox.read','Comments and enquiries','comment-automation'],['readiness.read','Onboarding','assistance'],['business.write','Payment setup','payments'],['analytics.read','Purchases and payments','analytics']]) {
      if (business.capabilities.includes(capability)) {
        const link = text('a', label, 'button secondary');
        link.href = `/v1/businesses/${business.id}/${page}`; $('business-tools').append(link); $('business-tools').hidden = false;
      }
    }
    if (actor.features?.support_grants && business.role === 'owner') { const link = text('a', 'Allow assisted access', 'button secondary'); link.href = `/v1/businesses/${business.id}/support`; $('business-tools').append(link); $('business-tools').hidden = false; }
    if (business.role === 'owner') { const link = text('a', 'WhatsApp setup and test', 'button secondary'); link.href = `/v1/businesses/${business.id}/channels/whatsapp/setup`; $('business-tools').append(link); $('business-tools').hidden = false; }
    if (actor.features?.customer_links && business.capabilities.includes('inbox.read')) { const link = text('a', 'Customer account links', 'button secondary'); link.href = `/v1/businesses/${business.id}/customers`; $('business-tools').append(link); $('business-tools').hidden = false; }
    profileVersion = data.profile.version;
    const form = $('profile-form');
    form.elements.name.value = data.profile.name;
    for (const name of ['support_email', 'phone', 'website']) form.elements[name].value = data.profile.profile[name] || '';
    const writable = business.capabilities.includes('business.write');
    [...form.elements].forEach(control => control.disabled = !writable);
    $('profile-status').textContent = writable ? (data.profile.confirmed ? 'Saved' : '') : 'Your role has read-only access to these details.';
    $('checklist').replaceChildren();
    const statusLabels = {ready: 'Ready', action_required: 'To do', pending_external: 'Approval pending'};
    for (const step of data.steps) {
      const li = document.createElement('li'), detail = document.createElement('div');
      detail.append(text('h3', step.label), text('p', step.reason));
      if (step.action_url && step.id === 'business_profile' && writable) {
        const link = text('a', 'Edit business details'); link.href = step.action_url; detail.append(link);
      } else if (step.action_url && step.id !== 'business_profile') {
        const link = text('a', step.id === 'channels' ? 'Manage channels' : 'Manage catalogue'); link.href = step.action_url; detail.append(link);
      }
      if (step.action_unavailable_reason) detail.append(text('p', step.action_unavailable_reason, 'hint'));
      li.append(detail, text('span', statusLabels[step.status] || 'Needs review', `badge ${step.status === 'ready' ? 'paid' : 'pending'}`)); $('checklist').append(li);
    }
    $('setup-progress').textContent = `${data.completed_steps} of ${data.total_steps} ready`;
    $('team').hidden = !business.capabilities.includes('members.manage');
    if (!$('team').hidden) await loadTeam();
  }
  async function loadTeam() {
    const businessId = business.id, epoch = businessLoad;
    const rows = await api(`/api/v1/businesses/${businessId}/invitations`);
    if (business?.id !== businessId || epoch !== businessLoad) return;
    $('team-list').replaceChildren();
    for (const row of rows) {
      const line = text('p', `${row.email} · ${row.role} · ${row.revoked ? 'Revoked' : row.consumed ? 'Accepted' : new Date(row.expires_at) < new Date() ? 'Expired' : 'Pending'}`);
      if (!row.revoked && !row.consumed) {
        const button = text('button', 'Revoke', 'button secondary'); button.type = 'button'; button.style.marginLeft = '12px';
        button.addEventListener('click', async () => {button.disabled = true; try {await api(`/api/v1/businesses/${business.id}/invitations/${row.id}`, {method:'DELETE'}); await loadTeam();} catch(e) {$('invite-error').textContent = e.message; button.disabled = false;}}); line.append(button);
      } $('team-list').append(line);
    }
  }
  async function workspace(data) {
    if (!data.csrf_token) {actor = null; mode = 'login'; access(); $('access-error').textContent = 'Sign in again to restore your browser session.'; return;}
    ended = false; identity = {user:data.user_id,csrf:data.csrf_token}; latestSession = data; $('logout-all').hidden = false;
    actor = data; $('assisted-access-link').hidden = !data.features?.assisted_operator; $('business-heading').textContent = 'Your business'; $('invite-result').hidden = true; $('team-list').replaceChildren(); $('access').hidden = true; $('workspace').hidden = false; $('logout').hidden = false;
    $('business-picker').replaceChildren(...actor.businesses.map(b => {const option = text('option', b.name);option.value=b.id;return option;}));
    if (requestedBusiness !== null) $('business-picker').value = actor.businesses.some(b => b.id === requestedBusiness) ? requestedBusiness : '';
    const requestedUnavailable = requestedBusiness !== null && !actor.businesses.some(b => b.id === requestedBusiness);
    $('business-picker-label').hidden = actor.businesses.length < 2 && !(requestedUnavailable && actor.businesses.length);
    await loadBusiness();
  }
  $('access-toggle').addEventListener('click', () => {mode = mode === 'signup' ? 'login' : 'signup'; $('access-error').textContent = ''; access();});
  $('access-form').addEventListener('submit', event => {event.preventDefault(); const form = event.currentTarget; busy(form, 'access-error', async () => {
    const body = {email: form.elements.email.value, password: form.elements.password.value};
    if (mode === 'signup') body.business_name = form.elements.business_name.value;
    if (mode === 'invite') body.token = invitation;
    const data = await api('/api/v1/auth/' + (mode === 'invite' ? 'invitations/accept' : mode), {method: 'POST', body}); form.elements.password.value = ''; await workspace(data);
  });});
  $('profile-form').addEventListener('submit', event => {event.preventDefault(); const form = event.currentTarget; busy(form, 'profile-error', async () => {
    const businessId = business.id, epoch = businessLoad;
    const body = {expected_version: profileVersion}; for (const key of ['name','business_type','country','support_email','phone','website']) body[key] = form.elements[key].value || null;
    const saved = await api(`/api/v1/businesses/${businessId}/profile`, {method:'PUT',body}); if (epoch !== businessLoad || business?.id !== businessId) return; business.name=saved.name; await loadBusiness(); $('profile-status').textContent='Business details saved.';
  });});
  $('invite-form').addEventListener('submit', event => {event.preventDefault(); const form = event.currentTarget; busy(form, 'invite-error', async () => {
    const businessId = business.id, epoch = businessLoad;
    const data = await api(`/api/v1/businesses/${businessId}/invitations`, {method:'POST',body:{email:form.elements.email.value,role:form.elements.role.value}});
    if (epoch !== businessLoad || business?.id !== businessId) return;
    $('invite-link').value = location.origin + data.invitation_url; $('invite-result').hidden=false; await loadTeam();
  });});
  $('business-picker').addEventListener('change', () => {
    if ($('business-picker').value) history.replaceState(null, '', '/v1?business=' + encodeURIComponent($('business-picker').value) + location.hash);
    loadBusiness().catch(e => $('global-error').textContent=e.message);
  });
  for (const id of ['logout','logout-all']) $(id).addEventListener('click', () => {busy($('workspace'), 'global-error', async () => {await api('/api/v1/auth/' + id, {method:'POST'});endWorkspace('Signed out. Sign in to continue.');});});
  async function recheck() {if (!actor || ended) return;if(checking){recheckPending=true;return;}checking = true;$('workspace').hidden = true;try {await checkedSession();} catch (_) {if (!ended) endWorkspace('Your current sign-in could not be checked. Sign in again.');} finally {checking = false;if (actor && !ended && !document.hidden) $('workspace').hidden = false;if(recheckPending && !ended){recheckPending=false;recheck();}}}
  window.addEventListener('focus', recheck);window.addEventListener('pageshow', recheck);window.addEventListener('pagehide', () => {$('workspace').hidden=true;});
  document.addEventListener('visibilitychange', () => {if (document.hidden) $('workspace').hidden=true;else recheck();});
  (async () => {try {if (invitation) access(); else await workspace(await checkedSession(true));} catch(e) {if(e.stale) return;if(e.status===401) access();else $('global-error').textContent=e.message;} finally {$('loading').hidden=true;}})();
})();
