# Fallback: deploying to Surge from GitHub Actions

Use this path when the session cannot reach `surge.surge.sh` and the environment's network
policy will not be changed, or when the user wants every merge to publish automatically.
GitHub Actions runners have their own network egress and are unaffected by this session's
proxy policy, so the deploy succeeds there even while it is blocked here.

The tradeoff worth stating to the user: this needs a one-time manual setup in the GitHub UI
(a secret and a variable), and thereafter deploys happen on push rather than on demand. If
they only want a one-off preview and can widen the network policy, direct deploy is less work.

## Workflow file

`.github/workflows/deploy-surge.yml`:

```yaml
name: Deploy to Surge

on:
  push:
    branches:
      - main
  workflow_dispatch: {}

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm

      - name: Install dependencies
        run: npm ci

      - name: Build static export
        run: npm run build

      - name: Deploy to Surge
        run: npx surge --project ./out --domain "$SURGE_DOMAIN" --token "$SURGE_TOKEN"
        env:
          SURGE_DOMAIN: ${{ vars.SURGE_DOMAIN }}
          SURGE_TOKEN: ${{ secrets.SURGE_TOKEN }}
```

Notes on the choices here:

- **Node 20** avoids the `NODE_USE_ENV_PROXY` problem entirely — Actions runners have direct
  egress and no proxy, so there is nothing to route through. Keep the pin unless the project
  needs a newer Node to build.
- **`--token`** is passed explicitly rather than relying on the `SURGE_TOKEN` env var. Both
  work; the flag makes the credential's source obvious when reading the workflow.
- **`workflow_dispatch`** lets the user trigger a deploy from the Actions tab without pushing,
  which is useful for the first run while testing the setup.
- Adjust `./out` if the project builds elsewhere (`dist`, `build`, `public`).

## One-time setup the user must do in the GitHub UI

Repository secrets cannot be created through the GitHub API without encrypting the value
against the repository's public key, and the available tooling in a session generally does not
expose that. Treat this as the user's step and give them the exact path:

1. **Secret** — repo → Settings → Secrets and variables → Actions → *Secrets* tab →
   New repository secret. Name `SURGE_TOKEN`, value from `npx surge token` on their machine.
2. **Variable** — same page, *Variables* tab → New repository variable. Name `SURGE_DOMAIN`,
   value e.g. `project-name.surge.sh`.

Ask them to enter the token directly in that form rather than pasting it into the
conversation. A secret entered there is encrypted at rest and unreadable afterwards, including
by you; a token pasted into chat is in the transcript.

## Checking that it worked

After the user confirms setup, trigger a run and read the result rather than assuming:

- Trigger: Actions tab → *Deploy to Surge* → Run workflow, or push to `main`.
- If GitHub tooling is available in the session, list the workflow runs and fetch the failing
  job's logs rather than asking the user to copy them.

Common first-run failures:

| Failure | Cause |
|---|---|
| `Invalid token` in the Actions log | Secret missing, misnamed, or holds a token from a `surge logout`-expired session |
| `domain is already taken` | `SURGE_DOMAIN` names a subdomain owned by another account |
| Build step fails but works locally | `npm ci` needs `package-lock.json` committed and in sync with `package.json` |
| Deploy step succeeds, site is empty | Build output directory does not match `--project` |
