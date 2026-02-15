# Manager + Subagent Pattern

## Overview
Coordinate complex projects using manager + subagent architecture for better quality and context management. This pattern prevents context dilution and maintains high code quality across multi-component projects.

## When to Use This Skill

**Use this pattern when:**
- Complex projects with 5+ distinct components
- Multi-day work spanning multiple sessions
- Cross-functional tasks (frontend + backend + database + testing)
- Quality concerns where single-agent approach produces mixed results
- Integration needs between different system parts

**Don't use for:**
- Simple, single-focus tasks (just do them directly)
- Quick bug fixes (unless systemic)
- Standalone features under 100 lines

---

## The Core Pattern

### Manager Role
The manager Claude:
- Understands full project scope
- Creates specialized subagents with clear responsibilities
- Coordinates subagent work
- Integrates components
- Reviews quality across all deliverables
- Handles cross-cutting concerns

### Subagent Roles
Each subagent:
- Focuses on ONE specific responsibility
- Works in clean, isolated context
- Produces specific deliverables
- Has clear completion criteria
- Reports back to manager

---

## How to Invoke This Pattern

### Basic Invocation
```
"Act as a project manager coordinating subagents to [task].

Create subagents for:
1. [Specific role] - [Specific responsibility]
2. [Specific role] - [Specific responsibility]
3. [Specific role] - [Specific responsibility]

Coordinate their work and integrate the pieces."
```

### Tidify-Specific Example
```
"Act as project manager for Tidify Phase 3 fixes.

Create subagents to:
1. Diagnostics Engineer - Analyze the duplicate metadata write bug
2. Backend Developer - Implement transaction-based fix
3. QA Engineer - Write comprehensive tests
4. Integration Specialist - Ensure fix works across all data types

Coordinate their work and deliver a production-ready solution."
```

---

## Real Tidify Use Cases

### Use Case 1: Fix Duplicate Metadata Writes (Phase 3)

**Problem:** Race condition causing duplicate writes to metadata.json

**Traditional Approach (Single Agent):**
```
You: "Fix the duplicate metadata write issue"
Claude: [tries to analyze, fix, test all at once]
Result: Context gets muddled, incomplete fix
```

**Manager-Subagent Approach:**
```
You: "Act as project manager. Fix duplicate metadata writes using subagents."

Manager Claude:
🔷 Diagnostics Engineer (Subagent 1)
Task: Root cause analysis
Steps:
- Trace write calls in phase3-orchestrator.ts
- Identify concurrent write scenarios
- Document race condition timing
Deliverable: Root cause report + reproduction steps

🔷 Backend Developer (Subagent 2)
Task: Implement transactional fix
Steps:
- Add write locking mechanism
- Implement atomic read-modify-write
- Handle concurrent access gracefully
Deliverable: Fixed code in phase3-orchestrator.ts

🔷 QA Engineer (Subagent 3)
Task: Comprehensive testing
Steps:
- Write concurrent write test scenarios
- Test with different data types (NPI, TIN, dates)
- Verify no duplicates under load
Deliverable: Test suite proving fix works

🔷 Code Reviewer (Subagent 4)
Task: Quality review
Steps:
- Check for edge cases
- Verify performance impact
- Ensure backward compatibility
Deliverable: Approved, optimized solution
```

### Use Case 2: Phase 2 Cost Optimization

**Goal:** Reduce LLM costs from $0.28 to $0.04 per file

**Manager-Subagent Approach:**
```
You: "Act as project manager. Optimize Phase 2 to hit $0.04/file target.

Create subagents for:
1. Cost Analyst - Measure current costs, identify expensive operations
2. Algorithm Designer - Design hybrid intelligence approach
3. Implementation Engineer - Build new phase2-orchestrator.ts
4. Validation Engineer - Ensure accuracy stays 85-99%
5. Performance Engineer - Benchmark and optimize"

Manager coordinates:
- Cost Analyst identifies: LLM calls for dates are expensive
- Algorithm Designer: Use regex for dates, LLM for complex fields
- Implementation Engineer: Builds new orchestrator
- Validation Engineer: Runs test suite across 1000 files
- Performance Engineer: Confirms $0.04 target hit
```

### Use Case 3: New Feature - Auto ZIP Code Fixing

**Goal:** Automatically fix malformed ZIP codes

