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
    // Terms already marked in this message, so each is bolded once.
    const usedTerms = new Map();
    renderWithTerms(textEl, data.reply, usedTerms);

    const tag = STATUS_TAGS[data.label];
    if (tag) {
      const span = document.createElement('span');
      span.className = 'status-tag ' + tag.className;
      span.textContent = tag.text;
      div.insertBefore(span, textEl);
    }

    const hasEvidence = Array.isArray(data.evidence) && data.evidence.length > 0;

    if (hasEvidence) {
      div.appendChild(evidenceList(data.evidence, usedTerms));
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
      rows.push(['Source', SOURCE_WORDS[data.source] || data.source]);
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

    // Pills close the message: a verdict names its data sources, and any defined term gets the glossary pill beside them.
    const citations = tag && Array.isArray(data.citations) ? data.citations : [];
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
