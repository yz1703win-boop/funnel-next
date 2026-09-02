---
name: surge-deploy
description: Deploy a static site, a built Next.js export, or a single HTML page to Surge.sh from a Claude Code remote/web session. Use this whenever the user wants to publish, upload, deploy, host, or preview something on Surge (surge.sh) — and especially when any `surge` command fails with "Invalid token", "Not Authenticated", or a 403/connection error, because in a sandboxed session those errors are almost always a proxy or network-policy problem rather than a bad credential. Covers the NODE_USE_ENV_PROXY=1 requirement, token authentication, the network-policy preflight check, packaging a standalone HTML page, verification, teardown, and a GitHub Actions fallback when direct egress cannot be opened.
---

# Deploying to Surge.sh

Surge publishes a directory of static files to a `*.surge.sh` domain in one command. The
command is trivial. Nearly all the difficulty comes from the sandboxed environment between you
and Surge's API, and the errors it produces point at the wrong thing. Read the next section
before running anything.

**Paths in this skill** — `scripts/` and `references/` are relative to this skill's own
directory, which is almost never your working directory. Resolve them against the path of this
SKILL.md and pass absolute paths on the command line.

## The one thing that wastes the most time

**"Invalid token" and "Not Authenticated" from Surge usually mean the proxy is not being
used — not that the token is wrong.**

Node 22+ ignores `HTTPS_PROXY`/`HTTP_PROXY` unless `NODE_USE_ENV_PROXY=1` is set. Without it
the surge CLI opens a direct connection, the sandbox's egress rejects it, and the CLI reports
that transport failure as a credential error. The CLI does warn, but it is easy to scroll past:

```
Warning - proxy settings are not being used
          re-run with NODE_USE_ENV_PROXY=1 to route through it
```

So set `NODE_USE_ENV_PROXY=1` on **every** surge invocation, `whoami` included:

```bash
NODE_USE_ENV_PROXY=1 SURGE_TOKEN="$TOKEN" npx surge whoami
```

If you take "Invalid token" at face value you will send the user off to regenerate a perfectly
good token, they will return with the same token, and it will fail again. That loop is the
most common failure here. Rule out the proxy before ever questioning a credential.

(Set the variable even when `HTTPS_PROXY` is unset — with no proxy configured it does nothing,
so there is no case where omitting it helps.)

## Workflow

### 1. Preflight: can this session reach Surge at all?

```bash
curl -sS -m 10 -o /dev/null -w "%{http_code}\n" https://surge.surge.sh/
```

`surge.surge.sh` is the API endpoint the CLI itself talks to, not just a marketing site, so
this is a real reachability test for the deploy path. `curl` honors `HTTPS_PROXY` natively,
which is what makes it a clean probe of the environment independent of Node's behavior.

- `200` → egress is open, continue.
- `curl: (56) CONNECT tunnel failed, response 403`, or a message naming `connect_rejected`
  → the environment's network policy blocks Surge. You cannot work around this from inside the
  session, and should not try — never unset `HTTPS_PROXY` or disable TLS verification. Two ways
  forward:
  - Ask the user to widen the environment's network policy (Claude Code on the web →
    environment settings → full network access, or allowlist `surge.sh`). Say that this
    applies to the whole environment rather than just this task, and can be reverted after.
  - Or use the CI fallback in `references/github-actions.md`, which deploys from a GitHub
    Actions runner and needs no egress from this session at all.

### 2. Authenticate with a token

Surge reads `SURGE_TOKEN` from the environment. There is no `SURGE_LOGIN` variable — when a
token is present the CLI substitutes the literal string `token` for the email, so the email is
irrelevant and a mismatch is never the cause of a failure.

If the user has not supplied a token, ask them to run this **on their own machine**:

```
npx surge login    # prompts for email + password; creates the account if new
npx surge token    # prints the token to paste back
```

`surge token` only returns a valid token once `surge login` has succeeded on that machine. If
a token keeps getting rejected *after* you have ruled out the proxy, ask the user to confirm
`npx surge whoami` shows their email locally.

