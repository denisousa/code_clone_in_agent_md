## Methodology
1. Collect all repositories that have an AGENTS.md file containing any configuration related to code duplication
2. Compute the full clone genealogy of the collected projects
3. Identify whether a merged pull request (merged commit) was authored by a human or an agent
4. Calculate clone density for each merged commit


## Research Questions
1. How are developers configuring agents to manage code clones?

We will analyze each file and:
- Analyze the domain of the repositories
- Determine whether it is an agent or subagent file
- Check whether a specific .md file is dedicated solely to avoiding duplication
- Assess whether it is being used in a code review context


2. After adopting agent configurations, did developers become more attentive to the emergence of code clones?


3. After adopting agent configurations, did the clone density in the project decrease?
