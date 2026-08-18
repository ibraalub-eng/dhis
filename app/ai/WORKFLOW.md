# Agent Workflow

## Standard Workflow

User Request
      ↓
Orchestrator
      ↓
Planner
      ↓
Architect
      ↓
Developer
      ↓
Reviewer
      ↓
QA
      ↓
Documentation
      ↓
Done


## Review Failure

Reviewer
    ↓
FAIL
    ↓
Developer
    ↓
Reviewer


## QA Failure

QA
 ↓
FAIL
 ↓
Debugger
 ↓
Developer
 ↓
QA


## Maximum Retries

3 attempts per implementation cycle.


## Blocking Conditions

Task becomes BLOCKED when:

- Required information is missing.
- Architecture decision requires human approval.
- Security risk cannot be resolved.
- Three implementation attempts fail.