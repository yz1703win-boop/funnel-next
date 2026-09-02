# Surge troubleshooting: diagnosing from first principles

Use this when the quick table in SKILL.md did not resolve the failure. The goal here is to
tell apart three failure layers that all surface as similar-looking errors: **egress**
(can packets leave?), **proxy routing** (does the CLI use the proxy?), and **credentials**
(is the token valid?). Establish them in that order — diagnosing out of order is what
produces long, wasted loops.

## Layer 1 — Egress

```bash
curl -sS -m 10 -o /dev/null -w "%{http_code}\n" https://surge.surge.sh/
```

`curl` honors `HTTPS_PROXY` from the environment natively, so this tests the path the proxy
provides, independent of anything Node does.

- `200` → egress is fine. Any surge failure is layer 2 or 3.
- `curl: (56) CONNECT tunnel failed, response 403`, or a message naming `connect_rejected`
  → the environment's network policy denies `surge.surge.sh`.

For proxy state and per-tool guidance in a Claude Code remote session:

```bash
curl -sS "$HTTPS_PROXY/__agentproxy/status"
```

Never respond to a policy denial by unsetting `HTTPS_PROXY`, disabling TLS verification, or
routing around the proxy. The denial is the environment owner's decision; the fixes are to
ask them to widen the policy, or to move the deploy to CI (`github-actions.md`).

## Layer 2 — Proxy routing in the Node CLI

This is the layer that produces the misleading errors.

Node 22 and later do not apply `HTTPS_PROXY` to outbound requests unless
`NODE_USE_ENV_PROXY=1` is set. The surge CLI checks for this and warns, but continues anyway
with a direct connection:

```
Warning - proxy settings are not being used
          re-run with NODE_USE_ENV_PROXY=1 to route through it
```

The direct connection is refused by the sandbox, and the CLI surfaces that as `Invalid token`
or `Not Authenticated` — an authentication message for what is really a transport failure.

Confirm the layer with a single comparison, changing nothing but the variable:

```bash
SURGE_TOKEN="$TOKEN" npx surge whoami                        # expect: Not Authenticated
NODE_USE_ENV_PROXY=1 SURGE_TOKEN="$TOKEN" npx surge whoami   # expect: <email> - Free
```

If the second succeeds, every later surge command needs the variable too. Environment
exports do not survive between separate tool calls, so put both variables on each command
line rather than relying on an earlier `export`.

Once `NODE_USE_ENV_PROXY=1` is set, Node prints `[UNDICI-EHPA] Warning: EnvHttpProxyAgent is
experimental`. That is expected and harmless.

## Layer 3 — Credentials

Only question the token after layers 1 and 2 are clean.

How the CLI resolves credentials (`lib/middleware/_shared/_creds.js`):

```js
req.passintoken = req.argv.token || process.env['SURGE_TOKEN'] || process.env['TRAVIS_SURGE_TOKEN'] || null
if (req.passintoken) {
  req.creds = { email: "token", token: req.passintoken }
} else {
  req.creds = localCreds(req.endpoint).get()   // reads ~/.netrc
}
```

Two consequences worth knowing:

- There is **no `SURGE_LOGIN` variable**. When a token is present the email is hardcoded to
  the literal string `token`. Supplying an email alongside the token changes nothing, and a
  mismatched email is not the cause of a failure.
- Without `SURGE_TOKEN`, the CLI falls back to `~/.netrc`, keyed by host, storing the account
  email as `login` and a token as `password`. A fresh container has no `~/.netrc`, which is
  why an unauthenticated session reports `Not Authenticated` rather than prompting.

A genuinely invalid token means the user's `npx surge token` ran without a prior successful
`npx surge login` on that machine. Ask them to confirm locally:

```
npx surge whoami     # must print their email, e.g. "user@example.com - Free"
npx surge token
```

If `whoami` works locally and the token still fails here after the proxy is confirmed
working, the token may have been rotated by a later `surge login` elsewhere — tokens are
per-session and `surge logout` expires them. Ask for a fresh one.

## Publish-time failures

| Message | Meaning |
|---|---|
| `domain is already taken` / ownership error | Another account owns that subdomain; choose a different name |
| `aborted` after the file table | Usually a dropped connection mid-upload; re-run the same command, it is idempotent |
| Publish succeeds but the URL 404s | The directory had no `index.html` at its root — check what was actually uploaded |
| Publish succeeds but shows an old version | Surge caches at the edge briefly; re-check after a few seconds before re-deploying |

## Verifying what actually shipped

The CLI's success message describes what it sent, not what serves. Confirm independently:

```bash
curl -sS -m 15 -o /dev/null -w "HTTP: %{http_code}  size: %{size_download}\n" https://<domain>/
curl -sS -m 15 https://<domain>/ | head -20     # spot-check the markup that landed
```

A `200` with an implausibly small byte count usually means a fragment was published without
its wrapper, or the wrong directory was passed.
