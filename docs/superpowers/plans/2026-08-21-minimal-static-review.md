# Minimal Static Review Mechanism Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the file-backed Review Packet flow without adding a service, database, or second state system.

**Architecture:** Extend the existing `lib_guard.review.static_packet` source-record workflow. `packet.json`, `review_items.tsv`, and append-only responses are authoritative; `review_gate.json`, Markdown, release checks, accept-window, and Version Detail remain derived or controlled consumers.

**Tech Stack:** Python stdlib, TSV/JSON files, existing atomic writers, unittest, static HTML renderer.

## Global Constraints

- Review Gate has only `WAITING`, `BLOCKED`, and `APPROVED`.
- Packet identity includes target/base/compare and normalized policy content.
- Reviewer decisions are only `PASS`, `BLOCK`, and `QUESTION`; BLOCK/QUESTION require notes.
- Collect is deterministic, idempotent, and does not use mtime or wall-clock fields.
- No database, Web service, plugin system, automatic release, or second effective/release state.

## Tasks

1. Add failing tests for deterministic collect, policy-routing invalidation, response routing validation, and direct release-gate consumption.
2. Extend packet identity and machine facts; validate response department/reviewer/timestamp; remove non-deterministic derived timestamps.
3. Make release check consume a supplied static gate even without an alias-specific policy.
4. Update the data contract and run targeted/full verification plus browser checks where available.
