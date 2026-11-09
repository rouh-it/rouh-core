/* The setup sign-ins, kept inline in Anatomy Connections. No credentials reach this page. */
let timer = null;
let loaded = false;
const states = {};
const busy = new Set();
const loading = new Set();
const generations = {};
const names = { claude: 'Claude Code', codex: 'Codex' };
const root = () => document.getElementById('subscriptions');
function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function button(text, action, primary = false) {
  const n = el('button', text, 'ctl small' + (primary ? ' primary' : ''));
  n.type = 'button'; n.addEventListener('click', action); return n;
}
function when(ts) {
  if (typeof ts !== 'number') return 'Reset time unavailable';
  // The account's named time zone includes daylight saving, unlike a fixed offset.
  const zone = states.zone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  return new Intl.DateTimeFormat(undefined, {timeZone: zone, day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short'}).format(new Date(ts * 1000)) + ' (' + zone + ')';
}
function field(text, input) { const n = el('label', text); n.append(input); return n; }
function fact(list, title, text) {
  const row = el('div'); row.append(el('dt', title), el('dd', text)); list.append(row);
}
function show(provider, s) {
  const card = root().querySelector('[data-provider="' + provider + '"]');
  const body = card.querySelector('.subscription-body');
  const oldCode = /** @type {HTMLInputElement|null} */ (card.querySelector('input[name="code"]'));
  const typed = oldCode ? oldCode.value : '';
  // Polling must never replace a field while someone is typing or choosing a workspace.
  if (card.contains(document.activeElement) && /^(INPUT|SELECT)$/.test(document.activeElement.tagName)) return;
  body.replaceChildren();
  if (!s.reached) {
    body.append(el('p', s.problem || 'The worker is not answering. Press Refresh to try again.', 'subscription-warning'));
    return;
  }
  const waiting = !!(s.waiting || s.waiting_for_code);
  const state = el('p', waiting ? 'Sign-in in progress' : s.on_plan ? 'Signed in' : 'Not signed in to a plan', 'subscription-state');
  state.setAttribute('role', 'status'); body.append(state);
  if (s.signed_in) {
    const facts = el('dl', null, 'subscription-facts');
    fact(facts, 'Account', s.email || 'Email unavailable');
    fact(facts, 'Plan and workspace', [s.plan || (s.on_plan ? 'Plan unavailable' : 'API key'),
      s.workspace || 'Workspace unavailable', s.workspace_name && s.workspace_name !== s.workspace ? s.workspace_name : ''].filter(Boolean).join(' · '));
    if (s.account_id) fact(facts, 'Workspace ID', s.account_id);
    body.append(facts);
  }
  if (s.workspace_mismatch) {
    const mismatch = s.workspace_expected_id ? 'This is a different workspace ID than ' + s.workspace_expected_id + '.' :
      'This is still ' + (s.workspace || 'an unknown workspace') + '. You chose ' + (s.workspace_choice === 'personal' ? 'Personal' : 'Team') + '.';
    const warning = el('p', mismatch + ' Jobs wait for the chosen workspace. Sign out and sign in with it.', 'subscription-warning');
    warning.setAttribute('role', 'alert'); body.append(warning);
  } else if (s.workspace_locked && s.on_plan) {
    body.append(el('p', 'This workspace is held for future Codex sign-ins.', 'subscription-muted'));
  }
  if (s.api_key_chosen) body.append(el('p', 'Jobs are currently billed to the OpenAI API key. Sign in to use your ChatGPT plan.', 'subscription-warning'));
  if (!s.on_plan && provider === 'claude') body.append(el('p', s.proxy ?
    'Without a Claude plan, jobs fall back to the Anthropic key.' :
    'Without a Claude plan, jobs need an Anthropic key. No key proxy is configured.', 'subscription-muted'));
  const capacity = el('div', null, 'subscription-capacity');
  const limits = s.limits || {};
  [['primary', '5-hour window'], ['secondary', 'Weekly window']].forEach(([key, title]) => {
    const w = limits[key] || {};
    const line = el('div');
    const known = typeof w.used_percent === 'number';
    const label = w.window_minutes && w.window_minutes !== (key === 'primary' ? 300 : 10080) ?
      (w.window_minutes / 60) + '-hour window' : title;
    line.append(el('p', label + ': ' + (known ? w.used_percent + '% used' : 'Unavailable')));
    if (known) {
      const meter = el('meter', null, 'subscription-meter'); meter.min = 0; meter.max = 100;
      meter.value = w.used_percent; meter.setAttribute('aria-label', label + ' used'); line.append(meter);
    }
    if (known || w.resets_at) line.append(el('p', when(w.resets_at), 'subscription-muted'));
    capacity.append(line);
  });
  const c = limits.credits;
  const credits = c ? c.unlimited ? 'Unlimited' : typeof c.balance === 'number' ? String(c.balance) :
    c.has_credits === true ? 'Available; balance not supplied' : c.has_credits === false ? 'None available; balance not supplied' : 'Balance not supplied' : 'Unavailable';
  capacity.append(el('p', 'Credits: ' + credits));
  if (limits.checked_at) capacity.append(el('p', 'Checked ' + when(limits.checked_at), 'subscription-muted'));
  if (limits.why) capacity.append(el('p', limits.why, 'subscription-muted'));
  body.append(capacity);
  if (s.last && !s.last.ok && s.last.said) body.append(el('p', s.last.said, 'subscription-warning'));
  if (s.why) body.append(el('p', s.why, 'subscription-warning'));
  const actions = el('div', null, 'subscription-actions');
  const signout = button('Sign out', () => {
    if (confirm('Sign out of ' + names[provider] + ' in the worker? New jobs will need a sign-in or key.')) {
      act(provider, {do: 'logout', confirmed: true});
    }
  });
  signout.disabled = !s.signed_in || waiting; actions.append(signout);
  if (!waiting) {
    let workspace, account;
    if (provider === 'codex') {
      workspace = el('select'); workspace.name = 'workspace';
      [['personal','Personal'], ['team','Team'], ['any','Any workspace']].forEach(([value, label]) => {
        const option = el('option', label); option.value = value; workspace.append(option);
      });
      workspace.value = s.workspace_choice || 'personal';
      body.append(field('Workspace to use', workspace));
      if (s.workspace_supported) {
        const more = el('details'); const summary = el('summary', 'Hold a specific workspace');
        account = el('input'); account.name = 'account_id'; account.placeholder = 'Workspace UUID (optional)';
        more.append(summary, field('Workspace ID', account)); body.append(more);
      }
      body.append(el('p', 'On OpenAI’s page, pick Personal, not Team, when using your personal plan.', 'subscription-muted'));
    }
    const signin = button('Sign in', () => act(provider, {do: 'start', ...(workspace ?
      {workspace: workspace.value, account_id: account ? account.value.trim() : ''} : {})}), !s.on_plan);
    signin.disabled = !s.installed; actions.append(signin);
  }
  body.append(actions);
  if (waiting) {
    const signin = el('div', null, 'subscription-signin');
    const url = String(s.address || '');
    if (url.startsWith('https://')) {
      const link = el('a', provider === 'codex' ? 'Open OpenAI sign-in' : 'Open Claude sign-in', 'ctl small' + (provider === 'codex' ? ' primary' : ''));
      link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; signin.append(link);
      if (provider === 'codex') signin.append(el('p', url, 'subscription-muted'));
    }
    if (provider === 'codex') {
      signin.append(el('p', 'Enter this one-time code on OpenAI’s page:'), el('code', s.code || '', 'subscription-code'));
      signin.append(button('Copy code', async () => {
        try { await navigator.clipboard.writeText(s.code || ''); }
        catch (_) { const note = el('p', 'Select the code above to copy it.', 'subscription-muted'); note.setAttribute('role','status'); signin.append(note); return; }
        const note = el('p', 'Code copied.', 'subscription-muted'); note.setAttribute('role','status'); signin.append(note);
      }));
      signin.append(el('p', 'Choose ' + (s.workspace_choice === 'team' ? 'Team' : s.workspace_choice === 'any' ? 'the workspace you want' : 'Personal, not Team') +
        '. Return here after approving. This code expires in 15 minutes.', 'subscription-muted'));
    } else {
      const code = el('input'); code.name = 'code'; code.autocomplete = 'off'; code.value = typed;
      signin.append(field('Code from Claude', code));
      signin.append(button('Finish sign-in', () => act(provider, {do:'code', code:code.value.trim()}), true));
    }
    signin.append(button('Cancel sign-in', () => act(provider, {do:'cancel'})));
    body.append(signin);
  }
  if (s.adoption) body.append(el('p', s.adoption, 'subscription-muted'));
}
async function fetchCard(provider, action) {
  const csrf = /** @type {HTMLInputElement|null} */ (document.querySelector('input[name="csrfmiddlewaretoken"]'));
  const response = await fetch('/api/subscriptions/' + provider, {cache:'no-store',
    ...(action ? {method:'POST', headers:{'Content-Type':'application/json',
      'X-CSRFToken': csrf ? csrf.value : ''}, body:JSON.stringify(action)} : {})});
  if (response.status === 404) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.problem || 'The worker could not finish. Press Refresh to try again.');
  return data;
}
async function load(provider) {
  if (busy.has(provider) || loading.has(provider)) return;
  loading.add(provider);
  const generation = generations[provider] || 0;
  try {
    const s = await fetchCard(provider);
    if (generation !== (generations[provider] || 0)) return;
    if (!s) return;
    root().hidden = false; states[provider] = s; if (s.zone) states.zone = s.zone; show(provider, s);
  } catch (err) {
    root().hidden = false; show(provider, {reached:false, problem:err.message});
  } finally { loading.delete(provider); }
}
async function act(provider, action) {
  if (busy.has(provider)) return;
  busy.add(provider);
  generations[provider] = (generations[provider] || 0) + 1;
  const card = root().querySelector('[data-provider="' + provider + '"]');
  card.querySelectorAll('button').forEach(b => {b.disabled = true;});
  const status = card.querySelector('.subscription-state');
  if (status) status.textContent = {start:'Starting sign-in…',logout:'Signing out…',code:'Finishing sign-in…',cancel:'Cancelling sign-in…'}[action.do];
  try {
    const s = await fetchCard(provider, action);
    if (!s) return;
    states[provider] = s; show(provider, s);
  } catch (err) {
    show(provider, states[provider] || {reached:false});
    const note = el('p', err.message, 'subscription-warning'); note.setAttribute('role','alert');
    card.querySelector('.subscription-body').append(note);
  } finally { busy.delete(provider); }
}
export function subscriptionsLoad() {
  if (!root()) return;
  if (!loaded) {
    loaded = true;
    document.getElementById('subscriptionsRefresh').addEventListener('click', () => {load('claude'); load('codex');});
    timer = setInterval(() => {
      if (!root().getClientRects().length || document.hidden) return;
      load('claude'); load('codex');
    }, 5000);
  }
  load('claude'); load('codex');
}
