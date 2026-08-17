# Privacy and intellectual-property policy

## Default rule

If public permission, ownership, or sensitivity is uncertain, do not move the information into a Social Commit.

## Never persist or publish

- API keys, tokens, cookies, passwords, OAuth material, private keys, or credential-shaped strings
- `.env` contents, credential stores, private configuration, or debug dumps
- private URLs, internal hostnames, database connection strings, or local absolute paths
- raw source code, raw diffs, proprietary algorithms, or unpublished roadmap details
- customer, partner, employee, private-message, or personally identifying data
- paid, licensed, embargoed, or otherwise unauthorized third-party material

## Safe transformation

Record the meaning of a change, not its implementation.

Unsafe:

```text
src/engine/staff.ts changed diagnosis from 100 to 80 using this code: ...
```

Safer:

```text
Recalibrated the entry-level diagnosis model so simulations no longer overestimate staff ability.
```

## Two-layer review

1. The script rejects common secret shapes, absolute paths, forbidden fields, and non-whitelisted event fields.
2. The agent performs semantic review for trade secrets, copyright, personal data, and contextual disclosure.

Passing the script is not proof that content is safe. Human approval remains required.

