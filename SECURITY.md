# Security

Rouh holds a person's mail, calendar, files and keys, and acts for them.
A flaw in it can hurt a real person, so we want to hear about one before anybody else does.

## How to report a vulnerability

- **Privately, never in a public issue, pull request or discussion.**
- Use GitHub's private vulnerability reporting on this repository (Security, Report a vulnerability), or write to **abuse@rouh.page**, which reaches the maintainers.
- Say what you found, where (file and line, or the address and the request), how to reproduce it, and what an attacker gains. A proof of concept helps; please keep it to your own installation and test data.
- Do not read, change or delete anybody else's data, and do not test against somebody else's Rouh, rouh.land's services or the relay at rouh.page beyond what proves the flaw.

## What happens next

- We answer within **3 working days** to say we have it.
- Within **10 working days** we say whether we confirm it, how severe we judge it, and when we expect a fix.
- A critical flaw (anybody's data or keys readable or a Rouh made to act for somebody else) is fixed first, usually within 14 days; others in the next release.
- We tell you before the fix is published, credit you in its notes if you wish, and ask you to wait for the fix, or 90 days from your report, whichever is first, before you publish.

## Supported versions

| Part | Supported |
|---|---|
| Rouh's code, `main` | The newest commit that passed "Tests on main", which is what a new Rouh installs and what every Rouh is offered. Older commits are not patched; a Rouh moves forward. |
| The base image, `rouh-base` | The newest level of each line (today 1.0.x). |
| The protected core, `rouh-guard` | The version the newest base release names. |
| Rouh for Mac | The newest release on rouh.land/mac/. |

## In scope

- This repository: Rouh's server, its tools and the page it serves, the one program (`one/`), the protected core (`guard/`), the stack file and images (`deploy/stack/`, `deploy/container/`) and the release signing (`deploy/container/mac_release.py`).
- How a Rouh reads mail, pages and messages from strangers: prompt injection (words written to make Rouh do what their writer wants) that makes it send, share, pay or delete without its person's yes, or reach data across people or organisations.
- The code a new Rouh installs and its update path: anything that lets somebody other than the makers change what a Rouh runs.

## Out of scope

- Findings that need a person to install a malicious gene, give an attacker their password, or paste a key into a chat.
- Denial of service by volume, and reports from automated scanners with no shown impact.
- Third-party services Rouh connects to (Google, Anthropic, OpenAI, Cloudflare, Slack and others): report those to their owners.
- Self-hosted installations whose owner changed the code or the protected settings.
