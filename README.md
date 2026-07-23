# Budget Bot

Personal finance assistant. Tracks expenses in an Excel file and sends
weekly/monthly reports to Telegram. Supports local storage, Google Cloud
Storage, and Amazon S3-compatible storage backends.

📐 **[Architecture & data flow diagrams →](docs/architecture.md)**
📖 **[Full command reference and Excel/bot documentation →](DOCUMENTATION.md)**

---

## Navigation

The bot has a persistent bottom menu with three buttons:

| Button | What it does |
|---|---|
| ➕ Add | Opens the add-transaction flow — type a description or send a photo of a receipt |
| 📊 Reports | Opens the reports menu — summary, budget, chart, savings, and more |
| ⚙️ More | Settings and utilities — display currency, rates refresh, export |

Each button opens its respective command flow without typing a slash command.
See [DOCUMENTATION.md](DOCUMENTATION.md) for the full command list, including
`/export` (download the live workbook from Telegram) and `/setbudget`
(owner-only — the first ID listed in `ALLOWED_TELEGRAM_IDS` is the primary
user with write access; every other allowed ID is read-only).

### Bulk import

`/bulk` — import many transactions at once from a photo, a CSV/XLSX bank
statement, a plain-text (`.txt`) file, or pasted text. The AI extracts every
transaction, auto-validates the results against the Lists sheet, and shows an
editable preview before anything is written.

CSV/XLSX statements use **saved profiles**: the first upload from a new bank
format triggers one AI call to map the columns (sample data is masked); you
confirm and name the profile, and every later statement with the same columns
parses instantly with zero AI calls. Profiles live on the bot's disk only —
no bank names or account details in the repo. See DOCUMENTATION.md for the
full bulk-import workflow (duplicate detection, editing a preview, drafts).

---

## Recommended: one command, $0/month, self-updating

This is how the bot is actually meant to be run: bootstrap locally with one
script, host it on an Oracle Cloud Free Tier VM (a real always-on Linux box,
free forever), and let a systemd timer pull and restart it automatically
whenever you push to `master`. No Docker, no GitHub secrets, no inbound ports.

**Requirements:** Python 3.12+, Git

### 1. Bootstrap with `setup.sh`

```bash
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot
./setup.sh                       # Windows: python scripts\setup_bot.py
```

The script checks your Python version, creates the virtualenv, installs
dependencies, asks for any missing config (bot token, allowed Telegram IDs,
optional DeepSeek key), validates the result, and — on Linux — offers to
install the systemd service for you. Re-run it any time; it acts as a config
doctor and only prompts for values still missing.

