# Running the bot on AWS (on demand)

The bot only needs to run during events, so we don't keep servers around. Two
buttons in the GitHub **Actions** tab manage an independent deployment for each event:

| Workflow | What it does |
|---|---|
| **Start bot** | Creates a small AWS Lightsail server, installs the bot, starts it, and prints the webhook URL. |
| **Stop bot** | Saves `records.db` to S3 (optional), then deletes the server so billing stops. |

```
Start bot:  GitHub Actions ──terraform apply──▶ event's Lightsail server ──ansible──▶ bot running
Stop bot:   GitHub Actions ──copy records.db──▶ event's S3 prefix ──terraform destroy──▶ server gone
```

**What's in this folder**

| Path | Purpose |
|---|---|
| `terraform/` | Describes the server: Lightsail instance, SSH key, firewall. |
| `ansible/` | Describes what goes *on* the server: uv, the bot code, `config.ini`, a systemd service. |
| `bootstrap/` | One-time creation of the two S3 buckets (Terraform state + database backups). |
| `../.github/workflows/bot-start.yml`, `bot-stop.yml` | The two buttons. |
| `../.github/workflows/infra-checks.yml` | Validates the Terraform/Ansible files on every PR. |

Each event gets its own Terraform state, Lightsail server, configuration, database,
backup prefix, and webhook URL. The state and backup S3 buckets are shared safely.

**Cost:** each `nano` Lightsail server is about $5/month, billed by the hour, so a
weekend event costs well under $1. The S3 buckets cost a few cents a month.
Nothing else is billed while all bots are stopped.

---

## One-time setup

You only do this once for the OHI/O AWS account and GitHub repo.

### 1. Create the S3 buckets

Find the AWS account ID (top-right menu in the AWS console, 12 digits). Then either:

**Option A: AWS console** (no tools needed). Go to **S3 → Create bucket**, region
**US East (Ohio) us-east-2**, and create:

- `ohio-discord-bot-tfstate-<ACCOUNT_ID>`: leave "Block all public access" on, set **Bucket Versioning: Enable**
- `ohio-discord-bot-backups-<ACCOUNT_ID>`: leave "Block all public access" on

**Option B: Terraform**, if you have Terraform and the AWS CLI logged in as an admin:

```bash
cd infra/bootstrap
terraform init
terraform apply
```

The names must match exactly, because the workflows compute them from the account ID.

### 2. Create a deploy user for GitHub