**Do not try to drive the interactive `surge login` prompt from inside the session.** It needs
a real TTY (the password field uses raw mode), so piped stdin does not work, and reaching for
`script`/`expect`/pty tricks to feed a password through is fragile and is a credential-handling
pattern the permission layer will likely block. Ask for a token instead.

Confirm before deploying:

```bash
NODE_USE_ENV_PROXY=1 SURGE_TOKEN="$TOKEN" npx surge whoami
# -> user@example.com - Free
```

**On token exposure, honestly:** environment exports do not persist between tool calls, so the
token goes on each command line and therefore into the session transcript and shell history.
Writing it to `~/.netrc` (where the CLI would otherwise look) to avoid that is both likely to
be blocked by the permission layer and not obviously better. So do not pretend the exposure
away — tell the user it is in the transcript, and that the mitigation is rotation: a token is
revocable, and `surge logout` expires it. Never commit it to a repo, and for CI put it in a
repository secret instead.

### 3. Prepare the directory to publish

Surge serves a directory as-is and looks for `index.html` at each path.

**A Next.js app** needs a static export — set `output: "export"` in `next.config.ts`, then
build. The export lands in `out/`:

```ts
const nextConfig: NextConfig = {
  output: "export",
};
```

```bash
npm run build   # produces ./out
```

Static export rules out anything needing a server at request time: server actions, route
handlers that read the request, cookies, rewrites/redirects/headers, ISR, and `next/image` with
the default loader. If the app uses those, say so rather than shipping a broken export — Surge
is static hosting and cannot run them.

**A single HTML page** must be a complete document. Pages written for the Artifact tool are
fragments: they start at `<title>`/`<style>` with no `<!doctype>`, `<html>`, `<head>` or
`<body>`, because the artifact runtime supplies those. Publishing such a fragment "works" but
drops the charset and viewport declarations, which garbles non-Latin text and breaks mobile
layout. Wrap it into a directory of its own:

```bash
python3 <skill-dir>/scripts/wrap_html.py <fragment.html> <publish-dir>/index.html --lang ja
```

Three decisions this command bakes in, worth making deliberately rather than by default:

- **Where `<publish-dir>` goes.** Put it in a scratch directory, never inside a git checkout.
  Surge writes a `CNAME` file into whatever directory you publish, so a publish dir inside the
  repo leaves an untracked file in the user's working tree. The script creates parent
  directories itself, so no `mkdir` is needed.
- **What goes in it.** Surge publishes the directory as-is, so it should contain the page and
  nothing else — one stray file is one publicly readable stray file.
- **`--lang`.** It defaults to `ja`, which is wrong for an English page and is not something
  the output will visibly complain about. Set it to the page's actual language.

The script adds the doctype, `<meta charset>`, viewport, `color-scheme`, and a `noindex` robots
tag, splitting the fragment at its first top-level element. `--allow-indexing` omits the
`noindex`. It detects an already-complete document and copies it through unchanged, so it is
safe to run twice.

### 4. Choose a domain

Any unused `*.surge.sh` subdomain is claimed on first publish. Re-publishing the same domain
replaces its contents, so keep the domain stable across updates to one site.

**Surge sites are public — anyone with the URL can read them, and the free plan has no access
control.** When the content is internal (pricing, strategy, customer data, anything the user
would not post publicly), say so before publishing and pick a domain with a random component so
the URL is not guessable, e.g. `project-notes-x7q2m4.surge.sh`. The `noindex` tag keeps it out
of search results but is not access control. If the user needs real privacy, Surge is the wrong
tool — say so rather than shipping and hoping.

When the user supplies the domain, use it as given rather than renaming it. The warning is
still owed if the content is sensitive — they are choosing a name, not waiving the fact that
the result is publicly readable.

### 5. Publish

```bash
NODE_USE_ENV_PROXY=1 SURGE_TOKEN="$TOKEN" \
  npx surge <directory> --domain <name>.surge.sh
```

The first `npx surge` of a session downloads the package before doing anything, which can take
30 seconds or more. Give the command a generous timeout — a timeout here is a slow install, not
the network-policy problem from step 1, and misreading one as the other sends you down exactly
the wrong path.

