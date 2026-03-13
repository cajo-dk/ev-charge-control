## 0. Fix Record

'''
Replace xxx with the next available non-zero number in /doc/fixes.
Use lowercase IDs and filenames to match the repository convention, for example: fix-001.
This template is completed when a fix is deployed.
The date is the deployment date of the fix.
'''

- FIX ID: fix-xxx
- DATE: yyyy.mm.dd
- STATUS: Draft | Deployed | Rolled Back
- RELATED VERSION: release.feature.fix
- IMPLEMENTATION BRANCH: fix-xxx

## 1. Summary

'''
Provide a concise description of the defect and the delivered correction.
This section should allow a reader to understand the fix without reading the code.
'''

## 2. Issue Description

'''
Describe the defect, symptom, or incorrect behavior that existed before the fix.
Include relevant context such as affected flows, systems, or users.
'''

## 3. Root Cause

'''
Explain the underlying cause of the issue as it was understood during diagnosis.
Write N/A if the root cause could not be determined with confidence.
'''

## 4. Resolution

'''
Describe what was changed to correct the problem.
Summarize the technical approach and any important tradeoffs.
'''

## 5. Scope and Impact

'''
Document what areas of the application were affected by the issue and what areas were changed by the fix.
Also describe any known side effects, compatibility considerations, or residual risks.
'''

## 6. Validation

'''
Describe how the fix was validated.
Include automated tests, manual verification, reproduction steps, or monitoring checks as relevant.
'''

## 7. Deployment Notes

'''
Capture anything important about deploying this fix, such as sequencing, configuration changes, required restarts, or rollback considerations.
Write N/A if deployment is straightforward.
'''

## 8. References

'''
Link or reference related FRs, issues, logs, commits, pull requests, or incident notes.
Write N/A if there are no supporting references.
'''
