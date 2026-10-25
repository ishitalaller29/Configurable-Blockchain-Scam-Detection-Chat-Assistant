// Chatbox page interactivity: Web front end for the same pipeline cli.py drives: each message is sent to server.py (POST /chat), which calls ChatSession.handle_message() and returns the reply the CLI would have printed after "Bot:". The reply is shown as-is.

document.addEventListener('DOMContentLoaded', () => {
  const backToStart = document.getElementById('backToStart');
  const chatInput = document.getElementById('chatInput');
  const thread = document.getElementById('thread');
  const promptHint = document.getElementById('promptHint');
  const plusIcon = document.getElementById('plusIcon');
  const adminBtn = document.getElementById('adminBtn');
  const adminBtnLabel = document.getElementById('adminBtnLabel');
  const adminDialog = document.getElementById('adminDialog');
  const adminForm = document.getElementById('adminForm');
  const adminPass = document.getElementById('adminPass');
  const adminError = document.getElementById('adminError');
  const adminCancel = document.getElementById('adminCancel');
  const attachNote = document.getElementById('attachNote');
  const sidebar = document.getElementById('sidebar');
  const aiMsgTemplate = document.getElementById('aiMsgTemplate');
  const addSourceBtn = document.getElementById('addSourceBtn');
  const llmConfigRows = document.getElementById('llmConfigRows');
  const saveLlmConfigBtn = document.getElementById('saveLlmConfigBtn');
  const llmConfigStatus = document.getElementById('llmConfigStatus');
  const addSourceForm = document.getElementById('addSourceForm');
  const sourceNameInput = document.getElementById('sourceNameInput');
  const sourceUrlInput = document.getElementById('sourceUrlInput');
  const sourceCancelBtn = document.getElementById('sourceCancelBtn');
  const addSourceStatus = document.getElementById('addSourceStatus');
  const downloadStatus = document.getElementById('downloadStatus');
  const downloadTemplateBtn = document.getElementById('downloadTemplateBtn');
  const detectorSelect = document.getElementById('detectorSelect');
  const detectorStatus = document.getElementById('detectorStatus');
  const dataSourceList = document.getElementById('dataSourceList');
  const dataSourceStatus = document.getElementById('dataSourceStatus');

  function cloneTemplate(template) {
    return template.content.firstElementChild.cloneNode(true);
  }

  const API_BASE = window.location.protocol === 'file:'
    ? 'http://localhost:8000'
    : '';
  const CHAT_API_URL = API_BASE + '/chat';
  const CHAT_STATUS_URL = API_BASE + '/chat/status';
  const RESET_API_URL = API_BASE + '/session/reset';

  const sessionReady = fetch(RESET_API_URL, { method: 'POST' }).catch(() => {});

  backToStart.addEventListener('click', () => {
    window.location.href = '../starting-page/index.html';
  });

  // File attachments are not supported by the backend yet, so say so instead of faking an attachment.
  plusIcon.addEventListener('click', () => {
    attachNote.hidden = false;
    clearTimeout(plusIcon._noteTimer);
    plusIcon._noteTimer = setTimeout(() => { attachNote.hidden = true; }, 4000);
  });

  function clearThread() {
    thread.innerHTML = '';
    thread.appendChild(promptHint);
    promptHint.style.display = '';
  }

  // ---------- Connected sources (admin sidebar) ----------
  const DATA_SOURCES_URL = API_BASE + '/admin/data-sources';
  let dataSourcesState = null;

  function renderDataSources(data) {
    dataSourcesState = data;
    dataSourceList.innerHTML = '';
    data.data_sources.forEach(source => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'source-item' + (source.active ? ' active' : '');
      item.dataset.sourceId = source.id;
      item.setAttribute('aria-pressed', String(source.active));
      item.title = (source.active ? 'On - click to stop calling ' : 'Off - click to start calling ') + source.name;
      item.textContent = source.name + ' API';
      const state = document.createElement('span');
      state.className = 'source-state';
      state.textContent = source.active ? 'On' : 'Off';
      const dot = document.createElement('span');
      dot.className = 'source-dot';
      state.appendChild(dot);
      item.appendChild(state);
      dataSourceList.appendChild(item);
    });
  }

  async function loadDataSources() {
    try {
      const res = await fetch(DATA_SOURCES_URL);
      if (!res.ok) throw new Error('bad status');
      renderDataSources(await res.json());
      dataSourceStatus.textContent = '';
    } catch (err) {
      dataSourceStatus.textContent = 'Could not load data sources from the server.';
    }
  }

  dataSourceList.addEventListener('click', async (e) => {
    const item = e.target.closest('.source-item');
    if (!item || !dataSourcesState) return;
    const id = item.dataset.sourceId;
    const active = dataSourcesState.data_sources.filter(s => s.active).map(s => s.id);
    const next = active.includes(id) ? active.filter(s => s !== id) : [...active, id];
    if (!next.length) {
      dataSourceStatus.textContent = 'At least one data source has to stay on.';
      return;
    }

    dataSourceStatus.textContent = 'Saving…';
    try {
      const res = await fetch(DATA_SOURCES_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active_data_sources: next }),
      });
      if (!res.ok) throw new Error('bad status');
      renderDataSources(await res.json());
      clearThread();
      dataSourceStatus.textContent = 'Saved - new conversation started.';
    } catch (err) {
      dataSourceStatus.textContent = 'Failed to change data sources.';
      loadDataSources();
    }
  });

  sidebar.addEventListener('click', (e) => {
    const item = e.target.closest('.source-item');
    if (!item || dataSourceList.contains(item)) return;
    sidebar.querySelectorAll('.source-item').forEach(i => {
      if (!dataSourceList.contains(i)) i.classList.remove('active');
    });
    item.classList.add('active');
  });

  // ---------- Add source ----------
  // "+ add source" opens a small form for the address of a running Detector API Wrapper (the container built from the downloadable template). The server checks that the wrapper is up and has a detector set up, then lists it under Active Detector below.
  const SOURCES_URL = API_BASE + '/admin/sources';
  const TEMPLATE_URL = API_BASE + '/admin/wrapper-template';

  // Error replies carry a readable `detail`; fall back to a generic line if there isn't one.
  async function errorDetail(res, fallback) {
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') return body.detail;
    } catch (err) { /* not JSON */ }
    return fallback;
  }

  function addSourceItem(id, name) {
    if (!addSourceBtn || !addSourceBtn.parentNode) return;
    const exists = Array.from(sidebar.querySelectorAll('.source-item'))
      .some(el => el.dataset.source === id);
    if (exists) return;
    const item = document.createElement('div');
    item.className = 'source-item';
    item.tabIndex = 0;
    item.dataset.source = id;
    item.appendChild(document.createTextNode(name || id));
    const dot = document.createElement('span');
    dot.className = 'source-dot';
    item.appendChild(dot);
    addSourceBtn.parentNode.insertBefore(item, addSourceBtn);
  }

  function setAddSourceOpen(open) {
    if (!addSourceForm) return;
    addSourceForm.style.display = open ? 'block' : 'none';
    if (open && sourceNameInput) sourceNameInput.focus();
    if (!open && addSourceStatus) addSourceStatus.textContent = '';
  }

  if (!addSourceBtn || !addSourceForm) {
    console.warn('Add source controls are missing from the page.');
  } else {
    addSourceBtn.addEventListener('click', () => {
      setAddSourceOpen(addSourceForm.style.display === 'none');
    });

    if (sourceCancelBtn) {
      sourceCancelBtn.addEventListener('click', () => setAddSourceOpen(false));
    }

    addSourceForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = sourceNameInput ? sourceNameInput.value.trim() : '';
      const url = sourceUrlInput ? sourceUrlInput.value.trim() : '';
      if (!name || !url) {
        if (addSourceStatus) addSourceStatus.textContent = 'Enter a name and the wrapper address.';
        return;
      }
      if (addSourceStatus) addSourceStatus.textContent = 'Checking the wrapper…';
      try {
        const res = await fetch(SOURCES_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, url }),
        });
        if (!res.ok) {
          if (addSourceStatus) addSourceStatus.textContent = await errorDetail(res, 'Could not add the source.');
          return;
        }
        const data = await res.json();
        addSourceItem(data.added.id, data.added.name);
        renderDetectorConfig(data.config);
        if (sourceNameInput) sourceNameInput.value = '';
        if (sourceUrlInput) sourceUrlInput.value = '';
        setAddSourceOpen(false);
        if (detectorStatus) detectorStatus.textContent = `Added "${data.added.name}". Choose it here to use it.`;
      } catch (err) {
        if (addSourceStatus) addSourceStatus.textContent = 'Could not reach the server.';
      }
    });
  }

  // Downloads the wrapper's Docker setup (Dockerfile, docker-compose.yml, .env.example and source) as a ZIP. The steps under the button say how to run it.
  if (!downloadTemplateBtn) {
    console.warn('Download template button is missing from the page.');
  } else {
    downloadTemplateBtn.addEventListener('click', async () => {
      if (downloadStatus) downloadStatus.textContent = 'Preparing the download…';
      try {
        const res = await fetch(TEMPLATE_URL);
        if (!res.ok) {
          if (downloadStatus) downloadStatus.textContent = await errorDetail(res, 'The template could not be downloaded.');
          return;
        }
        const blob = await res.blob();
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'detector-api-wrapper-template.zip';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(link.href);
        if (downloadStatus) downloadStatus.textContent = 'Downloaded. Follow the steps below to run it.';
      } catch (err) {
        if (downloadStatus) downloadStatus.textContent = 'Could not reach the server.';
      }
    });
  }

  // ---------- Admin password gate ----------
  // Hardcoded shared passphrase per the client's own suggestion (confirmed
  // in the technical advisor meeting as the simplest acceptable approach -
  // real auth/accounts are explicitly out of scope for this project).
  const ADMIN_PASSPHRASE = 'admin';

  let adminOn = false;

  function setAdmin(on) {
    adminOn = on;
    sidebar.style.display = on ? 'block' : 'none';
    adminBtn.classList.toggle('active', on);
    adminBtn.setAttribute('aria-pressed', String(on));
    adminBtnLabel.textContent = on ? 'Admin (exit)' : 'Admin';
    if (on) {
      loadDataSources();
      loadLlmConfig();
      loadDetectorConfig();
    }
  }

  function closeAdminDialog() {
    adminDialog.hidden = true;
    adminPass.value = '';
    adminError.hidden = true;
    adminBtn.focus();
  }

  adminBtn.addEventListener('click', () => {
    if (adminOn) {
      setAdmin(false);
      return;
    }
    adminDialog.hidden = false;
    adminPass.focus();
  });

  adminForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (adminPass.value === ADMIN_PASSPHRASE) {
      closeAdminDialog();
      setAdmin(true);
    } else {
      adminError.hidden = false;
      adminPass.select();
    }
  });

  adminCancel.addEventListener('click', closeAdminDialog);
  adminDialog.addEventListener('click', (e) => {
    if (e.target === adminDialog) closeAdminDialog();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !adminDialog.hidden) closeAdminDialog();
  });

  // ---------- LLM Backend config (FR-14) ----------
  const AGENT_LABELS = {
    business_analyser: 'Business Analyser',
    scam_checker: 'Scam Checker',
    forensic_investigator: 'Forensic Investigator',
  };

  const LLM_CONFIG_URL = API_BASE + '/admin/llm-config';
  let llmConfigState = null;

  function renderLlmConfig(data) {
    llmConfigState = data;
    llmConfigRows.innerHTML = '';

    Object.keys(AGENT_LABELS).forEach(agentKey => {
      const agentConfig = data.config[agentKey];
      if (!agentConfig) return;

      const row = document.createElement('div');
      row.className = 'llm-agent-row';
      row.dataset.agent = agentKey;

      const label = document.createElement('p');
      label.className = 'llm-agent-label';
      label.textContent = AGENT_LABELS[agentKey];
      row.appendChild(label);

      const select = document.createElement('select');
      select.className = 'llm-provider-select';
      data.supported_providers.forEach(provider => {
        const opt = document.createElement('option');
        opt.value = provider;
        opt.textContent = provider;
        if (provider === agentConfig.provider) opt.selected = true;
        select.appendChild(opt);
      });
      row.appendChild(select);

      const modelInput = document.createElement('input');
      modelInput.type = 'text';
      modelInput.className = 'llm-model-input';
      modelInput.placeholder = 'Model name';
      modelInput.value = agentConfig.model || '';
      row.appendChild(modelInput);

      const note = document.createElement('p');
      note.className = 'llm-provider-note';
      const isFunctional = data.functional_providers.includes(agentConfig.provider);
      note.textContent = isFunctional
        ? ''
        : 'Selected, but not yet functional - wired up in Sprint 3.';
      note.style.display = isFunctional ? 'none' : 'block';
      row.appendChild(note);

      select.addEventListener('change', () => {
        const functional = data.functional_providers.includes(select.value);
        note.textContent = functional
          ? ''
          : 'Selected, but not yet functional - wired up in Sprint 3.';
        note.style.display = functional ? 'none' : 'block';
      });

      llmConfigRows.appendChild(row);
    });
  }

  async function loadLlmConfig() {
    try {
      const res = await fetch(LLM_CONFIG_URL);
      if (!res.ok) throw new Error('bad status');
      const data = await res.json();
      renderLlmConfig(data);
      llmConfigStatus.textContent = '';
    } catch (err) {
      llmConfigStatus.textContent = 'Could not load LLM config from the server.';
    }
  }

  saveLlmConfigBtn.addEventListener('click', async () => {
    if (!llmConfigState) return;
    const config = {};
    llmConfigRows.querySelectorAll('.llm-agent-row').forEach(row => {
      const agentKey = row.dataset.agent;
      const provider = row.querySelector('.llm-provider-select').value;
      const model = row.querySelector('.llm-model-input').value.trim();
      const existing = llmConfigState.config[agentKey] || {};
      config[agentKey] = {
        provider,
        model,
        base_url: existing.base_url || null,
        api_key: existing.api_key || null,
      };
    });

    llmConfigStatus.textContent = 'Saving…';
    try {
      const res = await fetch(LLM_CONFIG_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config }),
      });
      if (!res.ok) throw new Error('bad status');
      const data = await res.json();
      renderLlmConfig(data);
      llmConfigStatus.textContent = 'Saved.';
    } catch (err) {
      llmConfigStatus.textContent = 'Failed to save LLM config.';
    }
  });

  // ---------- Active detector ----------
  // Picks which detector answers scam checks. "None" sends them to the ScamChecker. Saving starts a fresh conversation on the server, so the thread is cleared to match.
  const DETECTOR_CONFIG_URL = API_BASE + '/admin/detector';
  const NO_DETECTOR = '';

  function renderDetectorConfig(data) {
    if (!detectorSelect) return;
    detectorSelect.innerHTML = '';

    const none = document.createElement('option');
    none.value = NO_DETECTOR;
    none.textContent = 'None (Scam Checker)';
    detectorSelect.appendChild(none);

    data.detectors.forEach(detector => {
      // Wrappers added earlier show under Connected sources too.
      if (detector.id.startsWith('wrapper_')) addSourceItem(detector.id, detector.name);
      const opt = document.createElement('option');
      opt.value = detector.id;
      opt.textContent = detector.name || detector.id;
      if (detector.status !== 'live') opt.textContent += ' (may be unavailable)';
      detectorSelect.appendChild(opt);
    });
    detectorSelect.value = data.active_detector || NO_DETECTOR;
    detectorSelect.disabled = data.env_override;
    if (detectorStatus) {
      detectorStatus.textContent = data.env_override
        ? 'Set by ACTIVE_DETECTOR on the server - unset it to choose here.'
        : '';
    }
  }

  async function loadDetectorConfig() {
    try {
      const res = await fetch(DETECTOR_CONFIG_URL);
      if (!res.ok) throw new Error('bad status');
      renderDetectorConfig(await res.json());
    } catch (err) {
      if (detectorStatus) detectorStatus.textContent = 'Could not load detectors from the server.';
    }
  }

  if (detectorSelect) {
    detectorSelect.addEventListener('change', async () => {
      const chosen = detectorSelect.value;
      if (detectorStatus) detectorStatus.textContent = 'Saving…';
      try {
        const res = await fetch(DETECTOR_CONFIG_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active_detector: chosen === NO_DETECTOR ? null : chosen }),
        });
        if (!res.ok) throw new Error('bad status');
        renderDetectorConfig(await res.json());
        clearThread();
        if (detectorStatus) detectorStatus.textContent = 'Saved - new conversation started.';
      } catch (err) {
        if (detectorStatus) detectorStatus.textContent = 'Failed to change detector.';
        loadDetectorConfig();
      }
    });
  }

  function appendUserMsg(text) {
    const div = document.createElement('div');
    div.className = 'msg-user';
    div.textContent = text;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
    return div;
  }

  // Text is set with textContent, so a reply is always shown literally. `label` overrides the template's "AI generated response" label.
  function appendAiMsg(text, extraClass, label) {
    const div = cloneTemplate(aiMsgTemplate);
    if (extraClass) div.classList.add(extraClass);
    if (label) div.querySelector('.msg-ai-label-text').textContent = label;
    div.querySelector('.msg-ai-text').textContent = text;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
    return div;
  }

  // ---------- Rendering the backend's response ----------
  const STATUS_TAGS = {
    scam: { text: 'Scam', className: 'status-scam' },
    not_scam: { text: 'Not scam', className: 'status-benign' },
    insufficient_evidence: { text: 'Insufficient evidence', className: 'status-insufficient' },
  };

  // Mirrors conversation.SOURCE_WORDS so both front ends name the source identically. Unknown values fall through and render as-is.
  const SOURCE_WORDS = {
    scam_checker: 'Scam Checker (no detector configured)',
    detector: 'Configured detector',
  };

  // Mirrors conversation.MISSING_FIELD_WORDS.
  const MISSING_FIELD_WORDS = {
    contract: 'contract details',
    tx_history: 'transaction history',
    tokens: 'token balances',
    liquidity: 'liquidity pool data',
  };

  // ---------- Jargon definitions (hover tips) ----------
  // Plain-language definitions for blockchain terms that appear in replies. Each entry lists the spellings to match. Matching ignores case, and only the first use of a term in a message is bolded, so a reply isn't covered in highlights.
  const GLOSSARY = [
    { forms: ['liquidity pools', 'liquidity pool'], definition: 'A shared pot of two tokens that lets people trade one for the other. If it is small, or one person can empty it, trading can be risky.' },
    { forms: ['liquidity'], definition: 'How easily a token can be bought or sold without moving its price. Low liquidity can make it hard to sell.' },
    { forms: ['rug pulls', 'rug pull'], definition: 'A scam where the creators take the money out of a project and leave buyers holding worthless tokens.' },
    { forms: ['honeypots', 'honeypot'], definition: 'A token that can be bought but not sold, so buyers are trapped.' },
    { forms: ['pump and dump'], definition: 'A scheme that drives a price up with hype, then sells at the top, leaving later buyers with losses.' },
    { forms: ['smart contracts', 'smart contract'], definition: 'A program stored on the blockchain that runs by itself when its conditions are met.' },
    { forms: ['blockchain'], definition: 'A shared public record of transactions that no single person controls and that cannot easily be changed.' },
    { forms: ['wallets', 'wallet'], definition: 'An account on the blockchain that holds tokens. It is identified by a long code called an address.' },
    { forms: ['transaction history'], definition: 'The list of past transfers in and out of an address, with dates and amounts.' },
    { forms: ['on-chain'], definition: 'Recorded on the blockchain itself, where anyone can check it.' },
    { forms: ['minting', 'mint'], definition: 'Creating new tokens. If the owner can mint without limit, they can dilute everyone else.' },
    { forms: ['verified source code'], definition: 'The contract\'s code has been published and matched to what runs on the blockchain, so people can read what it does.' },
    { forms: ['DEX', 'decentralized exchange'], definition: 'A trading site that runs on smart contracts instead of a company, such as Uniswap.' },
    { forms: ['ERC-20'], definition: 'The standard format most tokens on Ethereum follow, so wallets and exchanges can handle them.' },
    { forms: ['wash trading'], definition: 'Trading with yourself to fake activity and make a token look popular.' },
    { forms: ['phishing'], definition: 'Tricking people into giving up passwords, keys or approvals, often with a fake site or message.' },
  ];

  const GLOSSARY_LOOKUP = {};
  GLOSSARY.forEach(entry => {
    entry.forms.forEach(form => { GLOSSARY_LOOKUP[form.toLowerCase()] = entry; });
  });
  const escapeRegex = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Longest spellings first, so "liquidity pool" wins over "liquidity".
  const GLOSSARY_REGEX = new RegExp(
    '(?<![\\w-])(' +
    Object.keys(GLOSSARY_LOOKUP)
      .sort((a, b) => b.length - a.length)
      .map(escapeRegex)
      .join('|') +
    ')(?![\\w-])',
    'gi'
  );

  // Fills `el` with `text`, turning the first use of each defined term into a bold, hoverable term. Built from text nodes, never innerHTML, so a reply is still shown literally. `seen` is a Map of the terms already marked in this message (glossary entry -> the wording used).
  function renderWithTerms(el, text, seen) {
    el.textContent = '';
    let last = 0;
    GLOSSARY_REGEX.lastIndex = 0;
    let match;
    while ((match = GLOSSARY_REGEX.exec(text)) !== null) {
      const entry = GLOSSARY_LOOKUP[match[1].toLowerCase()];
      if (seen.has(entry)) continue;
      seen.set(entry, match[1]);
      if (match.index > last) {
        el.appendChild(document.createTextNode(text.slice(last, match.index)));
      }
      const term = document.createElement('span');
      term.className = 'term';
      term.tabIndex = 0;
      term.appendChild(document.createTextNode(match[1]));
      const tip = document.createElement('span');
      tip.className = 'term-tooltip';
      tip.setAttribute('role', 'tooltip');
      tip.textContent = entry.definition;
      term.appendChild(tip);
      el.appendChild(term);
      last = match.index + match[1].length;
    }
    if (last < text.length) {
      el.appendChild(document.createTextNode(text.slice(last)));
    }
  }

  // ---------- Citation pills ----------
  // One pill per data source the verdict drew on, then a separate pill for the glossary when the reply defined any terms. Called last, so the pills sit at the end of the message.
  function citationRow(citations, usedTerms) {
    const row = document.createElement('div');
    row.className = 'citation-row';
    citations.forEach(c => {
      if (!c || !c.name) return;
      const pill = document.createElement(c.url ? 'a' : 'span');
      pill.className = 'citation-pill';
      pill.textContent = c.name;
      if (c.url) {
        pill.href = c.url;
        pill.target = '_blank';
        pill.rel = 'noopener noreferrer';
        pill.title = 'Open ' + c.name + ' in a new tab';
        const icon = document.createElement('span');
        icon.className = 'citation-icon';
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = '↗';
        pill.appendChild(icon);
      }
      row.appendChild(pill);
    });
    if (usedTerms.size > 0) {
      const pill = document.createElement('button');
      pill.type = 'button';
      pill.className = 'citation-pill citation-pill-glossary';
      pill.setAttribute('aria-expanded', 'false');
      pill.title = 'Show the definitions used in this reply';
      pill.textContent = 'Definitions: ChainCheck glossary';
      const arrow = document.createElement('span');
      arrow.className = 'citation-icon';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = '\u25BE';
      pill.appendChild(arrow);

      // Clicking the pill opens the list of every term defined in this reply.
      const panel = document.createElement('dl');
      panel.className = 'glossary-panel';
      panel.hidden = true;
      usedTerms.forEach((wording, entry) => {
        const dt = document.createElement('dt');
        dt.textContent = wording;
        const dd = document.createElement('dd');
        dd.textContent = entry.definition;
        panel.append(dt, dd);
      });
      pill.addEventListener('click', () => {
        const open = panel.hidden;
        panel.hidden = !open;
        pill.setAttribute('aria-expanded', String(open));
        arrow.textContent = open ? '\u25B4' : '\u25BE';
        thread.scrollTop = thread.scrollHeight;
      });
      row.appendChild(pill);
      row.appendChild(panel);
    }
    return row.childElementCount ? row : null;
  }

  function evidenceList(evidence, seen) {
    const box = document.createElement('div');
    box.className = 'evidence-box';
    const heading = document.createElement('p');
    heading.className = 'evidence-box-label';
    heading.textContent = 'Evidence';
    box.appendChild(heading);
    const ul = document.createElement('ul');
    ul.className = 'evidence-list';
    // Strongest evidence first - the backend returns it in no particular order.
    [...evidence].sort((a, b) => b.weight - a.weight).forEach(item => {
      const li = document.createElement('li');
      const desc = document.createElement('span');
      renderWithTerms(desc, item.description, seen);
      li.appendChild(desc);
      const weight = document.createElement('span');
      weight.className = 'evidence-weight';
      weight.textContent = item.weight.toFixed(2);
      li.appendChild(weight);
      ul.appendChild(li);
    });
    box.appendChild(ul);
    return box;
  }

  // ---------- Raw evidence (professional users only) ----------
  // The identifiers the data sources returned, kept apart from the AI's explanation. Shown only when the user's expertise is professional (auditors, investigators); everyone else gets the plain reply.
  const RAW_TYPE_LABELS = [
    ['transaction_hash', 'Transaction hashes'],
    ['contract_address', 'Contract addresses'],
    ['wallet_address', 'Wallet addresses'],
    ['account_address', 'Account addresses'],
    ['address', 'Other addresses'],
    ['block_hash', 'Block hashes'],
  ];
  const RAW_PREVIEW_COUNT = 5;
  // Professional users: a professional expertise tier, or a professional use case (investigators, police, auditors, compliance screeners). The assistant sets a plain-language user's tier to beginner even when their use case is professional, so the use case counts on its own.
  const PROFESSIONAL_USE_CASES = ['investigative_legal', 'compliance_risk'];
  function showsRawEvidence(data) {
    return data.expertise_tier === 'professional' || PROFESSIONAL_USE_CASES.includes(data.use_case);
  }
  const HEX_ADDRESS = /^0x[0-9a-fA-F]{40}$/;
  const HEX_HASH = /^0x[0-9a-fA-F]{64}$/;

  // Explorer page for a value, only where one is known: Etherscan covers Ethereum alone, and it has no page we can build from a block hash.
  function explorerUrl(type, value, chain) {
    if (chain !== 'ethereum') return null;
    if (type === 'transaction_hash' && HEX_HASH.test(value)) return 'https://etherscan.io/tx/' + value;
    if (type !== 'block_hash' && type !== 'transaction_hash' && HEX_ADDRESS.test(value)) return 'https://etherscan.io/address/' + value;
    return null;
  }

  function rawItemRow(item, chain) {
    const row = document.createElement('li');
    row.className = 'raw-item';
    const url = explorerUrl(item.type, item.value, chain);
    const value = document.createElement(url ? 'a' : 'span');
    value.className = 'raw-value';
    value.textContent = item.value;
    if (url) {
      value.href = url;
      value.target = '_blank';
      value.rel = 'noopener noreferrer';
      value.title = 'Open on Etherscan in a new tab';
    }
    const meta = document.createElement('span');
    meta.className = 'raw-meta';
    meta.textContent = item.source + (item.field ? ' \u00B7 ' + item.field : '');
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'raw-copy';
    copy.textContent = 'Copy';
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(item.value);
        copy.textContent = 'Copied';
      } catch (err) {
        copy.textContent = 'Not copied';
      }
      setTimeout(() => { copy.textContent = 'Copy'; }, 1500);
    });
    row.append(value, meta, copy);
    return row;
  }

  function rawEvidenceBlock(raw) {
    if (!raw || !Array.isArray(raw.items) || raw.items.length === 0) return null;
    const block = document.createElement('div');
    block.className = 'raw-block';
    const heading = document.createElement('p');
    heading.className = 'raw-block-label';
    heading.textContent = 'Raw evidence';
    block.appendChild(heading);
    const note = document.createElement('p');
    note.className = 'raw-block-note';
    const sources = Array.isArray(raw.sources) && raw.sources.length ? raw.sources.join(', ') : 'the data sources';
    note.textContent = 'Identifiers exactly as returned by ' + sources + '. Not interpreted by the AI.';
    block.appendChild(note);

    RAW_TYPE_LABELS.forEach(([type, title]) => {
      const items = raw.items.filter(i => i && i.type === type && typeof i.value === 'string');
      if (!items.length) return;
      const group = document.createElement('div');
      group.className = 'raw-group';
      const groupTitle = document.createElement('p');
      groupTitle.className = 'raw-group-title';
      groupTitle.textContent = title + ' (' + items.length + ')';
      group.appendChild(groupTitle);
      const list = document.createElement('ul');
      list.className = 'raw-list';
      items.slice(0, RAW_PREVIEW_COUNT).forEach(i => list.appendChild(rawItemRow(i, raw.chain)));
      group.appendChild(list);
      if (items.length > RAW_PREVIEW_COUNT) {
        const more = document.createElement('details');
        more.className = 'raw-more';
        const summary = document.createElement('summary');
        summary.textContent = 'Show ' + (items.length - RAW_PREVIEW_COUNT) + ' more';
        const moreList = document.createElement('ul');
        moreList.className = 'raw-list';
        items.slice(RAW_PREVIEW_COUNT).forEach(i => moreList.appendChild(rawItemRow(i, raw.chain)));
        more.append(summary, moreList);
        group.appendChild(more);
      }
      block.appendChild(group);
    });
    return block;
  }

  function detailBlock(rows) {
    const block = document.createElement('div');
    block.className = 'evidence-block';
    const label = document.createElement('p');
    label.className = 'evidence-block-label';
    label.textContent = 'Detection details';
    block.appendChild(label);
    rows.forEach(([name, value]) => {
      const row = document.createElement('div');
      row.className = 'evidence-row';
      const rowLabel = document.createElement('span');
      rowLabel.className = 'evidence-row-label';
      rowLabel.textContent = name;
      const rowValue = document.createElement('span');
      rowValue.className = 'evidence-row-value';
      rowValue.textContent = value;
      row.append(rowLabel, rowValue);
      block.appendChild(row);
    });
    return block;
  }


  function statusTag(label) {
    const tag = STATUS_TAGS[label];
    if (!tag) return null;
    const span = document.createElement('span');
    span.className = 'status-tag ' + tag.className;
    span.textContent = tag.text;
    return span;
  }

  function interpretationNote(text) {
    const p = document.createElement('p');
    p.className = 'interpretation-note';
    p.textContent = text;
    return p;
  }

  const INPUT_KINDS = { tx_hash: 'Transaction', token_name: 'Token' };

  function addressCard(result, number, total, usedTerms) {
    const card = document.createElement('section');
    card.className = 'address-card';
    card.dataset.label = result.label || 'none';
    const kind = INPUT_KINDS[result.input_type] || 'Address';
    card.setAttribute('aria-label', `${kind} ${number} of ${total}`);

    const head = document.createElement('div');
    head.className = 'address-card-head';
    const title = document.createElement('span');
    title.className = 'address-card-title';
    title.textContent = `${kind} ${number} of ${total}`;
    head.appendChild(title);
    const tag = statusTag(result.label);
    if (tag) head.appendChild(tag);
    card.appendChild(head);

    const value = document.createElement('code');
    value.className = 'address-card-value';
    value.textContent = result.input;
    card.appendChild(value);
    if (result.address && result.address.toLowerCase() !== result.input.toLowerCase()) {
      const resolved = document.createElement('p');
      resolved.className = 'address-card-resolved';
      resolved.textContent = 'Checked address: ' + result.address;
      card.appendChild(resolved);
    }

    const text = document.createElement('p');
    text.className = 'msg-ai-text';
    renderWithTerms(text, result.reply, usedTerms);
    card.appendChild(text);

    appendVerdictDetails(card, result, usedTerms);
    // Each address names its own data sources. The glossary pill goes once at the end of the whole message.
    const citations = tag && Array.isArray(result.citations) ? result.citations : [];
    const pills = citationRow(citations, new Map());
    if (pills) card.appendChild(pills);
    return card;
  }

  function appendMultiReply(data, usedTerms) {
    const total = data.results.length;
    const div = appendAiMsg(`I checked ${total} addresses - here's what I found for each:`);
    data.results.forEach((result, i) => {
      div.appendChild(addressCard(result, i + 1, total, usedTerms));
    });
    const skipped = data.skipped_inputs || [];
    if (skipped.length) {
      div.appendChild(interpretationNote(
        `I only check ${total} at a time, so I left out ${skipped.join(', ')} - ` +
        `send ${skipped.length === 1 ? 'it' : 'those'} in another message and I'll take a look.`
      ));
    }
    return div;
  }

  function appendVerdictDetails(el, data, usedTerms) {
    const hasEvidence = Array.isArray(data.evidence) && data.evidence.length > 0;

    if (hasEvidence) {
      el.appendChild(evidenceList(data.evidence, usedTerms));
    } else if (data.label === 'insufficient_evidence') {
      el.appendChild(interpretationNote('Not enough on-chain data was found for this address to reach a scam or not-scam verdict.'));
    } else if (STATUS_TAGS[data.label]) {
      el.appendChild(interpretationNote('No evidence items were itemised for this verdict.'));
    }

    const rows = [];
    if (typeof data.confidence === 'number') {
      const isZeroConfidenceNoEvidence = data.confidence === 0 && !hasEvidence;
      rows.push([
        'Confidence',
        isZeroConfidenceNoEvidence ? 'Not available' : Math.round(data.confidence * 100) + '%',
      ]);
    }
    if (data.risk_type) rows.push(['Risk type', data.risk_type]);
    if (data.source) {
      let source = SOURCE_WORDS[data.source] || data.source;
      if (data.source === 'detector' && data.detector_name) {
        source += ' (' + data.detector_name + ')';
      }
      rows.push(['Source', source]);
    }
    if (rows.length) el.appendChild(detailBlock(rows));

    if (showsRawEvidence(data)) {
      const rawBlock = rawEvidenceBlock(data.raw_data);
      if (rawBlock) div.appendChild(rawBlock);
    }

    // Shown on every reply that relied on fetched data, so a check that couldn't run is never mistaken for a clean one.
    if (Array.isArray(data.missing_fields) && data.missing_fields.length) {
      el.appendChild(interpretationNote('Not checked (data unavailable): ' +
        data.missing_fields.map(f => MISSING_FIELD_WORDS[f] || f).join(', ')));
    }
  }

  function appendReply(data) {
    // Terms already marked in this message, so each is bolded once.
    const usedTerms = new Map();
    let div;
    let citations = [];
    if (Array.isArray(data.results) && data.results.length > 0) {
      // The cards carry their own source pills, so only the glossary pill is left for the end.
      div = appendMultiReply(data, usedTerms);
    } else {
      div = appendAiMsg(data.reply);
      const textEl = div.querySelector('.msg-ai-text');
      renderWithTerms(textEl, data.reply, usedTerms);
      const tag = statusTag(data.label);
      if (tag) div.insertBefore(tag, textEl);
      appendVerdictDetails(div, data, usedTerms);
      citations = tag && Array.isArray(data.citations) ? data.citations : [];
    }

    // Pills close the message: a verdict names its data sources, and any defined term gets the glossary pill beside them.
    const pills = citationRow(citations, usedTerms);
    if (pills) div.appendChild(pills);

    if (Array.isArray(data.quick_replies) && data.quick_replies.length > 0) {
      const quickReplies = document.createElement('div');
      quickReplies.className = 'quick-replies';

      data.quick_replies.forEach(option => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'quick-reply-chip';
        button.textContent = option;

        button.addEventListener('click', () => {
          quickReplies.remove();
          sendMessage(option);
        });

        quickReplies.appendChild(button);
      });

      div.appendChild(quickReplies);
    }

    thread.scrollTop = thread.scrollHeight;
  }

  function appendPendingMsg() {
    return appendAiMsg('Thinking…', 'msg-pending');
  }

  // While the answer is being worked out, ask the server what it is doing and show that in the pending bubble. Returns a function that stops the polling.
  function startStatusPolling(pending) {
    const label = pending.querySelector('.msg-ai-text');
    let stopped = false;
    let timer = null;

    async function poll() {
      if (stopped) return;
      try {
        const res = await fetch(CHAT_STATUS_URL);
        if (res.ok && !stopped) {
          const data = await res.json();
          if (data.status && label) label.textContent = data.status + '…';
        }
      } catch (err) {
        // Status is cosmetic. The bubble keeps its last text.
      }
      if (!stopped) timer = setTimeout(poll, 400);
    }

    timer = setTimeout(poll, 300);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }

  function appendErrorMsg(title, text) {
    appendAiMsg(text, 'msg-error', title);
  }

  // ---------- Send ----------
  let sending = false;

  async function sendMessage(messageOverride = null) {
    const text = (messageOverride ?? chatInput.value).trim();
    if (!text || sending) return;

    if (promptHint) promptHint.style.display = 'none';

    appendUserMsg(text);
    chatInput.value = '';
    chatInput.disabled = true;
    sending = true;
    const pending = appendPendingMsg();
    let stopStatus = () => {};

    try {
      await sessionReady;
      stopStatus = startStatusPolling(pending);
      const res = await fetch(CHAT_API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      stopStatus();
      pending.remove();

      if (!res.ok) {
        appendErrorMsg(
          'Assistant error',
          `The assistant failed to answer (HTTP ${res.status}). ` +
          'Check the server log - the LLM backend (Ollama) may not be running.'
        );
        return;
      }

      const data = await res.json();
      appendReply(data);
    } catch (err) {
      stopStatus();
      pending.remove();
      appendErrorMsg(
        'Connection issue',
        "Couldn't reach the assistant backend. Start it with " +
        "'uvicorn server:app --port 8000', then try again."
      );
    } finally {
      sending = false;
      chatInput.disabled = false;
      chatInput.focus();
    }
  }

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  chatInput.addEventListener('paste', (e) => {
    const pasted = e.clipboardData && e.clipboardData.getData('text');
    if (!pasted || !/[\r\n]/.test(pasted)) return;
    e.preventDefault();
    const joined = pasted.split(/[\r\n]+/).map(line => line.trim()).filter(Boolean).join(', ');
    chatInput.setRangeText(joined, chatInput.selectionStart, chatInput.selectionEnd, 'end');
  });


  function showTermTip(e) {
    const term = e.target.closest('.term');
    if (!term) return;
    const tooltip = term.querySelector('.term-tooltip');
    if (!tooltip) return;
    const rect = term.getBoundingClientRect();
    const tooltipWidth = 220;
    let left = rect.left;
    if (left + tooltipWidth > window.innerWidth - 16) {
      left = window.innerWidth - tooltipWidth - 16;
    }
    tooltip.style.left = left + 'px';
    tooltip.classList.add('visible');
    const tooltipRect = tooltip.getBoundingClientRect();
    if (rect.top - tooltipRect.height - 12 < 8) {
      tooltip.style.top = (rect.bottom + 8) + 'px';
    } else {
      tooltip.style.top = (rect.top - tooltipRect.height - 8) + 'px';
    }
  }
  function hideTermTip(e) {
    const term = e.target.closest('.term');
    if (!term) return;
    const tooltip = term.querySelector('.term-tooltip');
    if (tooltip) tooltip.classList.remove('visible');
  }
  document.addEventListener('mouseover', showTermTip);
  document.addEventListener('mouseout', hideTermTip);
  // Keyboard users get the same tip when a term takes focus.
  document.addEventListener('focusin', showTermTip);
  document.addEventListener('focusout', hideTermTip);
});