**Manager-Subagent Approach:**
```
You: "Act as project manager. Add auto-fix for ZIP codes.

Subagents:
1. Requirements Analyst - Define ZIP code validation rules
2. Pattern Designer - Create regex patterns + edge cases
3. Backend Developer - Implement in unique-value-extractor.ts
4. Frontend Developer - Add UI indicator for auto-fixed ZIPs
5. QA Engineer - Test with real malformed data"

Manager ensures:
- Requirements cover: 5-digit, ZIP+4, missing leading zeros
- Patterns handle edge cases
- Backend integrates with existing Phase 2 flow
- Frontend shows "Auto-fixed: 1234 → 01234"
- Tests prove 99%+ accuracy
```

---

## Step-by-Step: Using in Tidify Today

### Example: Fix the Undo Functionality Issue

**Current Problem:** Undo button not reverting changes properly

**Step 1: Start Manager Session**
```
You: "Act as project manager for Tidify. We need to fix the undo 
     functionality that's failing to revert changes properly.
     
     Create subagents to:
     1. Debug the current undo implementation
     2. Design the correct state management
     3. Implement the fix
     4. Test across all Phase 3 scenarios
     
     Coordinate and deliver working solution."
```

**Step 2: Manager Creates Subagents**
```
Manager Claude:
"I'll coordinate this fix using 4 specialized subagents.

🔷 Debugging Specialist (Subagent 1)
Starting investigation of undo mechanism...

[Subagent 1 works in clean context]
- Reviews phase3-conversational-fix-handler.ts
- Traces state updates
- Identifies: State not properly captured before edits

Deliverable: Root cause identified - missing state snapshot
```

**Step 3: Implementation Subagent**
```
Manager: "Passing findings to Implementation Engineer..."

🔷 Implementation Engineer (Subagent 2)
Building fix based on diagnostics...

[Subagent 2 stays focused on implementation]
- Add state snapshot before any edit
- Implement deep clone for metadata
- Add version tracking for undo stack

Deliverable: Fixed code in conversational-fix-handler.ts
```

**Step 4: Testing Subagent**
```
Manager: "Moving to QA for validation..."

🔷 QA Engineer (Subagent 3)
Testing undo across scenarios...

[Subagent 3 focuses purely on testing]
Test scenarios:
✓ Undo single field change
✓ Undo multiple changes
✓ Undo then redo
✓ Undo with different data types
✓ Undo after auto-fixes

Deliverable: All tests passing
```

**Step 5: Integration Review**
```
Manager: "Final integration review..."

🔷 Integration Specialist (Subagent 4)
Reviewing complete solution...

Checks:
✓ No performance degradation
✓ Works with USE_NEW_PHASE2=true flag
✓ Backward compatible
✓ No side effects on other features

Deliverable: Production-ready fix approved
```

**Step 6: Manager Delivers**
```
Manager Claude:
"Undo functionality fix complete.

Summary:
- Root cause: Missing state snapshots
- Solution: Deep cloning before edits + undo stack
- Testing: All scenarios validated
- Performance: No measurable impact

Files changed:
- src/app/actions/phase3-conversational-fix-handler.ts

Ready to commit."
```

---

## Best Practices for Tidify

### 1. Define Clear Subagent Boundaries

**Bad:**
```
Subagent 1: Fix Phase 3
```

**Good:**
```
Subagent 1: Database Specialist
- Focus: phase3 metadata persistence
- Scope: Fix duplicate writes in metadata.json
- Deliverable: Atomic write implementation
```

### 2. Use Tidify-Specific Roles

**Common Tidify Subagents:**
```
- Phase 2 Cost Analyst
- Validation Logic Designer  
- UI/UX Specialist (for Phase 3 interface)
- Integration Engineer (Phase 2 ↔ Phase 3)
- Performance Engineer (cost/speed optimization)
- Healthcare Compliance Reviewer (HIPAA)
```

### 3. Reference Tidify Architecture

**In Your Request:**
```
"Context: Tidify uses hybrid intelligence with:
- Phase 2: Statistical + strategic LLM sampling
- Phase 3: User review + conversational fixes
- Goal: $0.04/file, 85-99% accuracy

Act as manager coordinating fix for [specific issue]..."
```

### 4. Specify Integration Points

**Example:**
```
"Ensure fix integrates with:
- phase2-orchestrator.ts (USE_NEW_PHASE2=true)
- phase2-deep-analysis.ts (validation flow)
- Existing cost-analyzer.ts (tracking)"
```

### 5. Include Success Criteria

**Example:**
```
"Success criteria:
- Accuracy: 95%+ on NPI/TIN extraction
- Cost: Stays under $0.04/file
- Speed: <30 seconds per file
- Tests: All existing tests still pass"
```

---

## Common Tidify Scenarios

### Scenario 1: New Validation Rule
```
Manager + Subagents:
1. Rules Analyst - Define validation logic
2. Pattern Designer - Create regex/LLM hybrid
3. Implementation - Add to confidence-classifier.ts
4. Testing - Validate accuracy
5. Cost Analysis - Ensure budget compliance
```