<details>
<summary>What <code>setup.sh</code> does under the hood, for anyone who wants to do it by hand</summary>

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt --prefer-binary
cp .env.example .env                 # then fill in the values below
mkdir -p data
python bot.py
```

Minimum `.env` values:
```
TELEGRAM_BOT_TOKEN=your_token_here
ALLOWED_TELEGRAM_IDS=your_telegram_user_id
STORAGE_BACKEND=local
XLSX_PATH=data/Expenses_Improved.xlsx
DISPLAY_CURRENCY=PLN
TIMEZONE=Europe/Warsaw
```

If `data/Expenses_Improved.xlsx` does not exist, the bot creates it
automatically from the repository template at `data/Expenses_Template.xlsx`.
The bot polls Telegram — no public IP or port forwarding needed. `Ctrl+C` stops it.

</details>

### 2. Host it on an Oracle Cloud Free Tier VM

Oracle's Always Free tier includes a real ARM Linux VM (Ampere A1, up to 4
CPU cores / 24 GB RAM) that runs 24/7 at no cost, forever — far more than
this bot needs.

**Recommended storage:** local disk. The VM is always on and the file is
right there — no cloud storage credentials needed.

```
STORAGE_BACKEND=local
XLSX_PATH=/home/ubuntu/budget-bot/data/Expenses_Improved.xlsx
TELEGRAM_BOT_TOKEN=your_token
ALLOWED_TELEGRAM_IDS=your_id
DISPLAY_CURRENCY=PLN
TIMEZONE=Europe/Warsaw
```

**Network configuration.** The bot uses Telegram **long polling** — outbound
HTTPS only (to `api.telegram.org`, `api.deepseek.com`, GitHub). It never
listens on a port:
- Use the default VCN with a public subnet (needed for SSH).
- Security List ingress: keep only the default SSH (TCP 22) rule — restrict
  the source to `YOUR_IP/32` if your home IP is stable.
- Security List egress: leave the default allow-all.
- Do not open 80/443/8443 — nothing listens on the VM.

**Oracle-specific trap:** Oracle's Ubuntu images ship with a REJECT rule in
`iptables` after the SSH allow. That's fine for this bot (nothing inbound is
needed), but if some future service on the VM is unreachable despite a
correct Security List rule, check `sudo iptables -L` before blaming the VCN.

Verify connectivity after first login:
```bash
curl -s https://api.telegram.org > /dev/null && echo telegram OK
curl -s https://api.deepseek.com > /dev/null && echo deepseek OK
```

**Only one bot instance may write the Excel file.** When the Oracle bot goes
live, stop the bot on any other machine — two instances polling the same
token fight over Telegram updates, and two writers on separate copies of the
file lose data.

SSH in, clone the repo, and run `./setup.sh` (Step 1) on the VM itself. When
it offers to install the systemd service, accept — that gives you
`budget-bot.service`, which keeps the bot running and auto-restarts it on
crash or reboot.

### 3. Auto-update timer (host and forget)

Instead of SSHing in after every push, install the poll-based updater from
`deploy/`. Every 10 minutes it checks whether the tracked branch moved on
GitHub; only then it pulls, installs dependencies, and restarts the bot.
No GitHub secrets, no inbound connections, no Docker required.

```bash
cd ~/budget-bot
chmod +x deploy/auto-update.sh
sudo cp deploy/budget-bot.service deploy/budget-bot-update.service deploy/budget-bot-update.timer /etc/systemd/system/

# allow the updater to restart the bot without a password prompt
echo 'ubuntu ALL=(root) NOPASSWD: /usr/bin/systemctl restart budget-bot' | sudo tee /etc/sudoers.d/budget-bot-update

sudo systemctl daemon-reload
sudo systemctl enable --now budget-bot budget-bot-update.timer

systemctl list-timers budget-bot-update.timer   # verify the timer is scheduled
journalctl -u budget-bot-update -n 20           # see update runs
```

The updater deploys whatever branch is checked out on the VM (`git rev-parse
--abbrev-ref HEAD`) — keep the VM on `master` so only merged PRs go live.
The bot's `.env` and `data/` are untouched by updates (both are gitignored).

After a successful pull + restart, the updater also sends a Telegram message
to the primary owner (the first ID in `ALLOWED_TELEGRAM_IDS`) announcing the
update, e.g. `🔄 Bot updated (commit 68331e3 -> 4ad94e9)` followed by a
bullet list of merged PR titles (extracted from commit subjects between the
old and new commit, matched by GitHub's squash-merge suffix `(#<PR number>)`
— this repo is squash-merge-only, so each PR lands as one commit whose
subject is `<PR title> (#<PR number>)`). If no subjects match that pattern
(e.g. a non-PR push), it falls back to a plain "Bot updated" line with no
bullets. This notification is best-effort, sent via a direct `curl` call to
the Telegram Bot API (not through the bot process) — if it fails, it's
logged but never blocks or rolls back the update/restart that already
happened.

### Cost summary

| Service | Cost |
|---|---|
| Oracle Cloud Free Tier VM (always-on) | **$0.00** |
| Local disk storage | **$0.00** |
| GitHub Actions (scheduled reports, optional) | **$0.00** |
| **Total** | **$0.00** |

---

## Set up scheduled reports (GitHub Actions)

Optional. Runs the weekly and monthly reports automatically, in addition to
the interactive bot, from a schedule instead of a long-running process.

**Step 1 — Push the code to a GitHub repo**

```bash
git init
git add .
git commit -m "Initial setup"
# Create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/budget-bot.git
git push -u origin main
```

Note: the Excel file does **not** go in the repo. If you want GitHub Actions
to read the same file the VM writes to, use a shared cloud storage backend
(GCS or S3-compatible — see below) instead of local disk.

