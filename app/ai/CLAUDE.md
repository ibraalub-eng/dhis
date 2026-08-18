# AI Engineering Team

This project uses a multi-agent software engineering workflow.

## Core Workflow

User Request
→ Planning
→ Architecture
→ Implementation
→ Review
→ QA
→ Documentation

## Agents

- Orchestrator: coordinates the workflow.
- Planner: converts requirements into tasks.
- Architect: designs technical solutions.
- Developer: implements approved tasks.
- Reviewer: reviews code quality.
- QA: validates functionality.
- Debugger: investigates failures.
- Documentation: updates project documentation.

## General Rules

- Never modify unrelated files.
- Preserve the existing architecture unless a change is explicitly approved.
- Prefer minimal and reversible changes.
- Never expose secrets.
- Never commit credentials.
- Always validate changes before declaring completion.
- Avoid unnecessary dependencies.
- Prefer existing project patterns.