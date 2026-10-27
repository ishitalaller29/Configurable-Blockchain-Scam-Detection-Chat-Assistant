# Blockchain Scam-Detection Chat Assistant (Capstone)

> **Status: early vertical slice.** The AI pipeline logic works end to end;
> the blockchain data it reasons over is currently fake. 

## What this is

A chat assistant that answers questions about a blockchain address - scam check, info lookup, or general question - backed by evidence rather than unsupported opinion. Full design in [`SPEC.md`].

This repo currently implements one path end to end: a chat message goes through the **Business Analyser** (LLM), and if it's a scam check with no detector configured, the **Scam Checker** (LLM) reasons over evidence and returns a verdict. The evidence is fake for now - real fetchers, the
Detector Connector, and the Forensic Investigator aren't built yet.

## Setup

```bash
# LLM: local Ollama running llama3.1
ollama pull llama3.1
ollama serve

# Python deps
pip install -r requirements.txt

# Run
python cli.py "Is 0xABCDEF1234567890 a scam?"
```

## Structure

```
schema.py                          data contracts (AddressContext, DetectionResult, ...)
config.py                          LLM backend settings
fake_data.py                       stand-in blockchain evidence (no real fetchers yet)
cli.py                             entry point - runs the pipeline end to end
agents/
  business_analyser.py             scope check, request classification, input extraction
  scam_checker.py                  no-detector fallback: judges evidence, explains itself
llm_providers/
  base.py                          common LLMProvider interface
  openai_compatible.py             adapter for any OpenAI-compatible endpoint 
```

## Use Case & Expertise Extraction Flow

### Description
The assistant adapts its answers to who is asking. The Business Analyser reads the conversation and works out two things: the user's **expertise tier** (`beginner`, `intermediate`, `professional`) and their **use case** (`investment`, `investigative_legal`, `compliance_risk`). If it can't tell, it asks the user once. If the user's signals conflict (for example plain language but a compliance use case), the tier defaults to `beginner`. Once both are known they are kept for the rest of the session. The tier and use case set how the Forensic Investigator words its explanation.

### Prompt Strategy
- **Agent:** Business Analyser only (`agents/business_analyser.py`).
- **Type:** One system prompt with explicit rules and worked input-to-output examples (a few-shot style), configured as `zero_shot` in `config/app_config.json`. The model must reply with a single JSON object (`expertise_tier`, `use_case`, `needs_clarification`).
- **Why:** The signals are subtle ("wallet" vs "contract internals"), so examples keep the tiers consistent. A fixed JSON shape lets the conversation layer act on the result without parsing prose. The rules look at the whole conversation, not just the last message.

### Use Case (when it runs)
It runs on **every user message**, as part of the Business Analyser's single call (`ChatSession._run_turn` in `conversation.py`). The extraction only becomes visible to the user when the tier or use case is still unknown (`needs_clarification: true`).

### Fallback Prompt
When the first message gives too little signal, the assistant asks one combined question: *"Have you used crypto much before, and what brings you here today?"* If the answer is still too vague, it shows four quick-reply buttons instead (`_PROFILE_FALLBACK_OPTIONS`): checking before buying, investigating for work, developer/researcher, or not sure yet. The choice is sent as the next message and the Business Analyser extracts the tier and use case from it.

![Fallback prompt example](docs/images/fallback-prompt.png)

### Known Bugs & Issues
- **Loop after "Not sure yet":** the fallback buttons only appear once. If the user is still vague, the assistant asks the opening question again.
- **Stale buttons:** if the user types instead of clicking, the old buttons stay on screen.
- **Buttons lost on a failed request:** if the request fails, the buttons are not restored (from the Retesting log, to be re-checked).
- **No default tier for vague users:** the assistant keeps asking instead of falling back to a neutral tier.
- **Scam Checker is not tailored:** the tier and use case reach the Forensic Investigator but not the Scam Checker.
- **`address_info` requests:** tier and use case have come back null in test runs.

## Frontend

The frontend is plain HTML, CSS and JavaScript in `frontend/` (no framework or build step), served by `server.py`. It has two pages: a starting page and the chat page. Admin tools live in a sidebar on the chat page.

### Admin View

![Admin panel](docs/images/admin-panel.png)

**Opening it.** The **Admin** button in the top bar opens a passphrase dialog. A correct passphrase opens the left sidebar and the button changes to **Admin (exit)**; clicking that hides the sidebar again. A wrong passphrase shows an error and keeps the sidebar closed, and Cancel or Esc closes the dialog.

**What can be configured**

| Setting | What it does |
|---|---|
| Connected sources | Turns Etherscan and DexScreener on or off as data sources. At least one has to stay on. Saving starts a fresh conversation. |
| + add source | Adds an external detector. Enter a name and the address of a running Detector API Wrapper (for example `http://localhost:8002`). The server checks the wrapper is up and has a detector set up, then saves it on that machine. |
| Active Detector | Chooses who answers scam checks. "None (Scam Checker)" means the app's own Scam Checker decides. Picking a detector means it decides and the Forensic Investigator explains its evidence. Changing it starts a fresh conversation. |
| LLM Backend Config | Sets the provider (`openai_native`, `anthropic_native`, `gemini_native`, `openai_compatible`) and model for each of the three agents: Business Analyser, Scam Checker and Forensic Investigator. Saving applies at once, with no restart. The panel marks a provider that isn't wired up yet. |
| Download API wrapper template | Downloads the Detector API Wrapper project, with a six-step "How to set it up" guide. The ZIP must be placed at `downloads/detector-api-wrapper-template.zip` on the server. |

