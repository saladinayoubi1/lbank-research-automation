## Summary

Describe the change and why it is needed.

## NEXUS architecture precheck

- **System Map nodes**: <e.g. RES-30, VAL-40>
- **Existing component**: <component/workflow/module being extended>
- **Duplicate-work check**: <why this reuses/extents existing architecture instead of creating a parallel path>
- **Primary executor / lane**: <GitHub-hosted / NEXUS-RESEARCH-RUNNER / NEXUS-LOCAL-RUNNER / other mapped lane>
- **Upstream dependencies**: <nodes/contracts/data required before this change>
- **Downstream consumers**: <nodes/product surfaces affected>
- **Authority / Paper-Live boundary**: <authority level; explicitly state Live=false>
- **Data provenance**: <source identity, registry, or N/A with repository-only rationale>
- **Failure mode / rollback**: <fail-closed behavior and rollback>
- **Tests / independent QA**: <tests and whether independent QA is required>
- **Deployment impact**: <none / staged / runner / product cutover impact>
- **DONE evidence**: <exact evidence required before this may be called DONE>

## Safety confirmation

- [ ] Demo/Paper-only boundaries remain intact.
- [ ] No credentials, withdrawals, billing authority, or Live trading path is introduced.
- [ ] No duplicate active runner or Paper writer is introduced.
- [ ] Existing ADRs/contracts were checked and updated when required.