Read the output rather than trusting the exit status, and **do not pipe it through `grep`**.
Filtering the two `[UNDICI-EHPA]` proxy warnings is not worth it: a bare `| grep -v ...`
returns grep's exit status, so a failed deploy exits 0 and reads as clean — the same species of
misleading signal this skill exists to prevent. Just read the full output.

Success prints two tables (certificate/DNS, then edge servers), then `Success! - Published to
<domain>`, then two URLs: a timestamped **live preview** (a one-off snapshot of this upload)
and the **production** domain. Report the production one. A trailing `verify your account with
'surge verify'` notice is cosmetic on the free plan and does not block anything.

Surge also writes a `CNAME` file into the published directory. Harmless, but do not commit it
into a repo's source tree by accident.

### 6. Verify

The CLI's success message describes what it sent, not what serves. Check independently, and
check the charset too — the whole reason for the wrapper in step 3 is that a missing charset
garbles non-Latin text, so a status code alone does not confirm the thing you actually care
about:

```bash
curl -sS -m 15 -o /dev/null -w "HTTP %{http_code}  %{content_type}  %{size_download}B\n" \
  https://<name>.surge.sh/
curl -sS -m 15 https://<name>.surge.sh/ | grep -F '<known string from the page>'
```

Expect `200`, `text/html; charset=UTF-8`, and a size matching what the wrapper reported. For
the second check, grep for a distinctive string you know is in the source — ideally a non-Latin
one if the page has any. Do not just `head` the response: the top of the document is doctype
and CSS, so it will look fine even when the text below it is mojibake, and confirming that text
survived is the entire reason the wrapper exists.

A `200` with an implausibly small size usually means a fragment shipped without its wrapper, or
the wrong directory was passed. Once both checks pass, give the user the URL as a plain link.

### 7. Updating and removing

- **Update**: rebuild and re-run the same publish command with the same `--domain`.
- **Remove**: `NODE_USE_ENV_PROXY=1 SURGE_TOKEN="$TOKEN" npx surge teardown <domain>`.
  Offer teardown for one-off previews, especially with sensitive content.

## Troubleshooting

| Symptom | Actual cause | Fix |
|---|---|---|
| `Invalid token` | Proxy not used (Node 22+) | Set `NODE_USE_ENV_PROXY=1` — check this before anything else |
| `Not Authenticated` from `whoami` | Same, or `SURGE_TOKEN` unset in that shell | Put both variables on the same command line; exports do not persist between tool calls |
| `curl: (56) CONNECT tunnel failed, response 403` | Environment network policy blocks surge.sh | Ask user to widen policy, or use the GitHub Actions fallback |
| Token still rejected once the proxy is confirmed working | `surge token` ran without a successful `surge login` | Ask the user to verify `npx surge whoami` locally |
| `domain is already taken` / ownership error | That subdomain belongs to another account — the `*.surge.sh` namespace is global | Pick another name; adding a random suffix avoids collisions |
| CJK text garbled, or mobile layout broken | Fragment published without `<meta charset>`/viewport | Wrap with `scripts/wrap_html.py`, then re-check `content_type` |
| Deploy "succeeds" but nothing shipped | `\| grep` swallowed a non-zero exit | Do not filter the output; verify over HTTP |
| First surge command times out | `npx` is downloading the package (30s+) | Raise the timeout and retry — this is not the policy block from step 1 |
| Untracked `CNAME` appears in the repo | Published a directory inside the git checkout | Publish from a scratch directory instead |
| `next build` errors about dynamic features | App needs a server; static export cannot support it | Name the specific feature; do not silently strip it |

Deeper diagnosis — separating egress from proxy routing from credentials, and how the CLI
resolves credentials internally — is in `references/troubleshooting.md`.

## When Surge is the wrong answer

Surge is good for a quick, public, throwaway preview. Push back and suggest alternatives when
the user needs server-side rendering or API routes, private or authenticated access, a custom
domain with real DNS control, or a deploy tied to CI on every merge. For that last case the
GitHub Actions path in `references/github-actions.md` is usually what they actually want.
