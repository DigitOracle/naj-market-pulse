# Putting a real login in front of the Azimuth EV map

Drafted 17 Sep 2026. Goal: `ev.digitalabbot.io` serving the EV map, behind Cloudflare Access with
email one-time codes, replacing the open `azimuth-ev.digitalchemy.workers.dev`.

## Why it isn't already done

Two constraints, both external to the code:

1. **Cloudflare Access attaches to a hostname on a Cloudflare zone.** `*.workers.dev` is Cloudflare's
   own zone, not ours, so an Access application cannot be created for the current URL.
2. **`digitalabbot.io` is on Vercel DNS**, not Cloudflare:
   ```
   digitalabbot.io  nameserver = ns1.vercel-dns.com
   digitalabbot.io  nameserver = ns2.vercel-dns.com
   ```

So a Cloudflare-controlled hostname has to exist before there is anywhere to put a login. The plan
below delegates **only the `ev` subdomain**, leaving `digitalabbot.io` and everything else on Vercel
untouched.

`wrangler` has no `access` command, and its OAuth token carries `account (read)` only, so steps 1, 2
and 5 are dashboard actions. Steps 3 and 4 are scripted.

---

## Step 1 — Add the subdomain as a zone (Cloudflare dashboard)

1. Cloudflare dashboard → **Add a site** → enter `ev.digitalabbot.io` (the subdomain, not the apex).
2. Choose the **Free** plan.
3. Cloudflare assigns two nameservers, e.g. `xxx.ns.cloudflare.com` / `yyy.ns.cloudflare.com`.
   **Write both down** — they are specific to this zone and are not the ones already serving
   `digitalchemy.workers.dev`.

> If Cloudflare declines to add a subdomain zone on the Free plan, the fallback is moving the apex
> `digitalabbot.io` to Cloudflare, which is a larger change affecting the Vercel sites on it. Do not
> do that without deciding separately — the subdomain route exists precisely to avoid it.

## Step 2 — Delegate `ev` from Vercel (Vercel dashboard)

In the Vercel DNS records for `digitalabbot.io`, add **two NS records**:

| Name | Type | Value |
|---|---|---|
| `ev` | NS | *(first Cloudflare nameserver from step 1)* |
| `ev` | NS | *(second Cloudflare nameserver from step 1)* |

Nothing else changes. Everything at the apex and every other subdomain keeps resolving through
Vercel exactly as now.

Confirm delegation has propagated before continuing:

```bash
nslookup -type=NS ev.digitalabbot.io
```

It should answer with the two Cloudflare nameservers. This is usually minutes, occasionally hours.

## Step 3 — Point the Worker at the custom domain (scripted)

Once step 2 resolves, add the route to `wrangler.jsonc`:

```jsonc
{
  "name": "azimuth-ev",
  "compatibility_date": "2026-09-16",
  "observability": { "enabled": true },
  "assets": { "directory": "dist_ev" },
  "routes": [
    { "pattern": "ev.digitalabbot.io", "custom_domain": true }
  ]
}
```

then redeploy:

```bash
npx wrangler deploy --config C:/Dev/naj-market-pulse/wrangler.jsonc
```

Wrangler creates the DNS record in the new zone itself. **Do not add this route before step 2
resolves** — the deploy fails if the zone is not in the account, and that failure looks like a
credentials problem rather than a DNS one.

## Step 4 — Verify it serves before locking it (scripted)

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://ev.digitalabbot.io
```

Expect `200` and the map. Confirm this works **before** step 5, so that if Access misbehaves you
know the hostname itself was sound.

## Step 5 — Apply Access (Cloudflare Zero Trust dashboard)

1. **Zero Trust** → **Access** → **Applications** → **Add an application** → **Self-hosted**.
2. Application name: `Azimuth EV`. Session duration: 24 hours is reasonable.
3. Public hostname: `ev.digitalabbot.io`.
4. Add a policy:
   - Name: `Allowed people`
   - Action: **Allow**
   - Include → **Emails** → list every address that may open it
     (e.g. `contact@digitalabbot.io`, `k.wilsonqc@outlook.com`)
5. Under **Login methods**, enable **One-time PIN**. That is the email-code flow: the visitor enters
   their address, Cloudflare emails a code, no password exists anywhere. Nothing is stored by us.
6. Save. Free tier covers up to 50 users.

Verify in a private window: `https://ev.digitalabbot.io` should present Cloudflare's login screen,
and only an allowlisted address should get through.

## Step 6 — Close the open door

While `workers_dev` is `true`, `azimuth-ev.digitalchemy.workers.dev` keeps serving the map with **no
login**, and Access on the custom domain does nothing about it. Once step 5 is verified, set:

```jsonc
"workers_dev": false
```

and redeploy. Skipping this leaves the gate standing beside an open door.

---

## What this also settles

Gating the app resolves the outstanding question about republishing DEWA's register publicly. The
data reached us through **test/staging** data.dubai credentials whose terms for public
redistribution were never verified, and the supercharge.info enrichment has **no explicit open
licence** at all. Behind a login the map is no longer a public redistribution of either, which is the
more defensible position until the production credentials request is answered.

Attribution still belongs on the page regardless — OpenChargeMap is CC-BY-SA and OpenStreetMap is
ODbL, and both require it whether the audience is one person or everyone.