**Why it is admin only.** The client specified that regular users should only see the chat. These settings change which services the app calls, what it costs and which model writes every answer, so a change affects every user's results. API keys stay on the server and are never sent to the browser.

**The admin lock (current decision).** The passphrase is hardcoded in `frontend/chatbox-page/script.js` as `ADMIN_PASSPHRASE` (currently `admin`). The client suggested a shared passphrase, and the technical advisor meeting confirmed it as the simplest acceptable approach, because real accounts are out of scope for this project. It only keeps the panel out of ordinary users' sight. It is checked in the browser, and the `/admin/*` endpoints on the server are not protected, so it is **not real security**. Before any real use it should be replaced by server-side sign-in and protected admin endpoints.

### Design Decisions

**Colour scheme.** Navy (`#1f3a5f`, `#14213d`) with white and light grey. Our first mockups were green with a hexagon pattern, and usability testers found them unserious for an audience of investors, investigators and compliance staff, so we moved to a calm, professional palette. Verdict tags use muted green (Not scam) and muted red (Scam). "Insufficient evidence" is neutral grey on purpose: amber would read as a risk signal when the honest answer is "we don't know". Typography is Arial, with monospace for hashes and addresses so they can be read and copied exactly.

**Output format.** Each verdict reply has the same parts, in the same order, so users learn where to look:
- A verdict tag, then the explanation in plain text. The jargon level follows the user's expertise tier, and defined terms link to a glossary.
- An **Evidence** box, then **Detection details** (confidence, risk type, and whether the result came from a configured detector or the Scam Checker's own reasoning).
- **Source pills** at the end. The Etherscan and DexScreener pills open the address page.
- A **Raw evidence** block (transaction hashes, addresses, block hashes, each with its source) for professional users only. It shows when the tier is professional or the use case is investigative or compliance. It sits in its own block so investigators can tell what the data sources returned from what the AI said about it.
- Gaps are shown, not hidden: "Insufficient evidence", and a note listing any data that could not be checked.

**Screen layout.** One chat column with the input fixed at the bottom. A badge in the header says "You're chatting with an AI assistant", because testers could only infer this from the layout. The starting page has no address box: the client wanted regular users to go straight into the chat. Admin tools sit in a sidebar that only appears after unlocking, so the normal view stays uncluttered. The paperclip is for file attachments only (it was earlier mistaken for an API source menu), and currently says attachments are not available.

**Accessibility.** Status is always shown as text as well as colour. Controls are real buttons and links, toggles use `aria-pressed`, and the dialog uses `role="dialog"`, closes with Esc and returns focus to the Admin button. Error and status messages use `role="alert"` or `role="status"`. Text is dark on light backgrounds for contrast. No formal accessibility audit has been run.

### Starting & Chat Box Pages

![Starting page](docs/images/starting-page.png)

The starting page says what the tool does in one line, with three cards for its main abilities. Both buttons lead to the chat.

| Control | What it does |
|---|---|
| Check now | Opens the chat page |
| See what else this tool can do | Opens the chat page |

![Chat page](docs/images/chat-page.png)

The chat page is the main screen. The reply above is a beginner-level answer: plain words, Evidence box, Detection details and source pills.

| Control | What it does |
|---|---|
| ChainCheck logo | Returns to the starting page |
| Admin | Opens the passphrase dialog (see Admin View) |
| Paperclip | Shows that attachments are not available yet |
| Input box (Enter) | Sends the message |
| Quick-reply buttons | Send that option as the next message |
| Source pills | Open the address on Etherscan or DexScreener in a new tab |
| Definitions pill | Shows the glossary terms used in the reply |
| Copy (Raw evidence) | Copies that hash or address |

## WireFrames
<b>Source: </b>https://miro.com/app/board/uXjVGwYXzDk=/ <br>
Final Wireframe Designs are listed under the following subheadings: <br>
<b>Starting Page:</b> <br>
Usability Testing Pages - REFINED <br>
<ul>
  <li><b>Usability Testing Pages - REFINED:</b> Updated starting page</li>
</ul> 
<br>

<b>Chat Box Page:</b> <br>
<ul>
  <li><b>Usability Testing Pages - REFINED:</b> Updated chatbox page (Normal users)</li>
  <li><b>Usability Testing Pages - REFINED:</b> Updated chatbox page (Admin users)</li>
  <li><b>Usability Testing Pages - REFINED:</b> Fallback prompt use case --> Fallback Prompt refers to the user expertise and use case extraction </li>
  <li><b>Usability Testing Pages - REFINED (Extended):</b> Display the refinements of previous beginner, intermediate, professional use cases, including the general output data format</li>
</ul> 