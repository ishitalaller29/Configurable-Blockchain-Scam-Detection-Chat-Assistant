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