### Scenario 2: UI Enhancement
```
Manager + Subagents:
1. UX Designer - Design improvement
2. Frontend Developer - Implement React components
3. State Manager - Update state management
4. Integration - Connect to Phase 2/3 backend
5. Accessibility Reviewer - WCAG compliance
```

### Scenario 3: Performance Optimization
```
Manager + Subagents:
1. Profiler - Identify bottlenecks
2. Algorithm Optimizer - Redesign slow parts
3. Caching Specialist - Add strategic caching
4. Validator - Ensure no accuracy loss
5. Benchmarker - Prove improvements
```

### Scenario 4: New Data Type Support
```
Manager + Subagents:
1. Requirements - Define new field specs
2. Extractor - Add to unique-value-extractor.ts
3. Classifier - Update confidence-classifier.ts
4. Pattern Expander - Add to pattern-expander.ts
5. Integration - Ensure Phase 3 can edit
```

---

## Troubleshooting

### Problem: Subagents Overlap
**Symptom:** Multiple subagents editing same file
**Solution:** 
```
"Manager: Define clear boundaries.
- Subagent 1: Only database layer
- Subagent 2: Only API layer  
- Subagent 3: Only UI layer
No overlaps."
```

### Problem: Manager Too Passive
**Symptom:** Subagents work in isolation, no integration
**Solution:**
```
"Manager: Actively coordinate.
After each subagent:
- Review deliverable
- Check integration points
- Validate against requirements
- Pass context to next subagent"
```

### Problem: Too Many Subagents
**Symptom:** Coordination overhead, confusion
**Solution:** Keep to 3-5 subagents for most tasks

### Problem: Context Loss
**Symptom:** Later subagents don't know what earlier ones did
**Solution:**
```
"Manager: Maintain state.
After each subagent, summarize:
- What was delivered
- What changed
- What next subagent needs to know"
```

---

## Measuring Success

**You'll know it's working when:**

✅ **Fixes are complete** - No missing edge cases
✅ **Code quality improves** - Cleaner, better tested
✅ **Less back-and-forth** - Gets it right first time
✅ **Easier debugging** - Can trace to specific subagent
✅ **Faster iterations** - Changes go to right specialist
✅ **Better integration** - Components work together

**For Tidify specifically:**
✅ Accuracy stays 85-99%
✅ Costs stay under $0.04/file
✅ No regressions in existing features
✅ Tests pass consistently
✅ Production-ready code

---

## Advanced: Multi-Session Projects

For work spanning multiple days:

### Session 1: Architecture
```
Manager + Subagents:
1. Architect - Design overall approach
2. Database Designer - Schema design
3. API Designer - Endpoint contracts

Manager saves: Architecture decisions, contracts
```

### Session 2: Implementation
```
Resume with same manager context:
"Continue from Session 1. Implement using:
1. Backend Developer - Build API
2. Frontend Developer - Build UI
3. Integration - Connect pieces"
```

### Session 3: Testing & Polish
```
Continue:
"Final phase:
1. QA Engineer - Full test suite
2. Performance Engineer - Optimize
3. Documentation - Update docs"
```

---

## Integration with Existing Skills

**Works great with:**

### systematic-debugging
```
Manager: "Use systematic-debugging skill for diagnostics"
Diagnostics Subagent: Follows structured debugging process
```

### test-driven-development  
```
Manager: "Use TDD for all implementation"
QA Subagent: Writes tests first, then implementation
```

### Cost Optimization
```
Manager: "Every decision must consider cost impact"
Cost Analyst Subagent: Validates $0.04/file target
```

---

## Quick Reference

### Invoke Manager Pattern
```
"Act as project manager coordinating subagents for [task]."
```

### Common Tidify Subagents
- Diagnostics Engineer
- Backend Developer  
- Frontend Developer
- QA Engineer
- Cost Analyst
- Performance Engineer
- Integration Specialist
- Healthcare Compliance Reviewer

### Success Criteria Template
```
"Success means:
- Accuracy: [metric]
- Cost: [budget]
- Performance: [speed]
- Tests: [coverage]
- Integration: [compatibility]"
```

---

## Examples Library

See `/examples` directory for:
- `duplicate-metadata-fix.md` - Full walkthrough
- `zip-code-autofix.md` - New feature example
- `phase2-cost-optimization.md` - Cost reduction
- `undo-functionality-fix.md` - Bug fix

---

**Remember:** This pattern shines for complex, multi-component work. For simple tasks, just work directly with Claude. Use the right tool for the job!
