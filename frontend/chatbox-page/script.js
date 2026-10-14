// Chatbox page interactivity: Web front end for the same pipeline cli.py drives: each message is sent to server.py (POST /chat), which calls ChatSession.handle_message() and returns the reply the CLI would have printed after "Bot:". The reply is shown as-is.

document.addEventListener('DOMContentLoaded', () => {
  const backToStart = document.getElementById('backToStart');
  const chatInput = document.getElementById('chatInput');
  const thread = document.getElementById('thread');
  const promptHint = document.getElementById('promptHint');
  const plusIcon = document.getElementById('plusIcon');
  const adminToggle = document.getElementById('adminToggle');
  const sidebar = document.getElementById('sidebar');
  const aiMsgTemplate = document.getElementById('aiMsgTemplate');
  const fileChipTemplate = document.getElementById('fileChipTemplate');
  const addSourceBtn = document.getElementById('addSourceBtn');
  const llmConfigRows = document.getElementById('llmConfigRows');
  const saveLlmConfigBtn = document.getElementById('saveLlmConfigBtn');
  const llmConfigStatus = document.getElementById('llmConfigStatus');
  const sourceFileInput = document.getElementById('sourceFileInput');
  const downloadTemplateBtn = document.getElementById('downloadTemplateBtn');
  const detectorSelect = document.getElementById('detectorSelect');
  const detectorStatus = document.getElementById('detectorStatus');

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

  adminToggle.addEventListener('change', () => {
    sidebar.style.display = adminToggle.checked ? 'block' : 'none';
  });

  backToStart.addEventListener('click', () => {
    window.location.href = '../starting-page/index.html';
  });

  plusIcon.addEventListener('click', () => {
    const chip = cloneTemplate(fileChipTemplate);
    const inputRow = document.querySelector('.input-row');
    inputRow.parentNode.insertBefore(chip, inputRow);
  });

  // ---------- Connected sources (admin sidebar) ----------
  sidebar.addEventListener('click', (e) => {
    const item = e.target.closest('.source-item');
    if (!item) return;
    sidebar.querySelectorAll('.source-item').forEach(i => i.classList.remove('active'));
    item.classList.add('active');
  });

  // "Add source" now ingests an uploaded detector/config file (built from the API
  // Wrapper Template) rather than just a typed-in name. Clicking the button opens
  // the hidden file input; the chosen file's name is shown as the new source item.
  // No actual upload to a backend endpoint yet - wiring that up, and validating the
  // file against the wrapper template's schema, is backend work for a later sprint.
  addSourceBtn.addEventListener('click', () => {
    sourceFileInput.click();
  });

  sourceFileInput.addEventListener('change', () => {
    const file = sourceFileInput.files && sourceFileInput.files[0];
    if (!file) return;

    const item = document.createElement('div');
    item.className = 'source-item';
    item.tabIndex = 0;
    item.dataset.source = file.name;
    item.textContent = file.name;
    const dot = document.createElement('span');
    dot.className = 'source-dot';
    item.appendChild(dot);
    addSourceBtn.parentNode.insertBefore(item, addSourceBtn);

    // Reset so selecting the same file again still fires 'change'.
    sourceFileInput.value = '';
  });

  // Stub only: real deployment of the API Wrapper Template repo as a Docker image
  // happens in Sprint 3. This just marks where that download call will go, so the
  // button is wired up and visible now without the actual asset existing yet.
  downloadTemplateBtn.addEventListener('click', () => {
    // TODO (Sprint 3): replace with a real download of the API Wrapper Template's
    // Docker image once that deployment pipeline exists. For now this is a no-op
    // placeholder so the button renders and is clickable without erroring.
    console.log('Download API wrapper template - not yet implemented (Sprint 3).');
  });

  // ---------- Admin password gate ----------
  // Hardcoded shared passphrase per the client's own suggestion (confirmed
  // in the technical advisor meeting as the simplest acceptable approach -
  // real auth/accounts are explicitly out of scope for this project).
  const ADMIN_PASSPHRASE = 'admin';

  adminToggle.addEventListener('change', () => {
    if (adminToggle.checked) {
      const attempt = window.prompt('Enter the admin passphrase');
      if (attempt !== ADMIN_PASSPHRASE) {
        adminToggle.checked = false;
        sidebar.style.display = 'none';
        if (attempt !== null) {
          window.alert('Incorrect passphrase.');
        }
        return;
      }
      sidebar.style.display = 'block';
      loadLlmConfig();
      loadDetectorConfig();
    } else {
      sidebar.style.display = 'none';
    }
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
        thread.innerHTML = '';
        thread.appendChild(promptHint);
        promptHint.style.display = '';
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

  function evidenceList(evidence) {
    const ul = document.createElement('ul');
    ul.className = 'evidence-list';
    // Strongest evidence first - the backend returns it in no particular order.
    [...evidence].sort((a, b) => b.weight - a.weight).forEach(item => {
      const li = document.createElement('li');
      li.textContent = item.description;
      const weight = document.createElement('span');
      weight.className = 'evidence-weight';
      weight.textContent = item.weight.toFixed(2);
      li.appendChild(weight);
      ul.appendChild(li);
    });
    return ul;
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


  function appendReply(data) {
    const div = appendAiMsg(data.reply);
    const textEl = div.querySelector('.msg-ai-text');

    const tag = STATUS_TAGS[data.label];
    if (tag) {
      const span = document.createElement('span');
      span.className = 'status-tag ' + tag.className;
      span.textContent = tag.text;
      div.insertBefore(span, textEl);
    }

    const hasEvidence = Array.isArray(data.evidence) && data.evidence.length > 0;

    if (hasEvidence) {
      div.appendChild(evidenceList(data.evidence));
    } else if (data.label === 'insufficient_evidence') {
      const note = document.createElement('p');
      note.className = 'interpretation-note';
      note.textContent = 'Not enough on-chain data was found for this address to reach a scam or not-scam verdict.';
      div.appendChild(note);
    } else if (tag) {
      const note = document.createElement('p');
      note.className = 'interpretation-note';
      note.textContent = 'No evidence items were itemised for this verdict.';
      div.appendChild(note);
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
    if (rows.length) div.appendChild(detailBlock(rows));

    // Shown on every reply that relied on fetched data, so a check that couldn't run is never mistaken for a clean one.
    if (Array.isArray(data.missing_fields) && data.missing_fields.length) {
      const note = document.createElement('p');
      note.className = 'interpretation-note';
      note.textContent = 'Not checked (data unavailable): ' +
        data.missing_fields.map(f => MISSING_FIELD_WORDS[f] || f).join(', ');
      div.appendChild(note);
    }

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


  document.addEventListener('mouseover', (e) => {
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
  });
  document.addEventListener('mouseout', (e) => {
    const term = e.target.closest('.term');
    if (!term) return;
    const tooltip = term.querySelector('.term-tooltip');
    if (tooltip) tooltip.classList.remove('visible');
  });
});
