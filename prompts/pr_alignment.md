You are checking whether a GitHub PR matches the author's ownership area on the team.

## Team Ground Truth
{ground_truth}

## PR Author
**{author_name}** owns: {author_role}

## PR Details
Title: {pr_title}

Commit messages:
{commits}

## Task
Based on the commit messages and PR title, does this work fall within {author_name}'s ownership area ({author_role})?

Output exactly one line:
- PASS — if the work matches their ownership area, or if it's ambiguous enough to be reasonable.
- NUDGE: [one sentence explaining who might be a better owner, referencing a specific person from the Directory if possible]

Err on the side of PASS. Only nudge when the mismatch is clear.
