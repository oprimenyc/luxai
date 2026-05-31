# GEMINI.md

## Project Mission

This project is a luxury-grade autonomous multi-agent AI operating system focused on:

- institutional-quality orchestration
- autonomous research
- deterministic paper trading
- options/SPY workflow execution
- operational reliability
- long-term maintainability
- eventual real-world deployment readiness

This is NOT a toy project.
This is NOT a demo project.
This is NOT a rapid prototyping sandbox.

The objective is a stable, trustworthy, operational platform.

---

# PRIMARY DEVELOPMENT PRINCIPLES

## 1. Stability Over Expansion

Never prioritize new features over operational reliability.

Avoid:

- speculative architecture
- unnecessary abstractions
- duplicate systems
- experimental rewrites
- feature creep

Prefer:

- stabilization
- simplification
- observability
- correctness
- maintainability

---

## 2. No Fake Implementations

Never create:

- placeholder code
- mocked production logic
- fake integrations
- simulated success responses
- TODO-driven architecture

All implementations must be:

- executable
- testable
- operationally valid

---

## 3. Validate Before Claiming Success

Never claim:

- "complete"
- "production ready"
- "fully operational"

without:

- runtime validation
- startup verification
- typecheck verification
- API verification
- websocket verification
- Docker verification

---

## 4. Incremental Engineering Only

Do NOT perform massive uncontrolled rewrites.

Always:

- work in small batches
- explain changes
- preserve operational stability
- minimize blast radius
- maintain backwards compatibility when possible

---

## 5. Architecture Discipline

The current architecture already contains:

- frontend
- api
- orchestrator
- event bus
- telemetry
- workflow engine
- memory system
- governance layer
- trading engine
- replay engine
- websocket infrastructure

Do NOT introduce:

- additional orchestration frameworks
- additional databases
- unnecessary microservices
- redundant agent systems
- speculative AI abstractions

---

# TRADING SYSTEM RULES

## ABSOLUTE RULES

### NEVER ENABLE LIVE TRADING

The system must remain PAPER TRADING ONLY unless explicitly authorized.

### RISK SYSTEMS MUST REMAIN DETERMINISTIC

The following systems must NEVER depend on LLM outputs:

- stop loss
- take profit
- trailing stops
- position sizing
- exposure limits
- daily loss limits
- execution safety

### OPTIONS SAFETY

All options workflows must validate:

- liquidity
- spread width
- delta constraints
- IV constraints
- expiration constraints
- max loss

before execution.

---

# OPERATIONAL PRIORITIES

Priority order:

1. startup reliability
2. runtime correctness
3. websocket stability
4. deterministic execution
5. observability
6. maintainability
7. performance optimization
8. UX refinement
9. feature expansion

---

# RESPONSIVE UI REQUIREMENTS

The platform must function across:

- desktop ultrawide monitors
- laptops
- tablets
- mobile devices

The frontend must remain:

- responsive
- touch-friendly
- keyboard navigable
- low-clutter
- information-dense
- readable under stress conditions

Trading and monitoring workflows must remain operational on mobile devices.

Avoid:

- fixed-width layouts
- oversized dashboards
- unscrollable panels
- hover-only interactions
- desktop-only assumptions

All major pages must gracefully adapt between:

- stacked mobile layouts
- tablet split layouts
- desktop multi-panel layouts

The design aesthetic should resemble:

- institutional trading terminals
- luxury fintech platforms
- high-end operational dashboards

NOT:

- crypto casino interfaces
- gamer aesthetics
- bloated admin templates
- cluttered analytics walls

---

# FRONTEND STANDARDS

The UI must feel:

- premium
- intentional
- minimal
- institutional
- responsive
- information-dense without clutter

Avoid:

- gimmicky animations
- unnecessary motion
- toy aesthetics
- dashboard overload

---

# CODE QUALITY RULES

Always:

- use strict typing
- remove dead code
- avoid duplicate logic
- prefer explicitness
- document operational assumptions
- validate environment variables
- handle async failures safely

Never:

- suppress type errors casually
- use unsafe any
- ignore exceptions silently
- create hidden side effects
- bypass risk controls

---

# AUTONOMOUS AGENT RULES

Before major changes:

1. analyze existing implementation
2. explain reasoning
3. validate compatibility
4. apply minimal necessary changes
5. verify runtime behavior

If uncertain:

- stop
- ask for clarification
- do not hallucinate architecture

---

# SUCCESS METRIC

Success is NOT:

- maximum code generation
- maximum features
- maximum agents

Success IS:

- reliable runtime behavior
- deterministic execution
- operational clarity
- maintainable architecture
- safe evolution toward production readiness
