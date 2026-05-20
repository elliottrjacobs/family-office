"""Gemini wrappers for Family Office.

Two tiers — both read the API key from profile/api-keys.json -> gemini.api_key:

- scripts.gemini.fast    -> Gemini 3.1 Flash-Lite + Google Search grounding (quick lookups)
- scripts.gemini.deep_research -> Gemini Deep Research Interactions API (multi-source reports)

See profile/api-guide.md for the full tier-1-vs-tier-2 decision guide.
"""
