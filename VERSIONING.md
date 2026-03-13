## 1. Versioning Instructions

The app must be versioned as follows:

    release.feature.fix

### 1.1. Releases

A release is a fundamental change to the app, such as a change in programming language, a new database type, a change in architecture, e.g., a move from orchestration to choreography, or a change to the UI/UX to the point where the new and old releases seem like two different applications.

### 1.2. Feature Requests

A feature must add recognizable functional or non-functional improvements; but they cannot render the UI/UX unrecognizable from the application running without the feature applied.

### 1.3. Fixes

A fix is a correction or remedy for an identified issue in the application.

## 2. Documentation Requirements

### 2.1. Releases

Documentation of Releases will be described here later. Release 1 will be the first release and, therefore, subject to the governance in CONTEXT.md

### 2.2. Feature Requests (FRs)

- When asked to start planning a new feature you must create a FR document in /doc/features with the file name fr-xxx.md - with xxx being the next available non-zero file number in the target folder.
- Use the template in /doc/fr-xxx.md to document your planning.
- You must fill out the pre-configured sections. Instructions are included as ''' comment '''
- Replace the comments with your documentation. If there is nothing to document in a specific section, simply write: N/A. You may add additional sections to each document as necessary for the FR.
- A user must approve the FR before you can start implementing.
- A feature must be developed in its own Git branch and merged into the main branch when deployed. The branch should be named fr-xxx similar to the FR id.

### 2.3. Fixes

Fixes are registered in /doc/fixes and are numbered and named fix-xxx.md - and they are documented when deployed by filling out a template /doc/fix-xxx.md and placing it in the /doc/fixes folder.

When asked to start work on a fix, you must check out a branch with the same name as the fix, and you must merge it back into the main branch on deployment.