**Step 2 — Add GitHub Secrets**

Go to your repo on GitHub → **Settings → Secrets and variables → Actions →
New repository secret**. Add `TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_IDS`,
and whichever storage credentials match your backend (see
[Environment variables reference](#environment-variables-reference)).

**Step 3 — Add a GitHub Variable (optional)**

**Settings → Secrets and variables → Actions → Variables tab** → add
`DISPLAY_CURRENCY` (e.g. `PLN`, `EUR`, `AZN`).

**Step 4 — Test it**

**Actions tab** → **Weekly Budget Report** → **Run workflow**. Wait about 30
seconds — you should receive a Telegram message.

**What runs automatically after this:**
- Every Sunday at 17:00 UTC → weekly check-in
- 1st of every month at 07:00 UTC → closed month summary
- 1st of January at 17:00 UTC → yearly summary

Every push to `main` updates the code the next scheduled run uses.

---

## Running tests

```bash
# Activate your virtual environment first, then:
pip install -r requirements.txt   # includes pytest and pytest-asyncio
pytest tests/ -v
```

Tests use temporary files — no real data is touched and the temp Excel is
cleaned up automatically after each test.

---

## Environment variables reference

| Variable | Used by | Required | Default |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | bot + reports | ✅ | — |
| `ALLOWED_TELEGRAM_IDS` | bot + reports | ✅ | — (first ID is the primary/owner user — see DOCUMENTATION.md) |
| `GCS_BUCKET_NAME` | bot + reports | for GCS | — |
| `GCS_KEY_JSON` | bot + reports | for GCS | — |
| `GCS_OBJECT_NAME` | bot + reports | — | `Expenses_Improved.xlsx` |
| `XLSX_PATH` | local mode only | — | `data/Expenses_Improved.xlsx` |
| `DISPLAY_CURRENCY` | bot + reports | — | `PLN` |
| `TIMEZONE` | bot + reports | — | `Europe/Warsaw` |
| `BUDGET_CYCLE` | bot | — | `0` — set to `1` to enable salary-period cycle tracking and cycle-aware `/summary` output |

If `GCS_BUCKET_NAME` is not set, both scripts fall back to reading a local
file at `XLSX_PATH`. This means local development works without any GCS
setup at all.

### Storage backend comparison

| Backend | Config | Cost | Best for |
|---|---|---|---|
| Local disk | `STORAGE_BACKEND=local` | $0 | Oracle VM, any always-on server, phone |
| GCS | `STORAGE_BACKEND=gcs` | $0 | When GitHub Actions also needs to read the file |
| Oracle Object Storage | `STORAGE_BACKEND=s3` + Oracle endpoint | $0 | Oracle VM + GitHub Actions sharing the same file |
| Cloudflare R2 | `STORAGE_BACKEND=s3` + R2 endpoint | $0 | Very fast, no egress fees |
| AWS S3 | `STORAGE_BACKEND=s3` (no endpoint) | ~$0.02/mo | Already using AWS |

The bot does not care which backend is active. Switching backends is one
line in `.env`. No code changes needed.

<details>
<summary>Configuring GCS or S3-compatible storage (first-time upload, service account setup)</summary>

**Google Cloud Storage:**

1. [console.cloud.google.com](https://console.cloud.google.com) → create a
   project → **Cloud Storage → Buckets → Create bucket** (region
   `us-central1` is in the Always Free zone; storage class Standard).
2. Upload `Expenses_Improved.xlsx` to the bucket.
3. **IAM & Admin → Service Accounts → Create service account**, role
   **Storage Object Admin**.
4. Open the service account → **Keys → Add key → Create new key → JSON** —
   this downloads the credential the bot uses as `GCS_KEY_JSON`.

**Oracle Object Storage (S3-compatible):**

```
STORAGE_BACKEND=s3
S3_BUCKET_NAME=your-bucket-name
S3_OBJECT_NAME=Expenses_Improved.xlsx
S3_ENDPOINT_URL=https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
S3_REGION=eu-frankfurt-1
```

Get the access/secret key pair from your Oracle profile → **Customer Secret
Keys → Generate Secret Key** (the secret is shown once). Find your namespace
under **Object Storage → Bucket** or **Settings → Tenancy**. Oracle region
names: `us-ashburn-1`, `us-phoenix-1`, `eu-frankfurt-1`, `eu-amsterdam-1`,
`ap-tokyo-1`, `ap-sydney-1`.

**Updating the Excel file from your computer** (any cloud backend), using
the sync script:
```bash
export XLSX_PATH="$HOME/Documents/Expenses_Improved.xlsx"
export GCS_BUCKET_NAME="your-bucket-name"
export GCS_KEY_JSON="$(cat /path/to/service-account-key.json)"
./scripts/sync_data.sh
```

</details>

---

## Excel structure — Lists sheet

The **Lists** sheet in the Excel file controls all reference data. The bot reads it live on every request — no restart needed.

| Column | Content |
|---|---|
| A | Month names (Jan … Dec) |
| B | Transaction Type (Expense, Income, Savings) |
| C | Category (unified list for all transaction types) |
| D | Person |
| E | Year |
| F | _(unused)_ |
| G | _(unused)_ |
| I | Currency code (e.g. `PLN`, `EUR`, `USD`) |
| J | Exchange rate (PLN per 1 unit of the currency) |

> **All lists (categories, currencies, persons, transaction types) are read live from Excel — add/remove values anytime without restarting the bot.**
> Col C is the single source of truth for categories — add any category here and it appears in the bot keyboard and Excel dropdown for all transaction types (Expense, Income, Savings).
> To add a new currency: add a row in columns I:J and it will appear in the AI parser immediately.

See [DOCUMENTATION.md](DOCUMENTATION.md) for the full Excel workbook
reference (sheets, MasterData columns, budget targets, dashboard, currency
system).

---

## Alternative hosting options

The Oracle VM path above is the recommended default. These alternatives are
valid but add complexity (Docker) or a different reliability trade-off
(Termux) — use them if they fit your situation better.

### Docker

**Requirements:** Docker Desktop (or Docker Engine on Linux)

```bash
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot
cp .env.example .env        # fill in values — see Environment variables reference
mkdir data
docker build -t budget-bot .
docker run -d \
  --name budget-bot \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  --restart unless-stopped \
  budget-bot
```

```bash
docker logs -f budget-bot        # view logs
docker stop budget-bot           # stop

# update after pulling new code:
docker stop budget-bot && docker rm budget-bot
docker build -t budget-bot .
docker run -d --name budget-bot --env-file .env -v "$(pwd)/data:/app/data" --restart unless-stopped budget-bot
```

<details>
<summary>Auto-deploy with Docker (push to GitHub → server updates itself)</summary>

Every push to `main` builds a new image and redeploys it to your server —
you never SSH in manually after the initial setup.

```
You: git push
       ↓
GitHub Actions: builds Docker image → pushes to a registry
       ↓ (automatic, triggered by successful build)
GitHub Actions: SSHes into your server → pulls new image → restarts container
       ↓
Your server: running the new version
```

**1. Registry account.** Either Docker Hub (sign up free, create a private
repo, generate an access token under Account Settings → Security) or GitHub
Container Registry (GHCR) — GHCR is the better free option since it's
already tied to your GitHub account, has no pull limits, and needs no
separate login (`${{ secrets.GITHUB_TOKEN }}` is automatic).

| | Docker Hub | GHCR |
|---|---|---|
| Free private repos | 1 | Unlimited |
| Pull limits | 100 per 6 hours (free) | None for your own images |
| Setup | Separate account needed | Uses your GitHub account |

**2. GitHub Secrets** (repo → Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `DOCKER_USERNAME` / `DOCKER_TOKEN` | Only if using Docker Hub |
| `SERVER_HOST` | Your server's public IP |
| `SERVER_USER` | SSH username (`ubuntu` for Oracle, `root` for most VPS) |
| `SERVER_SSH_KEY` | A **dedicated deploy key**'s private part — never your personal key. Generate: `ssh-keygen -t ed25519 -f ~/.ssh/budget_deploy -N ""`, add the `.pub` to the server's `~/.ssh/authorized_keys` |

**3. Prepare the server** (once):
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out and back in after this
nano ~/budget-bot.env           # paste your env vars, same as .env
scp Expenses_Improved.xlsx ubuntu@YOUR_SERVER_IP:~/data/
docker login                    # or the GHCR equivalent, so it can pull the private image
```

**4. Add a `deploy.yml` workflow** that builds on push and SSHes in to pull
+ restart. Pushing only `data/` does not trigger a rebuild if the workflow
scopes its `paths` to the root directory, `requirements.txt`, and
`Dockerfile`.

</details>

<details>
<summary>Auto-deploy without Docker (git pull over SSH)</summary>

If you'd rather skip images entirely, a workflow can SSH into the VM and run
`git pull` + restart directly:

```yaml
name: Deploy to Oracle VM

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Pull and restart on VM
        uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.VM_HOST }}
          username: ubuntu
          key:      ${{ secrets.VM_SSH_KEY }}
          script: |
            cd ~/budget-bot
            git pull
            source venv/bin/activate
            pip install -r requirements.txt -q
            sudo systemctl restart budget-bot
```

Add `VM_HOST` (the VM's public IP) and `VM_SSH_KEY` (a dedicated deploy
key's private part — see above) as GitHub Secrets. This is what the
auto-update timer (recommended path, above) replaces — prefer the timer
unless you specifically want deploys triggered by GitHub instead of polled
from the VM.

</details>

### Termux (run the bot on your Android phone)

Termux turns your Android device into a full-featured Linux terminal. This
works for a personal bot because Telegram polling needs no public IP, and
Python + pandas uses ~150MB RAM — fine on any modern phone. **The real
risk:** Android aggressively kills background processes to save battery, so
you must disable battery optimisation for Termux specifically or the bot
gets silently terminated when the screen is off.

<details>
<summary>Step-by-step Termux setup</summary>

**1. Install Termux** from [F-Droid](https://f-droid.org/packages/com.termux/)
— not the Play Store version, which does not work correctly.

**2. First-time setup:**
```bash
pkg update && pkg upgrade
pkg install python git
pip install python-telegram-bot openpyxl pandas python-dotenv google-cloud-storage apscheduler httpx
termux-setup-storage
```

**3. Prevent Android from killing the bot** (the most important step):
- **Settings → Apps → Termux → Battery → Unrestricted**
- On Samsung/Xiaomi/Huawei: also exclude Termux under **Settings → Battery →
  Background app management**
- Check [dontkillmyapp.com](https://dontkillmyapp.com) for your phone brand

**4. Copy the bot to your phone:**
```bash
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot
cp .env.example .env
nano .env
```
Since a phone has no fixed local disk you'd share elsewhere, use GCS
(`GCS_BUCKET_NAME` + `GCS_KEY_JSON`) instead of `STORAGE_BACKEND=local`.

**5. Run it:**
```bash
python bot.py
```
You should see `Bot starting — polling`. Send `/start` to your bot on
Telegram.

**6. Keep it running after closing Termux, with `tmux`:**
```bash
pkg install tmux
tmux new -s bot
python bot.py
# Ctrl+B, then D to detach (bot keeps running)
# tmux attach -t bot to come back
```

**7. Auto-start on reboot (optional):** install
[Termux:Boot](https://f-droid.org/packages/com.termux.boot/), then:
```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/budget-bot
tmux new-session -d -s bot "python bot.py"
EOF
chmod +x ~/.termux/boot/start-bot.sh
```

</details>

---

## Where does everything run?

If you split the interactive bot and the scheduled reports across two
places (e.g. Oracle VM + GitHub Actions), remember:

| Piece | Where it runs | What it does |
|---|---|---|
| **Excel file** | Local disk (Oracle VM) or cloud storage (GCS/S3-compatible) | Permanent storage. Never committed to GitHub. |
| **Scheduled reports** (optional) | GitHub Actions (free) | Reads the shared storage on a schedule. Sends weekly/monthly reports to Telegram. |
| **Interactive bot** | Oracle VM (recommended), or Docker/Termux (alternatives) | Always-on. Handles `/add`, `/summary`, `/budget` etc. |

If everything runs on the Oracle VM with local disk, GitHub Actions is
unnecessary — the interactive bot's own scheduled-report job covers the
same weekly/monthly sends.
