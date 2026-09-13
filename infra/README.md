# Running the bot on AWS (on demand)

The bot only needs to run during events, so we don't keep a server around. Two
buttons in the GitHub **Actions** tab handle it:

| Workflow | What it does |
|---|---|
| **Start bot** | Creates a small AWS Lightsail server, installs the bot, starts it, and prints the webhook URL. |
| **Stop bot** | Saves `records.db` to S3 (optional), then deletes the server so billing stops. |

```
Start bot:  GitHub Actions ──terraform apply──▶ Lightsail server ──ansible──▶ bot running (systemd)
Stop bot:   GitHub Actions ──copy records.db──▶ S3 backup bucket ──terraform destroy──▶ server gone
```

**What's in this folder**

| Path | Purpose |
|---|---|
| `terraform/` | Describes the server: Lightsail instance, SSH key, firewall. |
| `ansible/` | Describes what goes *on* the server: uv, the bot code, `config.ini`, a systemd service. |
| `bootstrap/` | One-time creation of the two S3 buckets (Terraform state + database backups). |
| `../.github/workflows/bot-start.yml`, `bot-stop.yml` | The two buttons. |
| `../.github/workflows/infra-checks.yml` | Validates the Terraform/Ansible files on every PR. |

**Cost:** the `nano` Lightsail plan is about $5/month, billed by the hour, so a
weekend event costs well under $1. The S3 buckets cost a few cents a month.
Nothing else is billed while the bot is stopped.

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

### 4. Add GitHub secrets

In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | from step 2 |
| `AWS_SECRET_ACCESS_KEY` | from step 2 |
| `SSH_PRIVATE_KEY` | entire contents of `ohio-bot-deploy`, including the `-----BEGIN/END-----` lines |
| `SSH_PUBLIC_KEY` | contents of `ohio-bot-deploy.pub` |
| `CONFIG_INI` | entire contents of the bot's `config.ini` (get it from the tech lead) |

To change the bot's config later, edit the `CONFIG_INI` secret and run **Start bot** again.

---

## Running an event

### Start

1. Go to **Actions → Start bot → Run workflow**.
2. Leave `ref` as `main`, unless you want a different branch.
3. Leave **Restore** unticked for a new event. Tick it only to bring back the
   data from the last **Stop**, for example after restarting mid-event.
4. Wait about 5 minutes. The run's **Summary** page shows the server IP and **webhook URL**.
5. Put the webhook URL into the registration/intake system. **It changes every time you run Start.**

To check that the webhook is reachable, send a request with a wrong key. You should get `401`:

```bash
curl -i -X POST http://<SERVER_IP>:<PORT>/post/user -H "api-key: wrong" -H "Content-Type: application/json" -d "{}"
```

### Stop

1. Go to **Actions → Stop bot → Run workflow**.
2. Leave **backup** ticked unless you're sure you don't need the data.
3. When the run finishes, open the **Lightsail console** and confirm there are no instances.

If the backup step fails (for example, the server is broken), the server is **not** deleted,
so nothing is lost. Fix the problem, or re-run with backup unticked if you don't need the data.

### Deploying a code change mid-event

Run **Start bot** again. It reuses the existing server: it pulls the new code,
restarts the bot, and keeps `records.db`.

---

## Troubleshooting

**The workflow failed.** Open the failed step. Common causes:
- `CONFIG_INI secret is missing`: step 4 above.
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
Lightsail console, or just run **Stop bot**. It's safe to run even when nothing exists.

---

## Known limitations

- **The webhook is plain HTTP**, so the `api-key` is sent unencrypted. Fixing this
  needs a domain name plus HTTPS (for example with Caddy).
- `start.py` runs the bot and the webhook as two child processes. If only one of
  them crashes, the service stays "running" and systemd won't restart it. Check
  the logs if the bot goes quiet but the webhook still responds.
- Backups in the S3 bucket contain participant names and emails. Delete old ones
  once they're no longer needed.
- The GitHub deploy user has long-lived access keys. GitHub OIDC could replace
  them later so no keys need to be stored.
