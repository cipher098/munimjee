(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let mode = location.hash.startsWith('#invite=') ? 'invite' : 'signup';
  const invitation = mode === 'invite' ? location.hash.slice(8) : null;
  if (invitation) history.replaceState(null, '', '/v1');
  const requestedBusiness = new URLSearchParams(location.search).get('business');
  let actor, business, profileVersion = 0, businessLoad = 0;
  const api = window.V1.api;
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
    try { await callback(); } catch (e) {if (epoch !== businessLoad) return; $(errorId).textContent = e.message;
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
  for (const id of ['logout','logout-all']) $(id).addEventListener('click', () => {busy($('workspace'), 'global-error', async () => {await api('/api/v1/auth/' + id, {method:'POST'});actor=null;mode='login';$('profile-form').reset();$('invite-result').hidden=true; access();});});
  (async () => {try {if (invitation) access(); else await workspace(await window.V1.session());} catch(e) {if(e.status===401) access();else $('global-error').textContent=e.message;} finally {$('loading').hidden=true;}})();
})();