In **IAM → Policies → Create policy → JSON**, paste this (replace `ACCOUNT_ID` in 4 places)
and name it `ohio-discord-bot-deploy`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "Lightsail", "Effect": "Allow", "Action": "lightsail:*", "Resource": "*" },
    { "Sid": "WhoAmI", "Effect": "Allow", "Action": "sts:GetCallerIdentity", "Resource": "*" },
    {
      "Sid": "ListBuckets",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": [
        "arn:aws:s3:::ohio-discord-bot-tfstate-ACCOUNT_ID",
        "arn:aws:s3:::ohio-discord-bot-backups-ACCOUNT_ID"
      ]
    },
    {
      "Sid": "ReadWriteObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::ohio-discord-bot-tfstate-ACCOUNT_ID/*",
        "arn:aws:s3:::ohio-discord-bot-backups-ACCOUNT_ID/*"
      ]
    }
  ]
}
```

Then go to **IAM → Users → Create user**, name it `ohio-bot-deployer`, choose
**Attach policies directly**, and pick `ohio-discord-bot-deploy`. Open the user →
**Security credentials → Create access key → "Application running outside AWS"**.
Keep the key ID and secret for step 4.

### 3. Make an SSH key

The workflows use this key to log in to the server. In PowerShell or Git Bash:

```bash
ssh-keygen -t ed25519 -C ohio-bot-deploy -f ohio-bot-deploy
```

Press Enter twice for no passphrase. This creates `ohio-bot-deploy` (private)
and `ohio-bot-deploy.pub` (public). Once both are saved as secrets you can
delete the files.

### 4. Add GitHub secrets and event environments

In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**:

| Repository secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | from step 2 |
| `AWS_SECRET_ACCESS_KEY` | from step 2 |
| `SSH_PRIVATE_KEY` | entire contents of `ohio-bot-deploy`, including the `-----BEGIN/END-----` lines |
| `SSH_PUBLIC_KEY` | contents of `ohio-bot-deploy.pub` |

Then go to **Settings → Environments** and create one environment per event. Use a
short lowercase name containing only letters, numbers, and hyphens, such as
`hackohio-2026` or `makeohio-2026`. In each environment, add an environment secret:

| Environment secret | Value |
|---|---|
| `CONFIG_INI` | that event's bot token, Discord IDs, webhook key, and other configuration |

The webhook key must be at least 32 characters. Generate one with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. Rotate any key
that was previously sent over the old plain-HTTP endpoint.

The workflows present these environments as the event choices. Delete any old
repository-level `CONFIG_INI` secret so a missing environment secret cannot silently
fall back to the wrong event's configuration. To change one event's config, update
its `CONFIG_INI` secret and run **Start bot** for that event again.

---

## Running an event

### Start

1. Go to **Actions → Start bot → Run workflow**.
2. Select the event's GitHub environment.
3. Leave `ref` as `main`, unless you want a different branch.
4. Leave **Restore** unticked for a new event. Tick it only to use an existing
   S3 backup for that event.
5. Wait about 5 minutes. The run's **Summary** page shows the server IP and **webhook URL**.
6. Put the webhook URL into that event's registration/intake system. **It changes whenever its server is recreated.**

To check that the webhook is reachable, send a request with a wrong key. You should get `401`:

```bash
curl -i -X POST https://<SERVER_IP>/post/user -H "api-key: wrong" -H "Content-Type: application/json" -d "{}"
```

For outage and certificate alerts, configure an external monitor to request
`https://<SERVER_IP>/health` every five minutes and alert unless it receives
HTTP `200` with `{"status":"ready"}`. The endpoint returns HTTP `503` until
Discord login and command synchronization complete. Update the monitor whenever
the workflow reports a new server IP.

### Stop

1. Go to **Actions → Stop bot → Run workflow**.
2. Select the event's GitHub environment.
3. When the run finishes, open the **Lightsail console** and confirm that event's instance is stopped.

The instance and its database are preserved. Lightsail can continue charging for
stopped instances; delete one manually only when its data is no longer needed.

### Deploying a code change mid-event

Run **Start bot** again with the same event name. It reuses that event's existing
server: it pulls the new code, restarts the bot, and keeps `records.db`.

---

## Troubleshooting

**The workflow failed.** Open the failed step. Common causes:
- `CONFIG_INI secret is missing`: the selected GitHub environment does not have the secret from step 4.
- `AccessDenied` or `NoSuchBucket`: the bucket names or IAM policy don't match the account ID (steps 1 and 2).
- Ansible `UNREACHABLE`: the server is still booting. Re-run **Start bot**.

**The bot is offline in Discord.** SSH in and look at the logs:

```bash
ssh -i ohio-bot-deploy ubuntu@<SERVER_IP>
sudo systemctl status ohio-bot
sudo journalctl -u ohio-bot -n 100 --no-pager
```

On the server, the bot lives in `/opt/ohio-discord-bot` and runs as the `bot` user.
To restart it: `sudo systemctl restart ohio-bot`.

**I'm not sure if something is still running and costing money.** Check the
Lightsail console. Instances are named `ohio-discord-bot-<event>`. **Stop bot** only
stops the event name entered in that workflow run.

---

## Known limitations

- HTTPS uses a short-lived Let's Encrypt certificate for the server's public IP.
  Caddy renews it automatically; if webhook TLS fails, inspect
  `sudo journalctl -u caddy -n 100 --no-pager`.
- `start.py` runs the bot and webhook as two child processes. If either exits,
  the launcher stops the sibling and exits so systemd restarts the service.
- Backups in the S3 bucket contain participant names and emails. Delete old ones
  once they're no longer needed.
- The GitHub deploy user has long-lived access keys. GitHub OIDC could replace
  them later so no keys need to be stored.
