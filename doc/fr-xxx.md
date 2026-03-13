## 0. Feature Request

'''
Replace xxx with the next available non-zero number in /doc/features.
Use lowercase IDs and filenames to match the repository convention, for example: fr-001.
The date is the approval date for the feature request.
Set STATUS to Draft until the user explicitly approves the FR.
'''

- REQUEST ID: fr-xxx
- DATE: yyyy.mm.dd
- STATUS: Draft | Approved | Implemented | Rejected
- RELATED VERSION: release.feature.fix
- IMPLEMENTATION BRANCH: fr-xxx

## 1. Summary

'''
Provide a short high-level description of the feature and the expected user or system outcome.
Keep this section readable by non-developers.
'''

## 2. Problem Statement

'''
Describe the current limitation, pain point, or business need.
Explain why the change is needed now and who is affected.
'''

## 3. Scope

### 3.1. Functional Requirements

'''
List the functional behavior that must be added or changed.
Write concrete requirements that can be validated during implementation and testing.
'''

### 3.2. Non-functional Requirements

'''
Document constraints such as performance, maintainability, observability, security, UX consistency, or Home Assistant compatibility.
Write N/A if there are no additional non-functional requirements beyond CONTEXT.md.
'''

### 3.3. Assumptions and Dependencies

'''
Capture assumptions, external dependencies, required integrations, or prerequisites.
Examples: Home Assistant entities, APIs, data sources, feature flags, or configuration values.
Write N/A if not applicable.
'''

## 4. Out of Scope

'''
Describe related ideas or adjacent work that are intentionally excluded from this FR.
This section should help prevent scope creep during implementation.
'''

## 5. Configuration and Data Impact

'''
Document any impact on configuration, environment variables, persisted data, migrations, or user-entered settings.
State explicitly if there is no configuration or data impact.
'''

## 6. Acceptance Criteria

'''
List the conditions that must be true for the feature to be accepted.
Write each criterion so it can be verified by a reviewer or tester.
'''

## 7. Implementation Notes

'''
Capture important design decisions, technical approach, constraints, risks, or open questions that should guide implementation.
This is not a full design document; keep it focused on what implementers need to know.
Write N/A if not needed yet.
'''

## 8. Test Plan

'''
Describe the automated tests required for this FR.
Include the types of tests needed and the core scenarios to cover.
If a test cannot be automated, explain why.
'''

## 9. Manual QA Checklist

'''
Describe any manual validation steps required before deployment.
If no manual QA is required, write N/A.
'''

## 10. Deployment and Rollback Notes

'''
Document anything that must be considered during release, rollout, or rollback.
Examples: configuration sequencing, feature toggles, migration order, or user communication.
Write N/A if not applicable.
'''
