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
    return a.email || a.label || 'Gmail mailbox';
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
              'Over plan limit - pause this mailbox to stay within your plan, or <a href="/pricing/">upgrade</a>.',
          };
        }
      }
      return { locked: false, canEnable: false, canDisable: true, reason: '', lockNote: '' };
    }

    if (atLimit) {
      const primary = primaryEnabledMailbox();
      let lockNote =
        'Plan inbox limit reached - pause another mailbox or <a href="/pricing/">upgrade</a>.';
      if (lim === 1 && primary) {
        const transportLabel = primary.transport === 'gmail_api' ? 'Gmail' : 'SMTP';
        lockNote =
          'Starter allows <strong>1 inbox</strong>. Active: <strong>' +
          esc(mailboxDisplayName(primary)) +
          '</strong> (' +
          transportLabel +
          '). Pause it to use this slot, or <a href="/pricing/">upgrade</a>.';
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
      ' allows 1 active inbox). <a href="/pricing/">Upgrade</a> to use more slots.' +
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
    const transportLabel = primary.transport === 'gmail_api' ? 'Gmail' : 'SMTP';
    el.style.display = '';
    el.innerHTML =
      '<div class="oauth-h"><i class="fa-solid fa-lock" aria-hidden="true"></i> ' +
      transportLabel +
      ' is using your inbox slot</div>' +
      '<p class="oauth-txt" style="margin:0;">Starter allows one active inbox. <strong>' +
      esc(mailboxDisplayName(primary)) +
      '</strong> is active on ' +
      transportLabel +
      '. Pause it to configure this transport, or <a href="/pricing/" style="color:#c4b5fd;font-weight:800;">upgrade</a>.</p>';
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
        '<p class="oauth-txt" style="margin:0;">Complete checkout for your plan before adding or enabling mailboxes. <a href="/pricing/" style="color:#c4b5fd;font-weight:800;">Go to Pricing</a></p>';
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
        : 'Your plan allows <strong>' + lim + '</strong> active inbox' + (lim === 1 ? '' : 'es') + ' total across Gmail and SMTP.';
    const gmailHint = document.getElementById('gmailInboxHint');
    const smtpHint = document.getElementById('smtpInboxHint');
    if (gmailHint) gmailHint.innerHTML = planTxt + ' Toggle each mailbox on/off. Only accounts in <strong>Gmail mode</strong> run automation.';
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
    renderSmtpAccounts();
    populateKbAccountSelect();
    updateTransportPill();
    renderTransportPlanNotice('gmailPlanNotice', 'gmail_api');
    renderTransportPlanNotice('smtpPlanNotice', 'smtp');
  }

  function renderTransportBanner() {
    const el = document.getElementById('transportModeBanner');
    if (!el) return;
    const mode = transportSummary.active_mode || 'gmail';
    const modeEnabled = transportSummary.enabled_count ?? 0;
    const planUsed = planInboxUsed();
    const planLim = planInboxLimit();
    const inactive = mode === 'gmail' ? 'SMTP' : 'Gmail';
    const planPill =
      planLim == null
        ? planUsed + ' active inbox' + (planUsed === 1 ? '' : 'es')
        : planUsed + ' of ' + planLim + ' plan inbox' + (planLim === 1 ? '' : 'es');
    const pillTone = planLim != null && planUsed >= planLim ? 'warn' : planUsed > 0 ? 'ok' : 'bad';
    el.innerHTML =
      '<div class="mode-banner">' +
      '<span>Active transport: <strong>' +
      (mode === 'gmail' ? 'Gmail' : 'SMTP') +
      '</strong> · ' +
      modeEnabled +
      ' in this mode</span>' +
      '<span class="pill ' +
      pillTone +
      '">' +
      planPill +
      '</span>' +
      '<span class="mode-muted">' +
      inactive +
      ' mode inactive - switch tab to use</span>' +
      '</div>';
  }

  function updateTransportPill() {
    const tp = document.getElementById('transportPill');
    if (!tp) return;
    const mode = transportSummary.active_mode || 'gmail';
    const planUsed = planInboxUsed();
    const planLim = planInboxLimit();
    let label =
      mode === 'gmail' ? 'Gmail mode' : 'SMTP mode';
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
    const smtpOn = which === 'smtp';
    document.getElementById('tabG')?.classList.toggle('on', !smtpOn);
    document.getElementById('tabS')?.classList.toggle('on', smtpOn);
    document.getElementById('pGmail')?.classList.toggle('on', !smtpOn);
    document.getElementById('pSmtp')?.classList.toggle('on', smtpOn);
    const mode = smtpOn ? 'smtp' : 'gmail';
    if ((transportSummary.active_mode || 'gmail') !== mode) {
      await setTransportMode(mode);
    }
  };

  function gmailAccounts() {
    return mailAccounts.filter((a) => a.transport === 'gmail_api');
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
          '<i class="fa-solid fa-lock"></i> Inbox limit reached - <a href="/pricing/">upgrade</a> or pause another mailbox</div>';
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
            : '') + renderGmailConnectForm(a, mismatch));
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
    return (
      '<form class="mb-connect-form" method="POST" action="/api/mail-accounts/' +
      a.id +
      '/setup-credentials" enctype="multipart/form-data">' +
      '<input type="hidden" name="csrfmiddlewaretoken" value="' +
      csrfToken() +
      '">' +
      (forceReconnect
        ? '<p class="small" style="margin:0 0 8px;color:var(--txm);">Sign in with <strong>' +
          esc(addr || 'this Gmail address') +
          '</strong> when Google asks.</p>'
        : '') +
      '<div class="fg"><label class="fl">Email</label>' +
      '<input class="fi" type="email" name="gmail_address" placeholder="you@company.com" required' +
      emailVal +
      '></div>' +
      '<div class="fg"><label class="fl">credentials.json</label>' +
      '<input class="fi" type="file" name="client_secret" accept="application/json" required></div>' +
      '<button type="submit" class="btn btn-purp btn-block"><i class="fa-brands fa-google"></i> Connect OAuth</button>' +
      '</form>'
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
        await apiJson('/api/mail-accounts/' + btn.dataset.disc + '/disconnect-gmail/', { method: 'POST', body: '{}' });
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
        if (!res.ok || !j.ok) showPlanError(j, 'Could not add Gmail mailbox');
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
          '<i class="fa-solid fa-lock"></i> Inbox limit reached - <a href="/pricing/">upgrade</a> or pause another mailbox</div>';
      }
    }
    host.innerHTML = html;
    wireSmtpCards();
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
      '<select class="fi provider-profile">' +
      '<option value="smtp_personal"' +
      ((c.PROVIDER_PROFILE || 'smtp_personal') === 'smtp_personal' ? ' selected' : '') +
      '>Personal SMTP · 100/day safety cap</option>' +
      '<option value="smtp_business"' +
      (c.PROVIDER_PROFILE === 'smtp_business' ? ' selected' : '') +
      '>Business SMTP · 1500/day provider cap</option>' +
      '</select></div>' +
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

  document.addEventListener('DOMContentLoaded', () => {
    const banner = document.getElementById('transportModeBanner');
    const highlight = banner?.dataset?.highlightAccount || '';
    const initialMode = banner?.dataset?.initialMode || 'gmail';
    if (highlight) document.body.dataset.highlightAccount = highlight;
    loadMailAccounts().then(() => {
      if (initialMode === 'smtp') {
        document.getElementById('tabG')?.classList.remove('on');
        document.getElementById('tabS')?.classList.add('on');
        document.getElementById('pGmail')?.classList.remove('on');
        document.getElementById('pSmtp')?.classList.add('on');
      }
    });
  });

  window.loadMailAccounts = loadMailAccounts;
  window.cpRedirect = function () {
    if (!OAUTH_REDIRECT_URI) return;
    navigator.clipboard?.writeText(OAUTH_REDIRECT_URI);
  };
})();
