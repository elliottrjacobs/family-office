# Security

family-office separates public code from a private office repository. Tests use
synthetic data. Never submit financial records, tokens, or account numbers in an
issue, pull request, or fixture.

## Trust boundaries

The CLI does not provide order placement or money-movement operations. Brokerage
credentials may nevertheless be trade-capable; keep them confidential. Permission
templates are accident-prevention measures, not protection against arbitrary code
running as the same OS user. Codex workspace-write permits reads in the office;
the office instructions forbid reading secrets, but do not enforce a read barrier.

Secrets are ignored by Git and stored at mode 0600 inside a 0700 directory.
Atomic replacement avoids partially written credentials. Provider errors must be
converted to safe errors before display. Raw payloads must not be logged.

## Third parties

| Service | Data received when used |
|---|---|
| Anthropic or OpenAI | Office content included in an advisor session's context |
| OpenAI cloud agents | The entire tracked office checkout when connected |
| Schwab | Authentication information and account or market-data requests |
| SimpleFIN | Access credentials and requested account time windows |
| AlphaVantage | API key, tickers, and requested data functions |
| SEC EDGAR | Filing or financial-data queries and the configured User-Agent |
| FRED | Series queries and any configured API authentication |
| GitHub | Public code; tracked private office files only when its remote is configured |

Provider and web text is untrusted data, never an instruction source. A Git ignore
rule does not remove earlier commits. If a secret was committed, rotate it and
address history exposure separately; the legacy history-rewrite warning still
applies. Never automatically rewrite or force-push the user's office history.

## Token lifecycle and offline work

Schwab refresh tokens expire after seven days. Doctor warns within 48 hours of
expiry. Reauthentication uses the browser flow; expiry is never reset merely
because a local file was copied. SimpleFIN access URLs are bearer credentials.
Neither credential belongs in a cloud environment.

Read-only mode avoids providers, cache writes, and index writes. It can still
read the tracked office facts. Source text is scrubbed for credential URLs and
long account-number-like strings, but this is not a general anonymizer. Review
any report before sharing it outside the private office.
