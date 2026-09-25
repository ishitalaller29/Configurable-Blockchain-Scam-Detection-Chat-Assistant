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

  function cloneTemplate(template) {
    return template.content.firstElementChild.cloneNode(true);
  }

  const API_BASE = window.location.protocol === 'file:'
    ? 'http://localhost:8000'
    : '';
  const CHAT_API_URL = API_BASE + '/chat';
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

  addSourceBtn.addEventListener('click', () => {
    const name = (window.prompt('Name of the source to add') || '').trim();
    if (!name) return;
    const item = document.createElement('div');
    item.className = 'source-item';
    item.tabIndex = 0;
    item.dataset.source = name;
    item.textContent = name;
    const dot = document.createElement('span');
    dot.className = 'source-dot';
    item.appendChild(dot);
    addSourceBtn.parentNode.insertBefore(item, addSourceBtn);
  });

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
    insufficient_evidence: { text: 'Suspicious', className: 'status-insufficient' },
  };

  // Mirrors conversation.SOURCE_WORDS so both front ends name the source identically. Unknown values fall through and render as-is.
  const SOURCE_WORDS = {
    scam_checker: 'Scam Checker (no detector configured)',
    detector: 'Configured detector',
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

    if (Array.isArray(data.evidence) && data.evidence.length) {
      div.appendChild(evidenceList(data.evidence));
    } else if (tag) {
      const note = document.createElement('p');
      note.className = 'interpretation-note';
      note.textContent = 'No evidence items were itemised for this verdict.';
      div.appendChild(note);
    }

    const rows = [];
    if (typeof data.confidence === 'number') {
      rows.push(['Confidence', Math.round(data.confidence * 100) + '%']);
    }
    if (data.risk_type) rows.push(['Risk type', data.risk_type]);
    if (data.source) {
      rows.push(['Source', SOURCE_WORDS[data.source] || data.source]);
    }
    if (rows.length) div.appendChild(detailBlock(rows));

    thread.scrollTop = thread.scrollHeight;
  }

  function appendPendingMsg() {
    return appendAiMsg('Thinking…', 'msg-pending');
  }

  function appendErrorMsg(title, text) {
    appendAiMsg(text, 'msg-error', title);
  }

  // ---------- Send ----------
  let sending = false;

  async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || sending) return;

    if (promptHint) promptHint.style.display = 'none';

    appendUserMsg(text);
    chatInput.value = '';
    chatInput.disabled = true;
    sending = true;
    const pending = appendPendingMsg();

    try {
      await sessionReady;
      const res = await fetch(CHAT_API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
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
