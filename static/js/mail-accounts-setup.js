/**
 * Multi-mailbox setup: Gmail/SMTP account cards, transport mode, per-account KB.
 */
(function () {
  const MAX_SLOTS_PER_TRANSPORT = 5;
  const OAUTH_REDIRECT_URI = document.getElementById('redirTxt')?.textContent?.trim() || '';

  let mailAccounts = [];
  let transportSummary = { active_mode: 'gmail', enabled_count: 0, max_slots: MAX_SLOTS_PER_TRANSPORT };
  let kbSelectedAccountId = null;

  function csrfToken() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = String(s || '');
    return d.innerHTML;
  }

  function attrEsc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/</g, '&lt;');
  }

  async function apiJson(url, opts) {
    const res = await fetch(url, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      ...opts,
    });
    const j = await res.json().catch(() => ({}));
    return { res, j };
  }

  function showPlanError(j, fallback) {
    const msg = (j && (j.error || j.detail)) || fallback || 'Plan limit reached';
    if (j && j.upgrade_required) {
      const hint =
        j.error === 'starter_trial_expired'
          ? '\n\nYour free Starter trial (20 auto-sends) has ended. Upgrade to Pro or contact us for Custom.'
          : j.error === 'payment_required'
            ? '\n\nComplete payment for your plan before adding mailboxes.'
            : j.error === 'plan_inbox_limit_reached'
              ? '\n\nYour plan active-inbox limit is reached. Upgrade or pause another mailbox first.'
              : j.error === 'plan_kb_source_limit_reached'
                ? '\n\nStarter allows one KB source (crawl or upload). Clear KB or upgrade to Pro.'
                : '\n\nOpen Pricing to upgrade your MailPilot plan.';
      const toastMsg = (msg.replace(/_/g, ' ') + hint).replace(/\n+/g, ' ').trim();
      if (typeof window.standardToast === 'function') {
        window.standardToast(toastMsg, 'warning', 5200);
      } else {
        alert(toastMsg);
      }
      if (typeof window.refreshBillingStrip === 'function') window.refreshBillingStrip();
      return true;
    }
    return false;
  }

  function planInboxLimit() {
    const lim = transportSummary.plan_inbox_limit;
    return lim == null ? null : Number(lim);
  }

  function planInboxUsed() {
    return Number(transportSummary.plan_inbox_used ?? transportSummary.enabled_count ?? 0);
  }

  function maxTransportSlots() {
    return Number(transportSummary.max_slots ?? MAX_SLOTS_PER_TRANSPORT);
  }

  function canAddMailbox() {
    return transportSummary.can_add_mailbox !== false;
  }

  function enabledMailboxes() {
    return mailAccounts.filter((a) => a.is_enabled);
  }

  function primaryEnabledMailbox() {
    const enabled = enabledMailboxes().sort((a, b) => a.id - b.id);
    return enabled[0] || null;
  }

  function mailboxDisplayName(a) {
    if (!a) return 'mailbox';
    if (a.transport === 'smtp') return a.label || a.config?.SMTP_USERNAME || 'SMTP mailbox';
    if (a.transport === 'microsoft_graph') return a.email || a.label || 'Microsoft mailbox';
    return a.email || a.label || 'Gmail mailbox';
  }

  function modeLabel(mode) {
    if (mode === 'smtp') return 'SMTP';
    if (mode === 'microsoft') return 'Microsoft';
    return 'Gmail';
  }

  function mailboxPlanState(account) {
    const lim = planInboxLimit();
    const used = planInboxUsed();
    if (lim == null) {
      return { locked: false, canEnable: true, canDisable: true, reason: '', lockNote: '' };
    }

    const enabled = enabledMailboxes();
    const atLimit = used >= lim;

    if (account.is_enabled) {
      if (enabled.length > lim) {
        const keepIds = new Set(
          [...enabled]
            .sort((a, b) => a.id - b.id)
            .slice(0, lim)
            .map((a) => a.id)
        );
        if (!keepIds.has(account.id)) {
          return {
            locked: true,
            canEnable: false,
            canDisable: true,
            reason: 'over_limit',
            lockNote:
              'Over plan limit - pause this mailbox to stay within your plan, or <a href="/#pricing">upgrade</a>.',
          };
        }
      }
      return { locked: false, canEnable: false, canDisable: true, reason: '', lockNote: '' };
    }

    if (atLimit) {
      const primary = primaryEnabledMailbox();
      let lockNote =
        'Plan inbox limit reached - pause another mailbox or <a href="/#pricing">upgrade</a>.';
      if (lim === 1 && primary) {
        const transportLabel =
          primary.transport === 'gmail_api'
            ? 'Gmail'
            : primary.transport === 'microsoft_graph'
              ? 'Microsoft'
              : 'SMTP';
        lockNote =
          'Starter allows <strong>1 inbox</strong>. Active: <strong>' +
          esc(mailboxDisplayName(primary)) +
          '</strong> (' +
          transportLabel +
          '). Pause it to use this slot, or <a href="/#pricing">upgrade</a>.';
      }
      return {
        locked: true,
        canEnable: false,
        canDisable: false,
        reason: 'plan_inbox_limit_reached',
        lockNote,
      };
    }

    return { locked: false, canEnable: true, canDisable: false, reason: '', lockNote: '' };
  }

  function splitAccountsForPlan(list) {
    const lim = planInboxLimit();
    if (lim !== 1 || list.length <= 1) {
      return { visible: list, lockedExtra: [] };
    }

    const primary = primaryEnabledMailbox();
    if (!primary) {
      return { visible: list.slice(0, 1), lockedExtra: list.slice(1) };
    }

    const primaryInList = list.find((a) => a.id === primary.id);
    if (primaryInList) {
      return {
        visible: [primaryInList],
        lockedExtra: list.filter((a) => a.id !== primary.id),
      };
    }

    return { visible: [], lockedExtra: list };
  }

  function renderLockedSlotCard(a, transportLabel) {
    const name = mailboxDisplayName(a);
    return (
      '<div class="mb-card mb-card-locked mb-card-slot-locked" data-locked-account="' +
      a.id +
      '">' +
      '<i class="fa-solid fa-lock" aria-hidden="true"></i> ' +
      '<strong>#' +
      a.slot +
      ' ' +
      esc(name) +
      '</strong> - locked on your plan (' +
      transportLabel +
      ' allows 1 active inbox). <a href="/#pricing">Upgrade</a> to use more slots.' +
      '</div>'
    );
  }

  function renderTransportPlanNotice(panelId, transport) {
    const el = document.getElementById(panelId);
    if (!el) return;
    const lim = planInboxLimit();
    const primary = primaryEnabledMailbox();
    if (lim !== 1 || !primary || primary.transport === transport) {
      el.style.display = 'none';
      el.innerHTML = '';
      return;
    }
    const transportLabel =
          primary.transport === 'gmail_api'
            ? 'Gmail'
            : primary.transport === 'microsoft_graph'
              ? 'Microsoft'
              : 'SMTP';
    el.style.display = '';
    el.innerHTML =
      '<div class="oauth-h"><i class="fa-solid fa-lock" aria-hidden="true"></i> ' +
      transportLabel +
      ' is using your inbox slot</div>' +
      '<p class="oauth-txt" style="margin:0;">Starter allows one active inbox. <strong>' +
      esc(mailboxDisplayName(primary)) +
      '</strong> is active on ' +
      transportLabel +
      '. Pause it to configure this transport, or <a href="/#pricing" style="color:#c4b5fd;font-weight:800;">upgrade</a>.</p>';
  }

  function planLockBannerHtml(lockNote) {
    if (!lockNote) return '';
    return '<div class="mb-plan-lock-banner"><i class="fa-solid fa-lock"></i> ' + lockNote + '</div>';
  }

  function renderPaymentBanner() {
    const el = document.getElementById('paymentRequiredBanner');
    if (!el) return;
    const expired = !!transportSummary.starter_trial_expired;
    const pay = !!transportSummary.payment_required;
    if (expired) {
      el.style.display = '';
      el.innerHTML =
        '<div class="oauth-h"><i class="fa-solid fa-triangle-exclamation" aria-hidden="true" style="color:var(--red);"></i> Starter trial ended</div>' +
        '<p class="oauth-txt" style="margin:0;">Your 20 auto-send trial is over. Upgrade to <strong>Pro</strong> or <strong>Custom</strong> to add mailboxes and run automation.</p>';
      return;
    }
    if (pay) {
      el.style.display = '';
      el.innerHTML =
        '<div class="oauth-h"><i class="fa-solid fa-credit-card" aria-hidden="true" style="color:var(--amber);"></i> Payment required</div>' +
        '<p class="oauth-txt" style="margin:0;">Complete checkout for your plan before adding or enabling mailboxes. <a href="/#pricing" style="color:#c4b5fd;font-weight:800;">Go to Pricing</a></p>';
      return;
    }
    el.style.display = 'none';
    el.innerHTML = '';
  }

  function updateInboxHints() {
    const lim = planInboxLimit();
    const planTxt =
      lim == null
        ? 'Your plan allows unlimited active inboxes (up to ' + maxTransportSlots() + ' slots per transport).'
        : 'Your plan allows <strong>' + lim + '</strong> active inbox' + (lim === 1 ? '' : 'es') + ' total across Gmail, Microsoft, and SMTP.';
    const gmailHint = document.getElementById('gmailInboxHint');
    const microsoftHint = document.getElementById('microsoftInboxHint');
    const smtpHint = document.getElementById('smtpInboxHint');
    if (gmailHint) gmailHint.innerHTML = planTxt + ' Toggle each mailbox on/off. Only accounts in <strong>Gmail mode</strong> run automation.';
    if (microsoftHint) {
      microsoftHint.innerHTML =
        planTxt +
        ' Connect Outlook / Microsoft 365 with one click. Only accounts in <strong>Microsoft mode</strong> run automation.';
    }
    if (smtpHint) {
      smtpHint.innerHTML =
        planTxt +
        ' <strong>SMTP</strong> sends mail; <strong>IMAP</strong> reads inbox on the Dashboard. Pause any slot without deleting credentials.';
    }
  }

  async function loadMailAccounts() {
    const { res, j } = await apiJson('/api/mail-accounts/?transport=');
    if (!res.ok || !j.ok) return;
    mailAccounts = j.accounts || [];
    transportSummary = j.summary || transportSummary;
    renderTransportBanner();
    renderPaymentBanner();
    updateInboxHints();
    renderGmailAccounts();
    renderMicrosoftAccounts();
    renderSmtpAccounts();
    populateKbAccountSelect();
    updateTransportPill();
    renderTransportPlanNotice('gmailPlanNotice', 'gmail_api');
    renderTransportPlanNotice('microsoftPlanNotice', 'microsoft_graph');
    renderTransportPlanNotice('smtpPlanNotice', 'smtp');
  }

  function renderTransportBanner() {
    const el = document.getElementById('transportModeBanner');
    if (!el) return;
    const mode = transportSummary.active_mode || 'gmail';
    const modeEnabled = transportSummary.enabled_count ?? 0;
    const planUsed = planInboxUsed();
    const planLim = planInboxLimit();
    const others = ['Gmail', 'Microsoft', 'SMTP'].filter((x) => x !== modeLabel(mode)).join(' / ');
    const planPill =
      planLim == null
        ? planUsed + ' active inbox' + (planUsed === 1 ? '' : 'es')
        : planUsed + ' of ' + planLim + ' plan inbox' + (planLim === 1 ? '' : 'es');
    const pillTone = planLim != null && planUsed >= planLim ? 'warn' : planUsed > 0 ? 'ok' : 'bad';
    el.innerHTML =
      '<div class="mode-banner">' +
      '<span>Active transport: <strong>' +
      modeLabel(mode) +
      '</strong> · ' +
      modeEnabled +
      ' in this mode</span>' +
      '<span class="pill ' +
      pillTone +
      '">' +
      planPill +
      '</span>' +
      '<span class="mode-muted">' +
      others +
      ' inactive - switch tab to use</span>' +
      '</div>';
  }

  function updateTransportPill() {
    const tp = document.getElementById('transportPill');
    if (!tp) return;
    const mode = transportSummary.active_mode || 'gmail';
    const planUsed = planInboxUsed();
    const planLim = planInboxLimit();
    let label = modeLabel(mode) + ' mode';
    if (planLim == null) {
      label += ' · ' + planUsed + ' active';
    } else {
      label += ' · ' + planUsed + '/' + planLim + ' plan inbox' + (planLim === 1 ? '' : 'es');
    }
    if (typeof window.setPill === 'function') {
      window.setPill(tp, label, planUsed > 0 ? 'ok' : planLim != null && planUsed >= planLim ? 'warn' : 'bad');
    }
  }

  async function setTransportMode(mode) {
    const { res, j } = await apiJson('/api/transport-mode/', {
      method: 'POST',
      body: JSON.stringify({ mode }),
    });
    if (res.ok && j.ok) {
      transportSummary = j.summary || transportSummary;
      renderTransportBanner();
      renderPaymentBanner();
      updateInboxHints();
      updateTransportPill();
      await loadMailAccounts();
    }
  }

  window.showPanel = async function (which) {
    const mode = which === 'smtp' ? 'smtp' : which === 'microsoft' ? 'microsoft' : 'gmail';
    document.getElementById('tabG')?.classList.toggle('on', mode === 'gmail');
    document.getElementById('tabM')?.classList.toggle('on', mode === 'microsoft');
    document.getElementById('tabS')?.classList.toggle('on', mode === 'smtp');
    document.getElementById('pGmail')?.classList.toggle('on', mode === 'gmail');
    document.getElementById('pMicrosoft')?.classList.toggle('on', mode === 'microsoft');
    document.getElementById('pSmtp')?.classList.toggle('on', mode === 'smtp');
    if ((transportSummary.active_mode || 'gmail') !== mode) {
      await setTransportMode(mode);
    }
  };

  function gmailAccounts() {
    return mailAccounts.filter((a) => a.transport === 'gmail_api');
  }

  function microsoftAccounts() {
    return mailAccounts.filter((a) => a.transport === 'microsoft_graph');
  }

  function smtpAccounts() {
    return mailAccounts.filter((a) => a.transport === 'smtp');
  }

  function renderGmailAccounts() {
    const host = document.getElementById('gmailAccountsList');
    if (!host) return;
    const list = gmailAccounts();
    const split = splitAccountsForPlan(list);
    let html = '';
    split.visible.forEach((a) => {
      html += renderGmailCard(a);
    });
    split.lockedExtra.forEach((a) => {
      const overLimit = a.is_enabled && planInboxLimit() != null && planInboxUsed() > planInboxLimit();
      html += overLimit ? renderGmailCard(a) : renderLockedSlotCard(a, 'Starter');
    });
    const showAdd = split.visible.length + split.lockedExtra.length < maxTransportSlots();
    if (showAdd && split.lockedExtra.length === 0) {
      if (canAddMailbox()) {
        html +=
          '<div class="mb-card mb-card-empty" data-action="add-gmail">' +
          '<i class="fa-solid fa-plus"></i> Add Gmail account (' +
          list.length +
          '/' +
          maxTransportSlots() +
          ' slots)</div>';
      } else {
        html +=
          '<div class="mb-card mb-card-empty mb-card-locked" title="Plan inbox limit reached">' +
          '<i class="fa-solid fa-lock"></i> Inbox limit reached - <a href="/#pricing">upgrade</a> or pause another mailbox</div>';
      }
    }
    host.innerHTML = html;
    wireGmailCards();
    const highlight = document.body.dataset.highlightAccount;
    if (highlight) {
      const card = host.querySelector('[data-account-id="' + highlight + '"]');
      card?.classList.add('mb-highlight');
      card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    maybeAutoStartGmailOAuth(list);
  }

  function maybeAutoStartGmailOAuth(list) {
    const banner = document.getElementById('transportModeBanner');
    const oauthError = (banner?.dataset?.oauthError || '').trim();
    // Never auto-loop while OAuth just failed — user must retry intentionally.
    if (oauthError) return;
    const shared = !!transportSummary.shared_gmail_oauth;
    if (!shared) return;
    const target =
      list.find((a) => String(a.id) === String(banner?.dataset?.highlightAccount || '')) ||
      list.find((a) => !a.gmail_connected && !a.oauth_email_mismatch);
    if (!target || target.gmail_connected) return;
    const key = 'mp_auto_gmail_oauth_' + target.id;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, '1');
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/api/mail-accounts/' + target.id + '/connect-oauth';
    const csrf = document.createElement('input');
    csrf.type = 'hidden';
    csrf.name = 'csrfmiddlewaretoken';
    csrf.value = csrfToken();
    form.appendChild(csrf);
    document.body.appendChild(form);
    form.submit();
  }

  function renderGmailCard(a) {
    const plan = mailboxPlanState(a);
    const mismatch = !!a.oauth_email_mismatch;
    const connected = !!a.gmail_connected && !mismatch;
    const paused = !a.is_enabled;
    const statusCls = plan.locked
      ? 'warn'
      : mismatch
        ? 'bad'
        : connected
          ? paused
            ? 'info'
            : 'ok'
          : 'bad';
    const statusTxt = plan.locked
      ? plan.reason === 'over_limit'
        ? 'Over limit'
        : 'Locked'
      : mismatch
        ? 'Wrong account'
        : connected
          ? paused
            ? 'Paused'
            : 'Active'
          : 'Not connected';
    const email = a.email || a.label || 'Gmail slot ' + a.slot;
    const mismatchNote = mismatch
      ? '<p class="mb-card-meta" style="color:var(--red);">OAuth is <strong>' +
        esc(a.profile_email || 'another Gmail') +
        '</strong> - reconnect with <strong>' +
        esc(email) +
        '</strong>.</p>'
      : '';
    const toggleDisabled = plan.locked ? !plan.canDisable : !plan.canEnable && !a.is_enabled;
    const bodyHtml =
      '<div class="mb-card-meta">KB: ' +
      (a.kb_chunk_count ?? 0) +
      ' chunks</div>' +
      mismatchNote +
      (connected
        ? '<button type="button" class="btn btn-ghost btn-sm" data-disc="' +
          a.id +
          '">Disconnect</button>'
        : (mismatch && a.gmail_connected
            ? '<button type="button" class="btn btn-ghost btn-sm" data-disc="' +
              a.id +
              '">Disconnect wrong account</button>'
            : '') +
          renderGmailConnectForm(a, mismatch) +
          (a.gmail_connected
            ? ''
            : '<div class="mb-card-actions"><button type="button" class="btn btn-ghost btn-sm" data-del-gmail="' +
              a.id +
              '"><i class="fa-solid fa-trash-can"></i> Remove</button></div>'));
    return (
      '<article class="mb-card' +
      (paused ? ' mb-paused' : '') +
      (plan.locked ? ' mb-card-plan-locked' : '') +
      '" data-account-id="' +
      a.id +
      '">' +
      '<header class="mb-card-hd">' +
      '<div class="mb-card-title"><span class="mb-slot">#' +
      a.slot +
      '</span> ' +
      esc(email) +
      '</div>' +
      '<label class="mb-switch" title="Run automation">' +
      '<input type="checkbox" class="mb-enable" data-id="' +
      a.id +
      '" ' +
      (a.is_enabled ? 'checked' : '') +
      (toggleDisabled ? ' disabled' : '') +
      '>' +
      '<span class="mb-switch-ui"></span></label>' +
      '<span class="pill ' +
      statusCls +
      '">' +
      statusTxt +
      '</span>' +
      '</header>' +
      planLockBannerHtml(plan.lockNote) +
      '<div class="mb-card-body-lock">' +
      bodyHtml +
      '</div>' +
      '</article>'
    );
  }

  function renderGmailConnectForm(a, forceReconnect) {
    const addr = (a.email || a.config?.GMAIL_ADDRESS || '').trim();
    const emailVal = addr ? ' value="' + attrEsc(addr) + '" readonly' : '';
    const shared = !!(a.shared_gmail_oauth || transportSummary.shared_gmail_oauth);
    const oneClick =
      '<form class="mb-connect-form" method="POST" action="/api/mail-accounts/' +
      a.id +
      '/connect-oauth">' +
      '<input type="hidden" name="csrfmiddlewaretoken" value="' +
      csrfToken() +
      '">' +
      (forceReconnect
        ? '<p class="small" style="margin:0 0 8px;color:var(--txm);">Sign in with <strong>' +
          esc(addr || 'this Gmail address') +
          '</strong> when Google asks.</p>'
        : '<p class="small" style="margin:0 0 8px;color:var(--txm);">Authorize MailPilot to read and reply from this Gmail inbox.</p>') +
      (addr
        ? '<input type="hidden" name="gmail_address" value="' + attrEsc(addr) + '">'
        : '') +
      '<button type="submit" class="btn btn-purp btn-block"><i class="fa-brands fa-google"></i> Connect with Google</button>' +
      '</form>';
    const byoForm =
      '<form class="mb-connect-form" method="POST" action="/api/mail-accounts/' +
      a.id +
      '/setup-credentials" enctype="multipart/form-data">' +
      '<input type="hidden" name="csrfmiddlewaretoken" value="' +
      csrfToken() +
      '">' +
      '<div class="fg"><label class="fl">Email</label>' +
      '<input class="fi" type="email" name="gmail_address" placeholder="you@company.com" required' +
      emailVal +
      '></div>' +
      '<div class="fg"><label class="fl">credentials.json</label>' +
      '<input class="fi" type="file" name="client_secret" accept="application/json" required></div>' +
      '<button type="submit" class="btn btn-ghost btn-block"><i class="fa-solid fa-key"></i> Connect with uploaded client</button>' +
      '</form>';
    if (shared || a.has_client_secret) {
      return (
        oneClick +
        '<details class="mb-advanced" style="margin-top:10px;">' +
        '<summary class="small" style="cursor:pointer;color:var(--txm);">Advanced: use your own Google OAuth client</summary>' +
        '<div style="margin-top:8px;">' +
        byoForm +
        '</div></details>'
      );
    }
    return (
      '<p class="small" style="margin:0 0 8px;color:var(--amber);">Server shared Google client is not configured. Set <code>GOOGLE_OAUTH_CLIENT_ID</code> + <code>GOOGLE_OAUTH_CLIENT_SECRET</code> in <code>.env</code>, or upload a Web client JSON below.</p>' +
      byoForm
    );
  }

  function wireGmailCards() {
    document.querySelectorAll('.mb-enable').forEach((inp) => {
      inp.addEventListener('change', async () => {
        const id = inp.dataset.id;
        const account = mailAccounts.find((a) => String(a.id) === String(id));
        const plan = account ? mailboxPlanState(account) : { canEnable: true };
        if (inp.checked && !plan.canEnable) {
          inp.checked = false;
          showPlanError({ upgrade_required: true, error: 'plan_inbox_limit_reached' }, 'Could not enable mailbox');
          return;
        }
        const { res, j } = await apiJson('/api/mail-accounts/' + id + '/', {
          method: 'PATCH',
          body: JSON.stringify({ is_enabled: inp.checked }),
        });
        if (!res.ok || !j.ok) {
          inp.checked = !inp.checked;
          showPlanError(j, 'Could not update mailbox');
        }
        await loadMailAccounts();
      });
    });
    document.querySelectorAll('[data-disc]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Disconnect Gmail OAuth for this mailbox?')) return;
        const { res, j } = await apiJson('/api/mail-accounts/' + btn.dataset.disc + '/disconnect-gmail', {
          method: 'POST',
          body: '{}',
        });
        if (!res.ok || !j.ok) showPlanError(j, 'Could not disconnect Gmail');
        await loadMailAccounts();
      });
    });
    document.querySelectorAll('[data-del-gmail]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Remove this Gmail mailbox?')) return;
        const { res, j } = await apiJson('/api/mail-accounts/' + btn.dataset.delGmail + '/', {
          method: 'DELETE',
          body: '{}',
        });
        if (!res.ok || !j.ok) showPlanError(j, 'Could not remove Gmail mailbox');
        await loadMailAccounts();
      });
    });
    const add = document.querySelector('[data-action="add-gmail"]');
    if (add) {
      add.addEventListener('click', async () => {
        const { res, j } = await apiJson('/api/mail-accounts/create', {
          method: 'POST',
          body: JSON.stringify({ transport: 'gmail_api' }),
        });
        if (!res.ok || !j.ok) {
          showPlanError(j, 'Could not add Gmail mailbox');
          return;
        }
        const created = j.account || j;
        const shared = !!(created.shared_gmail_oauth || transportSummary.shared_gmail_oauth);
        // One-click automatic connect: create mailbox then start Google OAuth immediately.
        if (shared && created.id) {
          const form = document.createElement('form');
          form.method = 'POST';
          form.action = '/api/mail-accounts/' + created.id + '/connect-oauth';
          const csrf = document.createElement('input');
          csrf.type = 'hidden';
          csrf.name = 'csrfmiddlewaretoken';
          csrf.value = csrfToken();
          form.appendChild(csrf);
          document.body.appendChild(form);
          form.submit();
          return;
        }
        await loadMailAccounts();
      });
    }
  }

  function renderMicrosoftAccounts() {
    const host = document.getElementById('microsoftAccountsList');
    if (!host) return;
    const list = microsoftAccounts();
    const split = splitAccountsForPlan(list);
    let html = '';
    split.visible.forEach((a) => {
      html += renderMicrosoftCard(a);
    });
    split.lockedExtra.forEach((a) => {
      const overLimit = a.is_enabled && planInboxLimit() != null && planInboxUsed() > planInboxLimit();
      html += overLimit ? renderMicrosoftCard(a) : renderLockedSlotCard(a, 'Starter');
    });
    const showAdd = split.visible.length + split.lockedExtra.length < maxTransportSlots();
    if (showAdd && split.lockedExtra.length === 0) {
      if (canAddMailbox()) {
        html +=
          '<div class="mb-card mb-card-empty" data-action="add-microsoft">' +
          '<i class="fa-solid fa-plus"></i> Add Microsoft account (' +
          list.length +
          '/' +
          maxTransportSlots() +
          ' slots)</div>';
      } else {
        html +=
          '<div class="mb-card mb-card-empty mb-card-locked" title="Plan inbox limit reached">' +
          '<i class="fa-solid fa-lock"></i> Inbox limit reached - <a href="/#pricing">upgrade</a></div>';
      }
    }
    host.innerHTML = html || '<p class="small">No Microsoft mailboxes yet.</p>';
    wireMicrosoftCards();
  }

  function renderMicrosoftCard(a) {
    const plan = mailboxPlanState(a);
    const connected = !!a.microsoft_connected || (!!a.has_token && a.transport === 'microsoft_graph' && a.inbox_ready);
    const paused = !a.is_enabled;
    const statusCls = plan.locked ? 'warn' : connected ? (paused ? 'info' : 'ok') : 'bad';
    const statusTxt = plan.locked
      ? plan.reason === 'over_limit'
        ? 'Over limit'
        : 'Locked'
      : connected
        ? paused
          ? 'Paused'
          : 'Active'
        : 'Not connected';
    const email = a.email || a.label || 'Microsoft slot ' + a.slot;
    const msConfigured = !!transportSummary.microsoft_oauth_configured;
    const connectForm = msConfigured
      ? '<form class="mb-connect-form" method="POST" action="/api/mail-accounts/' +
        a.id +
        '/connect-oauth">' +
        '<input type="hidden" name="csrfmiddlewaretoken" value="' +
        csrfToken() +
        '">' +
        '<p class="small" style="margin:0 0 8px;color:var(--txm);">Sign in with Outlook or Microsoft 365.</p>' +
        '<button type="submit" class="btn btn-purp btn-block"><i class="fa-brands fa-microsoft"></i> Connect with Microsoft</button>' +
        '</form>'
      : '<p class="small" style="color:var(--amber);">Microsoft OAuth is not configured on the server. Set <code>MICROSOFT_OAUTH_CLIENT_ID</code> and <code>MICROSOFT_OAUTH_CLIENT_SECRET</code>.</p>';
    const toggleDisabled = plan.locked ? !plan.canDisable : !plan.canEnable && !a.is_enabled;
    const bodyHtml =
      '<div class="mb-card-meta">KB: ' +
      (a.kb_chunk_count ?? 0) +
      ' chunks</div>' +
      (connected
        ? '<button type="button" class="btn btn-ghost btn-sm" data-disc-ms="' +
          a.id +
          '">Disconnect</button>'
        : connectForm +
          '<div class="mb-card-actions"><button type="button" class="btn btn-ghost btn-sm" data-del-ms="' +
          a.id +
          '"><i class="fa-solid fa-trash-can"></i> Remove</button></div>');
    return (
      '<article class="mb-card' +
      (paused ? ' mb-paused' : '') +
      (plan.locked ? ' mb-card-plan-locked' : '') +
      '" data-account-id="' +
      a.id +
      '">' +
      '<header class="mb-card-hd">' +
      '<div class="mb-card-title"><span class="mb-slot">#' +
      a.slot +
      '</span> ' +
      esc(email) +
      '</div>' +
      '<label class="mb-switch" title="Run automation">' +
      '<input type="checkbox" class="mb-enable-ms" data-id="' +
      a.id +
      '" ' +
      (a.is_enabled ? 'checked' : '') +
      (toggleDisabled ? ' disabled' : '') +
      '>' +
      '<span class="mb-switch-ui"></span></label>' +
      '<span class="pill ' +
      statusCls +
      '">' +
      statusTxt +
      '</span>' +
      '</header>' +
      planLockBannerHtml(plan.lockNote) +
      '<div class="mb-card-body-lock">' +
      bodyHtml +
      '</div>' +
      '</article>'
    );
  }

  function wireMicrosoftCards() {
    document.querySelectorAll('.mb-enable-ms').forEach((inp) => {
      inp.addEventListener('change', async () => {
        const id = inp.dataset.id;
        const account = mailAccounts.find((a) => String(a.id) === String(id));
        const plan = account ? mailboxPlanState(account) : { canEnable: true };
        if (inp.checked && !plan.canEnable) {
          inp.checked = false;
          showPlanError({ upgrade_required: true, error: 'plan_inbox_limit_reached' }, 'Could not enable mailbox');
          return;
        }
        const { res, j } = await apiJson('/api/mail-accounts/' + id + '/', {
          method: 'PATCH',
          body: JSON.stringify({ is_enabled: inp.checked }),
        });
        if (!res.ok || !j.ok) {
          inp.checked = !inp.checked;
          showPlanError(j, 'Could not update mailbox');
        }
        await loadMailAccounts();
      });
    });
    document.querySelectorAll('[data-disc-ms]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Disconnect Microsoft OAuth for this mailbox?')) return;
        const { res, j } = await apiJson('/api/mail-accounts/' + btn.dataset.discMs + '/disconnect-gmail', {
          method: 'POST',
          body: '{}',
        });
        if (!res.ok || !j.ok) showPlanError(j, 'Could not disconnect Microsoft');
        await loadMailAccounts();
      });
    });
    document.querySelectorAll('[data-del-ms]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Remove this Microsoft mailbox?')) return;
        const { res, j } = await apiJson('/api/mail-accounts/' + btn.dataset.delMs + '/', {
          method: 'DELETE',
          body: '{}',
        });
        if (!res.ok || !j.ok) showPlanError(j, 'Could not remove Microsoft mailbox');
        await loadMailAccounts();
      });
    });
    const add = document.querySelector('[data-action="add-microsoft"]');
    if (add) {
      add.addEventListener('click', async () => {
        const { res, j } = await apiJson('/api/mail-accounts/create', {
          method: 'POST',
          body: JSON.stringify({ transport: 'microsoft_graph' }),
        });
        if (!res.ok || !j.ok) showPlanError(j, 'Could not add Microsoft mailbox');
        await loadMailAccounts();
      });
    }
  }

  function renderSmtpAccounts() {
    const host = document.getElementById('smtpAccountsList');
    if (!host) return;
    const list = smtpAccounts();
    const split = splitAccountsForPlan(list);
    let html = '';
    split.visible.forEach((a) => {
      html += renderSmtpCard(a);
    });
    split.lockedExtra.forEach((a) => {
      const overLimit = a.is_enabled && planInboxLimit() != null && planInboxUsed() > planInboxLimit();
      html += overLimit ? renderSmtpCard(a) : renderLockedSlotCard(a, 'Starter');
    });
    const showAdd = split.visible.length + split.lockedExtra.length < maxTransportSlots();
    if (showAdd && split.lockedExtra.length === 0) {
      if (canAddMailbox()) {
        html +=
          '<div class="mb-card mb-card-empty" data-action="add-smtp">' +
          '<i class="fa-solid fa-plus"></i> Add SMTP mailbox (' +
          list.length +
          '/' +
          maxTransportSlots() +
          ' slots)</div>';
      } else {
        html +=
          '<div class="mb-card mb-card-empty mb-card-locked" title="Plan inbox limit reached">' +
          '<i class="fa-solid fa-lock"></i> Inbox limit reached - <a href="/#pricing">upgrade</a> or pause another mailbox</div>';
      }
    }
    host.innerHTML = html;
    wireSmtpCards();
    enhanceMpSelects(host);
  }

  function closeMpSelect(root) {
    if (!root) return;
    root.classList.remove('is-open');
    const menu = root.querySelector('.mp-select-menu');
    const trigger = root.querySelector('.mp-select-trigger');
    if (menu) {
      menu.classList.remove('open');
      menu.hidden = true;
    }
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
  }

  function syncMpSelect(root) {
    const sel = root.querySelector('select');
    const textEl = root.querySelector('.mp-select-trigger-text');
    const menu = root.querySelector('.mp-select-menu');
    if (!sel || !textEl || !menu) return;
    const opt = sel.selectedOptions && sel.selectedOptions[0];
    textEl.textContent = opt ? opt.textContent : 'Select profile';
    menu.querySelectorAll('.mp-select-option').forEach(function (btn) {
      btn.classList.toggle('is-selected', String(btn.getAttribute('data-value') || '') === String(sel.value));
    });
  }

  function rebuildMpSelectMenu(root) {
    const sel = root.querySelector('select');
    const menu = root.querySelector('.mp-select-menu');
    if (!sel || !menu) return;
    menu.innerHTML = '';
    Array.prototype.forEach.call(sel.options, function (opt) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mp-select-option';
      btn.setAttribute('role', 'option');
      btn.setAttribute('data-value', opt.value);
      btn.textContent = opt.textContent || opt.value;
      btn.addEventListener('click', function () {
        if (String(sel.value) !== String(opt.value)) {
          sel.value = opt.value;
          sel.dispatchEvent(new Event('change', { bubbles: true }));
        }
        syncMpSelect(root);
        closeMpSelect(root);
      });
      menu.appendChild(btn);
    });
    syncMpSelect(root);
  }

  function enhanceMpSelects(scope) {
    const rootEl = scope || document;
    rootEl.querySelectorAll('[data-mp-select]').forEach(function (root) {
      if (root.dataset.mpBound === '1') {
        rebuildMpSelectMenu(root);
        return;
      }
      root.dataset.mpBound = '1';
      const trigger = root.querySelector('.mp-select-trigger');
      const menu = root.querySelector('.mp-select-menu');
      if (!trigger || !menu) return;
      rebuildMpSelectMenu(root);
      trigger.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        const open = !root.classList.contains('is-open');
        document.querySelectorAll('[data-mp-select].is-open').forEach(function (other) {
          if (other !== root) closeMpSelect(other);
        });
        if (open) {
          root.classList.add('is-open');
          menu.hidden = false;
          menu.classList.add('open');
          trigger.setAttribute('aria-expanded', 'true');
          syncMpSelect(root);
        } else {
          closeMpSelect(root);
        }
      });
    });
    if (!document.body.dataset.mpSelectDocBound) {
      document.body.dataset.mpSelectDocBound = '1';
      document.addEventListener('click', function (e) {
        document.querySelectorAll('[data-mp-select].is-open').forEach(function (root) {
          if (!root.contains(e.target)) closeMpSelect(root);
        });
      });
      document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        document.querySelectorAll('[data-mp-select].is-open').forEach(closeMpSelect);
      });
    }
  }

  function renderSmtpCard(a) {
    const plan = mailboxPlanState(a);
    const c = a.config || {};
    const paused = !a.is_enabled;
    const verified = a.smtp_last_test_ok;
    const statusCls = plan.locked ? 'warn' : verified ? (paused ? 'info' : 'ok') : '';
    const statusTxt = plan.locked
      ? plan.reason === 'over_limit'
        ? 'Over limit'
        : 'Locked'
      : verified
        ? paused
          ? 'Paused'
          : 'Verified'
        : 'Not verified';
    const toggleDisabled = plan.locked ? !plan.canDisable : !plan.canEnable && !a.is_enabled;
    const fieldsBlock =
      '<div class="mb-smtp-fields" data-smtp-id="' +
      a.id +
      '">' +
      smtpFieldsHtml(a, c) +
      '</div>' +
      '<div class="mb-card-actions">' +
      '<button type="button" class="btn btn-purp btn-sm" data-save-smtp="' +
      a.id +
      '">Save</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-test-smtp="' +
      a.id +
      '">Test SMTP</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-del-smtp="' +
      a.id +
      '">Remove</button>' +
      '</div>' +
      '<span class="pill mini-pill" id="smtpStatus-' +
      a.id +
      '">-</span>';
    return (
      '<article class="mb-card mb-smtp-card' +
      (paused ? ' mb-paused' : '') +
      (plan.locked ? ' mb-card-plan-locked' : '') +
      '" data-account-id="' +
      a.id +
      '">' +
      '<header class="mb-card-hd">' +
      '<div class="mb-card-title"><span class="mb-slot">#' +
      a.slot +
      '</span> ' +
      esc(a.label || c.SMTP_USERNAME || 'SMTP') +
      '</div>' +
      '<label class="mb-switch"><input type="checkbox" class="mb-enable-smtp" data-id="' +
      a.id +
      '" ' +
      (a.is_enabled ? 'checked' : '') +
      (toggleDisabled ? ' disabled' : '') +
      '><span class="mb-switch-ui"></span></label>' +
      '<span class="pill ' +
      statusCls +
      '">' +
      statusTxt +
      '</span>' +
      '</header>' +
      planLockBannerHtml(plan.lockNote) +
      '<div class="mb-card-body-lock">' +
      fieldsBlock +
      '</div>' +
      '</article>'
    );
  }

  function smtpFieldsHtml(a, c) {
    const passPh = a.has_smtp_password ? 'Re-enter only to change' : 'Required - enter to save';
    return (
      '<div class="row2"><div class="fg"><label class="fl">SMTP Host</label>' +
      '<input class="fi smtp-host" value="' +
      esc(c.SMTP_HOST || '') +
      '"></div>' +
      '<div class="fg"><label class="fl">Port</label>' +
      '<input class="fi smtp-port" type="number" value="' +
      (c.SMTP_PORT || 587) +
      '"></div></div>' +
      '<div class="row2"><div class="fg"><label class="fl">Username</label>' +
      '<input class="fi smtp-user" value="' +
      esc(c.SMTP_USERNAME || '') +
      '"></div>' +
      '<div class="fg"><label class="fl">Password</label>' +
      '<input class="fi smtp-pass" type="password" autocomplete="new-password" placeholder="' +
      attrEsc(passPh) +
      '"></div></div>' +
      '<div class="fg"><label class="fl">From (optional)</label>' +
      '<input class="fi smtp-from" value="' +
      esc(c.SMTP_FROM_EMAIL || '') +
      '"></div>' +
      '<div class="fg"><label class="fl">Provider safety profile</label>' +
      '<div class="mp-select" data-mp-select>' +
      '<select class="fi provider-profile" tabindex="-1" aria-hidden="true">' +
      '<option value="smtp_personal"' +
      ((c.PROVIDER_PROFILE || 'smtp_personal') === 'smtp_personal' ? ' selected' : '') +
      '>Personal SMTP · 100/day safety cap</option>' +
      '<option value="smtp_business"' +
      (c.PROVIDER_PROFILE === 'smtp_business' ? ' selected' : '') +
      '>Business SMTP · 1500/day provider cap</option>' +
      '</select>' +
      '<button type="button" class="mp-select-trigger" aria-haspopup="listbox" aria-expanded="false">' +
      '<span class="mp-select-trigger-text"></span>' +
      '<i class="fa-solid fa-chevron-down" aria-hidden="true"></i>' +
      '</button>' +
      '<div class="mp-select-menu" role="listbox" hidden></div>' +
      '</div></div>' +
      '<div class="oauth-h" style="margin-top:12px;margin-bottom:8px;">IMAP (read inbox)</div>' +
      '<div class="fg"><label class="fl">IMAP host (optional)</label>' +
      '<input class="fi imap-host" value="' +
      esc(c.IMAP_HOST || '') +
      '" placeholder="imap.example.com"></div>' +
      '<div class="row2"><div class="fg"><label class="fl">IMAP port</label>' +
      '<input class="fi imap-port" type="number" min="1" max="65535" value="' +
      (c.IMAP_PORT || 993) +
      '" required></div>' +
      '<div class="fg"><label class="fl">SMTP TLS name (cert mismatch)</label>' +
      '<input class="fi smtp-tls-name" value="' +
      esc(c.SMTP_TLS_SERVERNAME || '') +
      '" placeholder="timerni.com"></div></div>' +
      '<div class="fg" style="margin-bottom:0;"><label class="fl">IMAP TLS name (optional)</label>' +
      '<input class="fi imap-tls-name" value="' +
      esc(c.IMAP_TLS_SERVERNAME || '') +
      '" placeholder="timerni.com"></div>'
    );
  }

  function smtpAccountById(id) {
    return mailAccounts.find((a) => String(a.id) === String(id));
  }

  function smtpPasswordReady(card, account) {
    const pass = (card.querySelector('.smtp-pass')?.value || '').trim();
    if (pass) return true;
    return !!(account && account.has_smtp_password);
  }

  function smtpPayloadFromCard(card) {
    const payload = {
      SMTP_HOST: card.querySelector('.smtp-host')?.value || '',
      SMTP_PORT: parseInt(card.querySelector('.smtp-port')?.value || '587', 10),
      SMTP_USERNAME: card.querySelector('.smtp-user')?.value || '',
      SMTP_FROM_EMAIL: card.querySelector('.smtp-from')?.value || '',
      IMAP_HOST: card.querySelector('.imap-host')?.value || '',
      IMAP_PORT: parseInt(card.querySelector('.imap-port')?.value || '993', 10),
      SMTP_TLS_SERVERNAME: card.querySelector('.smtp-tls-name')?.value || '',
      IMAP_TLS_SERVERNAME: card.querySelector('.imap-tls-name')?.value || '',
      PROVIDER_PROFILE: card.querySelector('.provider-profile')?.value || 'smtp_personal',
      SMTP_USE_TLS: true,
      SMTP_USE_SSL: false,
      SMTP_VERIFY_TLS: true,
      IMAP_VERIFY_TLS: true,
    };
    const pass = card.querySelector('.smtp-pass')?.value || '';
    if (pass) payload.SMTP_PASSWORD = pass;
    return payload;
  }

  function wireSmtpCards() {
    document.querySelectorAll('.mb-enable-smtp').forEach((inp) => {
      inp.addEventListener('change', async () => {
        const account = mailAccounts.find((a) => String(a.id) === String(inp.dataset.id));
        const plan = account ? mailboxPlanState(account) : { canEnable: true };
        if (inp.checked && !plan.canEnable) {
          inp.checked = false;
          showPlanError({ upgrade_required: true, error: 'plan_inbox_limit_reached' }, 'Could not enable mailbox');
          return;
        }
        const { res, j } = await apiJson('/api/mail-accounts/' + inp.dataset.id + '/', {
          method: 'PATCH',
          body: JSON.stringify({ is_enabled: inp.checked }),
        });
        if (!res.ok || !j.ok) {
          inp.checked = !inp.checked;
          showPlanError(j, 'Could not update mailbox');
        }
        await loadMailAccounts();
      });
    });
    document.querySelectorAll('[data-save-smtp]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const card = btn.closest('.mb-smtp-card');
        const id = btn.dataset.saveSmtp;
        const account = smtpAccountById(id);
        const pill = document.getElementById('smtpStatus-' + id);
        if (!smtpPasswordReady(card, account)) {
          if (typeof window.setPill === 'function') {
            window.setPill(pill, 'Enter SMTP password and Save', 'bad');
          }
          return;
        }
        const payload = smtpPayloadFromCard(card);
        const { res, j } = await apiJson('/api/mail-accounts/' + id + '/', {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        if (res.ok && j.ok) {
          if (typeof window.setPill === 'function') window.setPill(pill, 'Saved', 'ok');
          card.querySelector('.smtp-pass').value = '';
          await loadMailAccounts();
        } else if (typeof window.setPill === 'function') {
          window.setPill(pill, j.error || 'Save failed', 'bad');
        }
      });
    });
    document.querySelectorAll('[data-test-smtp]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.testSmtp;
        const card = btn.closest('.mb-smtp-card');
        const account = smtpAccountById(id);
        const pill = document.getElementById('smtpStatus-' + id);
        if (!smtpPasswordReady(card, account)) {
          if (typeof window.setPill === 'function') {
            window.setPill(pill, 'Enter SMTP password first', 'bad');
          }
          return;
        }
        await apiJson('/api/mail-accounts/' + id + '/', {
          method: 'PATCH',
          body: JSON.stringify(smtpPayloadFromCard(card)),
        });
        if (typeof window.setPill === 'function') window.setPill(pill, 'Sending test mail…', 'info');
        const { res, j } = await apiJson('/api/mail-accounts/' + id + '/test-smtp', { method: 'POST', body: '{}' });
        if (typeof window.setPill === 'function') {
          const ok = res.ok && j.ok;
          const msg = ok
            ? 'Test mail sent to ' + (j.sent_to || 'mailbox')
            : j.error || 'Failed';
          window.setPill(pill, msg, ok ? 'ok' : 'bad');
        }
        if (res.ok && j.ok) card.querySelector('.smtp-pass').value = '';
        await loadMailAccounts();
      });
    });
    document.querySelectorAll('[data-del-smtp]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Remove this SMTP mailbox?')) return;
        await apiJson('/api/mail-accounts/' + btn.dataset.delSmtp + '/', { method: 'DELETE', body: '{}' });
        await loadMailAccounts();
      });
    });
    document.querySelector('[data-action="add-smtp"]')?.addEventListener('click', async () => {
      const { res, j } = await apiJson('/api/mail-accounts/create', { method: 'POST', body: JSON.stringify({ transport: 'smtp' }) });
      if (!res.ok || !j.ok) showPlanError(j, 'Could not add SMTP mailbox');
      await loadMailAccounts();
    });
  }

  function populateKbAccountSelect() {
    const sel = document.getElementById('kbAccountSelect');
    if (!sel) return;
    const mode = transportSummary.active_mode || 'gmail';
    const tr = mode === 'smtp' ? 'smtp' : 'gmail_api';
    const list = mailAccounts.filter((a) => a.transport === tr);
    sel.innerHTML = '';
    list.forEach((a) => {
      const opt = document.createElement('option');
      opt.value = a.id;
      opt.textContent = (a.email || a.label || 'Slot ' + a.slot) + (a.is_enabled ? '' : ' (paused)');
      sel.appendChild(opt);
    });
    if (list.length && !kbSelectedAccountId) kbSelectedAccountId = list[0].id;
    if (kbSelectedAccountId) sel.value = String(kbSelectedAccountId);
    sel.onchange = () => {
      kbSelectedAccountId = parseInt(sel.value, 10);
      if (typeof window.refreshKbStatus === 'function') window.refreshKbStatus();
    };
  }

  window.getKbAccountId = function () {
    const sel = document.getElementById('kbAccountSelect');
    if (sel && sel.value) return sel.value;
    return kbSelectedAccountId || '';
  };

  window.kbAccountQuery = function () {
    const id = window.getKbAccountId();
    return id ? '?account_id=' + encodeURIComponent(id) : '';
  };

  function wireSharedSecretFix() {
    const btn = document.getElementById('btnSaveSharedSecret');
    const input = document.getElementById('sharedGocspx');
    const status = document.getElementById('sharedSecretFixStatus');
    if (!btn || !input) return;
    btn.addEventListener('click', async () => {
      const secret = (input.value || '').trim();
      if (!secret) {
        if (status) status.textContent = 'Paste the GOCSPX secret first.';
        return;
      }
      btn.disabled = true;
      if (status) status.textContent = 'Saving…';
      const { res, j } = await apiJson('/api/gmail/shared-client-secret', {
        method: 'POST',
        body: JSON.stringify({ client_secret: secret }),
      });
      if (!res.ok || !j.ok) {
        if (status) status.textContent = (j && j.error) || 'Could not save secret';
        btn.disabled = false;
        return;
      }
      if (status) status.textContent = 'Saved. Starting Connect…';
      // Clear sticky oauth error so auto-retry / manual connect works.
      try {
        sessionStorage.clear();
      } catch (_) {}
      const gmail = (mailAccounts || []).find((a) => a.transport === 'gmail_api') || null;
      if (gmail) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/api/mail-accounts/' + gmail.id + '/connect-oauth';
        const csrf = document.createElement('input');
        csrf.type = 'hidden';
        csrf.name = 'csrfmiddlewaretoken';
        csrf.value = csrfToken();
        form.appendChild(csrf);
        document.body.appendChild(form);
        form.submit();
        return;
      }
      window.location.href = '/setup';
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const banner = document.getElementById('transportModeBanner');
    const highlight = banner?.dataset?.highlightAccount || '';
    const initialMode = banner?.dataset?.initialMode || 'gmail';
    if (highlight) document.body.dataset.highlightAccount = highlight;
    wireSharedSecretFix();
    loadMailAccounts().then(() => {
      if (initialMode === 'smtp') {
        document.getElementById('tabG')?.classList.remove('on');
        document.getElementById('tabS')?.classList.add('on');
        document.getElementById('pGmail')?.classList.remove('on');
        document.getElementById('pSmtp')?.classList.add('on');
      } else if (initialMode === 'microsoft') {
        document.getElementById('tabG')?.classList.remove('on');
        document.getElementById('tabM')?.classList.add('on');
        document.getElementById('pGmail')?.classList.remove('on');
        document.getElementById('pMicrosoft')?.classList.add('on');
      }
    });
  });

  window.loadMailAccounts = loadMailAccounts;
  window.cpRedirect = function () {
    if (!OAUTH_REDIRECT_URI) return;
    navigator.clipboard?.writeText(OAUTH_REDIRECT_URI);
  };
})();
