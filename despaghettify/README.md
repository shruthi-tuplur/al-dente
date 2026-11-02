# Despaghettify

A code audit tool that reviews attorney-built scripts and explains, in plain English, how to make them secure and ready for a whole team.

## Problem

Attorneys are increasingly building their own tools with AI coding assistants. These tools often work for one person but are not ready for a team: API keys in the code, confidential data sent where it should not go, hardcoded file paths, no tests, no error handling, one giant function.

## How it works

Despaghettify takes a Python script or small project and produces a report with findings in four categories:

- **Security:** secrets in code, unsafe handling of confidential or privileged data, data sent to unapproved services
- **Reliability:** missing error handling, no tests, hardcoded paths
- **Maintainability:** structure, readability, duplication
- **Data minimization:** whether the tool uses more data than it needs

Each finding has a severity level and a plain-English explanation written for a non-engineer.

## Why not just use a linter

General-purpose linters and secret scanners catch code problems but do not know about legal risk. Despaghettify focuses on what matters to legal teams, like privileged data going to unapproved AI services and data minimization, and explains findings in language an attorney can act on.

## Design choices

- Deterministic checks where possible (secret scanning, pattern detection).
- LLM review for structure and design suggestions.
- A human decides what to change.

## Status

Planned. MVP: Python scripts only, security and reliability checks, plain-English report.
