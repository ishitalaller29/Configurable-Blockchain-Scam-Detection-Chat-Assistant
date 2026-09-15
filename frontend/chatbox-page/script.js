// Chatbox page interactivity.
// Implements the three expertise tiers (beginner, intermediate, professional),
// the leading question, the fallback prompt for ambiguous answers, and the
// benign/suspicious/scam verdict scale, per the validated wireframe and the
// BA's four flag resolutions.
 
document.addEventListener('DOMContentLoaded', () => {
  const backToStart = document.getElementById('backToStart');
  const chatInput = document.getElementById('chatInput');
  const thread = document.getElementById('thread');
  const promptHint = document.getElementById('promptHint');
  const plusIcon = document.getElementById('plusIcon');
  const adminToggle = document.getElementById('adminToggle');
  const sidebar = document.getElementById('sidebar');
 
  let stage = 'awaiting_leading_answer'; // awaiting_leading_answer -> awaiting_detail -> resolved
  let tier = null; // 'beginner' | 'intermediate' | 'professional'
 
  adminToggle.addEventListener('change', () => {
    sidebar.style.display = adminToggle.checked ? 'block' : 'none';
  });
 
  backToStart.addEventListener('click', () => {
    window.location.href = '../starting-page/index.html';
  });
 
  plusIcon.addEventListener('click', () => {
    const chip = document.createElement('div');
    chip.className = 'file-chip';
    chip.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="#33404f" stroke-width="1.6"/>
        <path d="M14 2v6h6" stroke="#33404f" stroke-width="1.6"/>
      </svg>
      contract_snapshot.pdf
    `;
    const inputRow = document.querySelector('.input-row');
    inputRow.parentNode.insertBefore(chip, inputRow);
  });
 
  document.querySelectorAll('.source-item').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.source-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
    });
  });
 
  function appendUserMsg(text) {
    const div = document.createElement('div');
    div.className = 'msg-user';
    div.textContent = text;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
  }
 
  function appendAiMsg(html) {
    const div = document.createElement('div');
    div.className = 'msg-ai';
    div.innerHTML = html;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
    attachQuickReplies(div); // fixed: every AI message gets its buttons wired automatically
    return div;
  }
 
  function attachQuickReplies(container) {
    container.querySelectorAll('.quick-reply-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.tier) tier = btn.dataset.tier;
        chatInput.value = btn.dataset.fill || btn.textContent;
        sendMessage();
      });
    });
  }
 
  // ---------- Tier classification ----------
  function classifyTier(text) {
    const t = text.toLowerCase();
    const professionalWords = ['contract', 'abi', 'liquidity pool', 'mint function', 'bytecode', 'reentrancy'];
    const intermediateWords = ['wallet', 'token', 'buy', 'sell', 'exchange', 'gas fee'];
    const beginnerWords = ['what does that mean', "don't understand", 'is this safe', 'someone told me'];
 
    if (professionalWords.some(w => t.includes(w))) return 'professional';
    if (intermediateWords.some(w => t.includes(w))) return 'intermediate';
    if (beginnerWords.some(w => t.includes(w))) return 'beginner';
    return null; // ambiguous, needs fallback buttons
  }
 
  // ---------- Stage 1: leading question ----------
  function askLeadingQuestion() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <p style="margin:0;">Just so I can explain things the right way, have you used crypto much before, and what brings you here today?</p>
    `);
  }
 
  // ---------- Fallback: button-based prompt for ambiguous answers ----------
  function askFallbackButtons() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <p style="margin:0 0 10px;">No problem, pick whichever fits best:</p>
      <div class="quick-replies">
        <button class="quick-reply-chip" data-tier="beginner" data-fill="Just checking before I buy or invest">Just checking before I buy or invest</button>
        <button class="quick-reply-chip" data-tier="professional" data-fill="Investigating this for work (police, legal, compliance)">Investigating this for work (police, legal, compliance)</button>
        <button class="quick-reply-chip" data-tier="professional" data-fill="I'm a developer/researcher looking into this myself">I'm a developer/researcher looking into this myself</button>
        <button class="quick-reply-chip" data-tier="beginner" data-fill="Not sure yet, just exploring">Not sure yet, just exploring</button>
      </div>
    `);
  }
 
  // ---------- Beginner tier ----------
  function beginnerResponse() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <span class="status-tag status-insufficient">Insufficient evidence</span>
      <p style="margin:0 0 10px;">
        No worries, I'll keep this simple. This
        <span class="term">address<span class="term-tooltip">Think of this like an account number. It's how crypto is sent and received.</span></span>
        is very new, so there isn't much
        <span class="term">history<span class="term-tooltip">This just means the list of past transactions this address has been part of.</span></span>
        for me to check yet.
      </p>
      <p style="margin:0;">Can you tell me roughly how much money is involved, or where you heard about this address? That will help me give you a clearer answer.</p>
      <div class="quick-replies">
        <button class="quick-reply-chip" data-fill="Someone messaged me about it and I want to buy in">Someone messaged me about it and I want to buy in</button>
        <button class="quick-reply-chip" data-fill="I'm not sure, I just have the address">I'm not sure, I just have the address</button>
      </div>
    `);
  }
 
  function beginnerResolved() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <span class="status-tag status-scam">Scam</span>
      <p style="margin:0 0 10px;">
        Based on what you've told me, this has some warning signs. Someone reaching out first and encouraging you to buy in quickly is a common pattern in scams.
      </p>
      <p style="margin:0 0 6px; font-weight:bold;">In plain terms, here's why:</p>
      <ul class="evidence-list">
        <li>The people running this
          <span class="term">token<span class="term-tooltip">A token is a type of crypto asset built on top of a blockchain, often created for one specific project.</span></span>
          pulled out most of their funds very recently, which is a common warning sign.</li>
        <li>Very few other people hold this token, which can mean it's not established or trusted yet.</li>
      </ul>
      <p style="margin:10px 0 0;">My suggestion: it's safer not to send money here until you can verify it with someone you trust.</p>
      <a class="citation-pill" href="#" onclick="return false;">Source: cryptoscamdb &#8599;</a>
    `);
  }
 
  // ---------- Intermediate tier: findings-first ordering ----------
  function intermediateResponse() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <span class="status-tag status-suspicious">Suspicious</span>
      <p style="margin:0 0 10px;">This wallet is newly created with limited transaction history, but a couple of early signals are worth flagging before I go further.</p>
      <div class="evidence-block">
        <p class="evidence-block-label">Preliminary findings</p>
        <div class="evidence-row"><span class="evidence-row-label">Wallet age</span><span class="evidence-row-value">2 days</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Liquidity status</span><span class="evidence-row-value">Added, unverified</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Contract source</span><span class="evidence-row-value">Unverified</span></div>
      </div>
      <p style="margin:12px 0 0;">One thing that would change my read: is this for a trade you're considering, or due diligence on a project?</p>
      <div class="quick-replies">
        <button class="quick-reply-chip" data-fill="Due diligence, liquidity was added about a week ago">Due diligence, liquidity was added about a week ago</button>
        <button class="quick-reply-chip" data-fill="Screening it for a compliance review">Screening it for a compliance review</button>
      </div>
    `);
  }
 
  function intermediateResolved() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <span class="status-tag status-scam">Scam</span>
      <p style="margin:0 0 10px;">Based on the added detail, this fits a
        <span class="term">rug pull<span class="term-tooltip">A rug pull is when a project's creators suddenly withdraw funds and disappear, leaving investors with worthless tokens.</span></span>
        pattern.</p>
      <p style="margin:0 0 6px; font-weight:bold;">AI interpretation:</p>
      <ul class="evidence-list">
        <li>Roughly 90 percent of liquidity was removed shortly after being added.</li>
        <li>Top holder wallet controls a large share of supply, concentrated ownership is a common risk marker.</li>
        <li>No verified contract source, so the code behind it hasn't been independently checked.</li>
      </ul>
      <div class="evidence-block">
        <p class="evidence-block-label">Raw evidence</p>
        <div class="evidence-row"><span class="evidence-row-label">Contract address</span><span class="evidence-row-value">0x7a3f...9e21</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Liquidity removal tx</span><span class="evidence-row-value">0x51c8...4b0d</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Removal timestamp</span><span class="evidence-row-value">2026-09-08 14:32 UTC</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Top holder share</span><span class="evidence-row-value">41.2%</span></div>
      </div>
      <p class="interpretation-note">The section above is directly observed on-chain data. The bullets above it are the AI's interpretation of that data, not a verified fact on their own.</p>
      <a class="citation-pill" href="#" onclick="return false;">Source: DexScreener &#8599;</a>
      <a class="citation-pill" href="#" onclick="return false;">Source: Etherscan &#8599;</a>
    `);
  }
 
  // ---------- Professional tier: findings-first ordering, denser evidence ----------
  function professionalResponse() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <span class="status-tag status-suspicious">Suspicious</span>
      <p style="margin:0 0 10px;">Limited on-chain history available, but a few structural signals stand out already.</p>
      <div class="evidence-block">
        <p class="evidence-block-label">Preliminary findings</p>
        <div class="evidence-row"><span class="evidence-row-label">Contract verification</span><span class="evidence-row-value">Unverified</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Mint function</span><span class="evidence-row-value">Owner-only, no timelock</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Deployer history</span><span class="evidence-row-value">2 prior contracts flagged</span></div>
      </div>
      <p style="margin:12px 0 0;">Are you after a full breakdown, contract internals, liquidity events, and transaction graphs, or a quick sanity check before you dig in yourself? Flag if this ties to an active case file.</p>
      <div class="quick-replies">
        <button class="quick-reply-chip" data-fill="Full breakdown please, this is for an active investigation">Full breakdown please, this is for an active investigation</button>
        <button class="quick-reply-chip" data-fill="Quick sanity check, validating my own findings">Quick sanity check, validating my own findings</button>
      </div>
    `);
  }
 
  function professionalResolved() {
    appendAiMsg(`
      <div class="msg-ai-label"><span class="msg-ai-dot"></span>AI generated response</div>
      <span class="status-tag status-scam">Scam</span>
      <p style="margin:0 0 6px; font-weight:bold;">AI interpretation:</p>
      <ul class="evidence-list">
        <li>Contract is unverified. Decompiled
          <span class="term">bytecode<span class="term-tooltip">Bytecode is the compiled, low-level form of a smart contract, what actually runs on-chain when source isn't verified.</span></span>
          shows an owner-only mint function with no timelock.</li>
        <li>Liquidity pool drained via a single transaction shortly after pool creation, consistent with a scripted
          <span class="term">rug pull<span class="term-tooltip">A rug pull is when a project's creators suddenly withdraw funds and disappear, leaving investors with worthless tokens.</span></span>.</li>
        <li>Deployer wallet linked to two prior contracts with near-identical bytecode, both drained within an hour of launch.</li>
        <li>No reentrancy guard present, though not the primary risk vector here.</li>
      </ul>
      <div class="evidence-block">
        <p class="evidence-block-label">Raw evidence</p>
        <div class="evidence-row"><span class="evidence-row-label">Contract address</span><span class="evidence-row-value">0x7a3f...9e21</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Deployer wallet</span><span class="evidence-row-value">0x2d94...c710</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Drain tx</span><span class="evidence-row-value">0x51c8...4b0d</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Drain timestamp</span><span class="evidence-row-value">2026-09-08 14:32 UTC, 42 min post-launch</span></div>
        <div class="evidence-row"><span class="evidence-row-label">Related contracts</span><span class="evidence-row-value">0x9b1a...2f4e, 0x6e05...8a13</span></div>
      </div>
      <p class="interpretation-note">The section above is directly observed on-chain data. The bullets above it are the AI's interpretation of that data, provided to support further investigation, not as a substitute for it.</p>
      <p style="margin:10px 0 0; font-weight:bold;">Suggested next steps:</p>
      <ul class="evidence-list">
        <li>Compare bytecode of the two related contracts listed above to confirm shared authorship.</li>
        <li>Trace the drain transaction to determine where the withdrawn funds were subsequently moved.</li>
        <li>Check whether the deployer and top-holder wallets are controlled by the same entity.</li>
      </ul>
      <a class="citation-pill" href="#" onclick="return false;">Source: Etherscan &#8599;</a>
      <a class="citation-pill" href="#" onclick="return false;">Source: DexScreener &#8599;</a>
      <a class="citation-pill" href="#" onclick="return false;">Source: cryptoscamdb &#8599;</a>
    `);
  }
 
  function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
 
    if (promptHint) promptHint.style.display = 'none';
 
    appendUserMsg(text);
    chatInput.value = '';
 
    setTimeout(() => {
      if (stage === 'awaiting_leading_answer') {
        if (!tier) tier = classifyTier(text);
        if (!tier) {
          askFallbackButtons();
          return; // stage stays the same until a tier is picked via fallback buttons
        }
        stage = 'awaiting_detail';
        if (tier === 'beginner') beginnerResponse();
        else if (tier === 'intermediate') intermediateResponse();
        else professionalResponse();
      } else if (stage === 'awaiting_detail') {
        stage = 'resolved';
        if (tier === 'beginner') beginnerResolved();
        else if (tier === 'intermediate') intermediateResolved();
        else professionalResolved();
      }
    }, 500);
  }
 
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });
 
  // Position jargon tooltips using fixed coordinates so they're never
  // clipped by the scrollable thread container or hidden behind the input box.
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
 
  // Kick off the conversation with the leading question.
  askLeadingQuestion();
});