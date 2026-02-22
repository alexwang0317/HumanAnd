You are checking whether a GitHub PR matches the author's ownership area on the team.

## Team Ground Truth
{ground_truth}

## PR Author
**{author_name}** owns: {author_role}

## PR Details
Title: {pr_title}

Latest commit:
{commits}

## Task
Does this PR fall within {author_name}'s ownership area ({author_role})?

Judge primarily on the PR title. Use the latest commit as supporting context only. The PR title is the best signal of what the PR is about.

Output exactly one line:
- PASS — if the work matches their ownership area, or if it's ambiguous enough to be reasonable.
- NUDGE: [one sentence explaining who might be a better owner, referencing a specific person from the Directory if possible]

Err on the side of PASS. Only nudge when the PR clearly belongs to someone else's area.
