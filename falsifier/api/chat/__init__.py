"""
falsifier.api.chat
==================
Tool-calling chat layer over pipeline artifacts.

All numbers returned to users originate from pipeline artifact fields stored
in the in-memory job store (_job_store).  No number is hardcoded here.

Sub-modules
-----------
tools         — 8 deterministic tools that read from _job_store artifacts
guardian      — Granite Guardian output-safety screening wrapper
system_prompt — builds the LLM system prompt at runtime (never hardcoded)
session       — conversation state + tool-call loop
"""
