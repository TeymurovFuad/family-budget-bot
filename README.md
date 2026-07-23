# Budget Bot

Personal finance assistant. Tracks expenses in an Excel file and sends
weekly/monthly reports to Telegram. Supports local storage, Google Cloud
Storage, and Amazon S3 as storage backends.

📐 **[Architecture & data flow diagrams →](docs/architecture.md)**

---

## Navigation

The bot has a persistent bottom menu with three buttons:

| Button | What it does |
|---|---|
| ➕ Add | Opens the add-transaction flow — type a description or send a photo of a receipt |
| 📊 Reports | Opens the reports menu — summary, budget, chart, savings, and more |
| ⚙️ More | Settings and utilities — display currency, rates refresh, export |

Each button opens its respective command flow without typing a slash command.

### Reports submenu

| Button | What it does |
|---|---|
| 📅 Summary | Monthly summary (income, expenses, savings, net) |
| 📆 Week | Last 7 days expenses by category |
| 💰 Budget | Budget vs actual for this month |
| 🏆 Top | Top 5 expenses this month |
| 💾 Savings | Savings rate chart (last 6 months) |
| 📋 Report | Full monthly report with category breakdown |
| 📊 Chart | Horizontal bar chart of expenses vs budget |
| 📅 Range | Date-range report — choose This month, Last month, Last 3/6 months, This year, or Custom |

### More submenu

| Button | What it does |
|---|---|
| 💱 Rates | Show current exchange rates from Excel |
| 🔄 Rates Refresh | Fetch live rates from frankfurter.dev and update Excel |
| ✏️ Edit Last | Edit the most recent transaction |

### Bulk import

`/bulk` — import many transactions at once from a photo, a CSV/XLSX bank
statement, a plain-text (`.txt`) file, or pasted text. The AI extracts every
transaction, auto-validates the results against the Lists sheet, and shows an
editable preview before anything is written. Send `save` (or `/save`) to store
the batch, `cancel` to discard. Unfinished drafts are kept per user — run
`/bulk` again to resume after a timeout or bot restart.

CSV/XLSX statements use **saved profiles**: the first upload from a new bank
format triggers one AI call to map the columns (sample data is masked); you
confirm and name the profile, and every later statement with the same columns
parses instantly with zero AI calls. Profiles live on the bot's disk only —
no bank names or account details in the repo.

---

## Quick start (one command)

Fork the repo, clone it, run the setup script. It checks your Python version,
creates the virtualenv, installs dependencies, asks for any missing config
(bot token, allowed Telegram IDs, optional DeepSeek key), validates the
result, and on Linux offers to install the systemd service.

**Requirements:** Python 3.12+, Git

```bash
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot
./setup.sh                       # Windows: python scripts\setup_bot.py
```

Re-run it any time — it acts as a config doctor and only prompts for values
that are still missing.

---

## Quick start (manual, no Docker)

The same steps done by hand.

**Requirements:** Python 3.12+, Git

```bash
# 1. Clone and enter the repo
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot

# 2. Create and activate a virtual environment
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies (--prefer-binary avoids C++ compiler errors on Windows)
pip install -r requirements.txt --prefer-binary

# 4. Create your .env file
cp .env.example .env
```

Edit `.env` and fill in at minimum:
```
TELEGRAM_BOT_TOKEN=your_token_here
ALLOWED_TELEGRAM_IDS=your_telegram_user_id
STORAGE_BACKEND=local
XLSX_PATH=data/Expenses_Improved.xlsx
DISPLAY_CURRENCY=PLN
TIMEZONE=Europe/Warsaw
```

If `data/Expenses_Improved.xlsx` does not exist, the bot will create it automatically from the repository template at `data/Expenses_Template.xlsx`.

```bash
# 5. Create the data directory (the bot will create the Excel file automatically)
mkdir data

# 6. Run the bot
python bot.py
```

The bot polls Telegram — no public IP or port forwarding needed.
Press `Ctrl+C` to stop.

---

## Quick start (Docker)

**Requirements:** Docker Desktop (or Docker Engine on Linux)

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot

# 2. Create your .env file
cp .env.example .env
# Edit .env with your values (see the local quick-start section above)

# 3. Create the data directory for local storage
mkdir data

# 4. Build the image
docker build -t budget-bot .

# 5. Run the container
docker run -d \
  --name budget-bot \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  --restart unless-stopped \
  budget-bot
```

**To view logs:**
```bash
docker logs -f budget-bot
```

**To stop:**
```bash
docker stop budget-bot
```

**To update (after pulling new code):**
```bash
docker stop budget-bot && docker rm budget-bot
docker build -t budget-bot .
docker run -d --name budget-bot --env-file .env -v "$(pwd)/data:/app/data" --restart unless-stopped budget-bot
```

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

## Where does everything run?

Three pieces, each with a different job:

| Piece | Where it runs | What it does |
|---|---|---|
| **Excel file** | Google Cloud Storage | Permanent storage. Never committed to GitHub. |
| **Scheduled reports** | GitHub Actions (free) | Reads from GCS on a schedule. Sends weekly/monthly reports to Telegram. |
| **Interactive bot** | Your phone (Termux) | Always-on. Handles `/add`, `/summary`, `/budget` etc. Reads and writes GCS. |

**You do not host the bot in GCS.** GCS is only for storing the Excel file.
GitHub runs the scheduled reports. Your phone runs the interactive bot.

---

## Hosting the interactive bot on your phone (Termux)

Termux turns your Android device into a full-featured Linux terminal, allowing you to run Python, Git, and use tools like tmux — all on mobile.

**This works well** for a personal bot because:
- The bot uses Telegram polling (pulls messages) — no public IP needed
- Python + pandas uses ~150MB RAM — fine on any modern phone
- Your phone is already always on and connected

**The one real risk:** Android aggressively kills background processes to save battery. You need to disable battery optimisation for Termux specifically, or Android will silently terminate the bot when the screen is off.

### Step-by-step: run the bot on Android

**Step 1 — Install Termux**

Install from **F-Droid**, not the Play Store.
The Play Store version does not work correctly.

F-Droid: https://f-droid.org/packages/com.termux/

**Step 2 — First-time Termux setup**

Open Termux and run these commands one by one:

```bash
pkg update && pkg upgrade
pkg install python git
pip install python-telegram-bot openpyxl pandas python-dotenv google-cloud-storage apscheduler httpx
```

Allow Termux to access phone storage (needed to put your Excel file somewhere you can also open it):
```bash
termux-setup-storage
```

**Step 3 — Prevent Android from killing the bot**

This is the most important step. Without it, Android will kill Termux within minutes of the screen going off.

1. Go to Android **Settings → Apps → Termux → Battery**
2. Select **"Unrestricted"** (not "Optimised", not "Restricted")
3. On some phones (Samsung, Xiaomi, Huawei): also go to **Settings → Battery → Background app management** and exclude Termux

If your phone brand is known for aggressive battery killing, check:
**https://dontkillmyapp.com** — find your phone brand and follow the specific instructions.

**Step 4 — Copy the bot to your phone**

```bash
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot
cp .env.example .env
nano .env
```

Fill in `.env`:
```
TELEGRAM_BOT_TOKEN=your_token_here
ALLOWED_TELEGRAM_IDS=your_telegram_id_here
GCS_BUCKET_NAME=your_bucket_name
GCS_KEY_JSON=paste_full_json_key_content_here
DISPLAY_CURRENCY=PLN
TIMEZONE=Europe/Warsaw
```

For `GCS_KEY_JSON`: paste the entire contents of your service account JSON key file as one line. It starts with `{"type": "service_account",...`.

**Step 5 — Run the bot**

```bash
python bot.py
```

You should see `Bot starting — polling` in the terminal. Open Telegram and send `/start` to your bot.

**Step 6 — Keep it running after closing Termux**

Use `tmux` so the bot survives you closing the Termux app:

```bash
pkg install tmux
tmux new -s bot
python bot.py
# Press Ctrl+B, then D to detach (bot keeps running)
# To come back: tmux attach -t bot
```

**Step 7 — Auto-start on phone reboot (optional)**

Install Termux:Boot from F-Droid: https://f-droid.org/packages/com.termux.boot/

Create the boot script:
```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/budget-bot
tmux new-session -d -s bot "python bot.py"
EOF
chmod +x ~/.termux/boot/start-bot.sh
```

Now the bot starts automatically whenever your phone reboots, in the background, without you doing anything.

---

## Upload the Excel file to Google Cloud Storage

### First-time upload

**Step 1 — Create a Google account and go to Google Cloud**

Go to https://console.cloud.google.com — sign in with your Google/Gmail account.

**Step 2 — Create a project**

1. Click the project selector at the top of the page (next to "Google Cloud")
2. Click **New Project**
3. Name it `budget-tracker` (or anything you want)
4. Click **Create**
5. Wait a few seconds, then select it from the project selector

**Step 3 — Enable Cloud Storage**

1. In the left menu: **Cloud Storage → Buckets**
2. Click **Create bucket**
3. Fill in the form:
   - **Name**: must be globally unique, e.g. `your-bucket-name`
   - **Region**: choose **us-central1** (important — this is in the Always Free zone)
   - **Storage class**: Standard
   - **Access control**: leave as default (Uniform)
4. Click **Create**

**Step 4 — Upload your Excel file**

1. Click your new bucket name to open it
2. Click **Upload files**
3. Select `Expenses_Improved.xlsx` from your computer
4. Wait for the upload to finish — you will see the file listed in the bucket

**Step 5 — Create a service account (the bot's login credential)**

1. In the left menu: **IAM & Admin → Service Accounts**
2. Click **Create service account**
3. Name: `budget-bot`, click **Create and continue**
4. Role: search for and select **Storage Object Admin**
5. Click **Continue**, then **Done**

**Step 6 — Download the service account key**

1. Click your new `budget-bot` service account in the list
2. Go to the **Keys** tab
3. Click **Add key → Create new key**
4. Choose **JSON**
5. Click **Create** — a `.json` file downloads automatically
6. Keep this file safe — it is the password that lets the bot access your bucket

---

## Updating the Excel file later

### From Telegram
Use `/add` — the bot updates GCS directly. Nothing else needed.

### From your computer
Run the sync script (needs `XLSX_PATH` and `GCS_BUCKET_NAME` set in your shell):

```bash
export XLSX_PATH="$HOME/Documents/Expenses_Improved.xlsx"
export GCS_BUCKET_NAME="your-bucket-name"
export GCS_KEY_JSON="$(cat /path/to/service-account-key.json)"
./scripts/sync_data.sh
```

### From the Google Cloud Console
Go to https://console.cloud.google.com → Cloud Storage → your bucket → click the file → **Delete**, then **Upload files** with the new version.

---

## Set up scheduled reports (GitHub Actions)

This runs the weekly and monthly reports automatically. Free.

**Step 1 — Push the code to a private GitHub repo**

```bash
git init
git add .
git commit -m "Initial setup"
# Create a private repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/budget-bot.git
git push -u origin main
```

Note: the Excel file does **not** go in the repo. It stays in GCS.

**Step 2 — Add GitHub Secrets**

Go to your repo on GitHub → **Settings → Secrets and variables → Actions → New repository secret**

Add each of these:

| Secret name | What to put |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather |
| `ALLOWED_TELEGRAM_IDS` | Your Telegram user ID (from @userinfobot) |
| `GCS_BUCKET_NAME` | Your bucket name, e.g. `your-bucket-name` |
| `GCS_KEY_JSON` | Open the downloaded JSON key file in a text editor, select all, paste the entire content here |

**Step 3 — Add a GitHub Variable (optional)**

Go to **Settings → Secrets and variables → Actions → Variables tab → New repository variable**

| Variable | Value |
|---|---|
| `DISPLAY_CURRENCY` | `PLN` (or `EUR`, `AZN` etc.) |

**Step 4 — Test it**

Go to your repo → **Actions tab** → click **Weekly Budget Report** → click **Run workflow** → click the green **Run workflow** button.

Wait about 30 seconds. You should receive a Telegram message.

**What runs automatically after this:**
- Every Sunday at 17:00 UTC → weekly check-in
- 1st of every month at 07:00 UTC → closed month summary
- 1st of January at 17:00 UTC → yearly summary

Every time you push code to `main`, the next scheduled run uses the updated code automatically.

---

## Environment variables reference

| Variable | Used by | Required | Default |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | bot + reports | ✅ | — |
| `ALLOWED_TELEGRAM_IDS` | bot + reports | ✅ | — |
| `GCS_BUCKET_NAME` | bot + reports | for GCS | — |
| `GCS_KEY_JSON` | bot + reports | for GCS | — |
| `GCS_OBJECT_NAME` | bot + reports | — | `Expenses_Improved.xlsx` |
| `XLSX_PATH` | local mode only | — | `data/Expenses_Improved.xlsx` |
| `DISPLAY_CURRENCY` | bot + reports | — | `PLN` |
| `TIMEZONE` | bot + reports | — | `Europe/Warsaw` |
| `BUDGET_CYCLE` | bot | — | `0` — set to `1` to enable salary-period cycle tracking and cycle-aware `/summary` output |

If `GCS_BUCKET_NAME` is not set, both scripts fall back to reading a local file at `XLSX_PATH`.
This means local development works without any GCS setup at all.

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

---

## Cost summary

| Service | Cost |
|---|---|
| Google Cloud Storage (5 GB free, US regions) | **$0.00** |
| GitHub Actions (scheduled reports) | **$0.00** |
| Running bot on your Android phone | **$0.00** |
| **Total** | **$0.00** |

---

## Hosting on Oracle Cloud (free forever, always-on)

Oracle's Always Free tier includes a real ARM Linux VM with 4 CPU cores and
24 GB RAM — far more than the bot needs. It runs 24/7 at no cost, forever.

The bot runs on the VM. The Excel file can be stored either on the VM's local
disk or in Oracle Object Storage (S3-compatible, also free).

**Recommended for Oracle:** use local disk. The VM is always on, the file is
right there, no cloud storage needed. Simpler than GCS.

### Configure the bot for Oracle VM with local disk

In your `.env` on the VM:
```
STORAGE_BACKEND=local
XLSX_PATH=/home/ubuntu/budget-bot/data/Expenses_Improved.xlsx

TELEGRAM_BOT_TOKEN=your_token
ALLOWED_TELEGRAM_IDS=your_id
DISPLAY_CURRENCY=PLN
TIMEZONE=Europe/Warsaw
```

That is the entire config. No cloud storage credentials needed.

### Configure the bot for Oracle Object Storage (optional)

If you want the scheduled GitHub Actions reports to also read from Oracle,
use Oracle Object Storage with the S3-compatible API.

1. In Oracle Cloud Console → Object Storage → Create Bucket
2. Go to your profile → Customer Secret Keys → Generate Secret Key
   Copy the access key and secret key shown (you only see the secret once)
3. Find your namespace: Object Storage → Bucket → copy the namespace from the URL
   or from Settings → Tenancy

In your `.env`:
```
STORAGE_BACKEND=s3
S3_BUCKET_NAME=your-bucket-name
S3_OBJECT_NAME=Expenses_Improved.xlsx
S3_ENDPOINT_URL=https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
S3_REGION=eu-frankfurt-1
```

Oracle region names: `us-ashburn-1`, `us-phoenix-1`, `eu-frankfurt-1`,
`eu-amsterdam-1`, `ap-tokyo-1`, `ap-sydney-1`.

### Network configuration (VCN / Security List)

The bot uses Telegram **long polling** — it only makes outbound HTTPS requests
(to `api.telegram.org`, `api.deepseek.com`, GitHub). It never listens on a port,
so no inbound port needs to be opened and no domain/TLS/webhook setup is required.

When creating the instance:

1. Use the default VCN with a **public subnet** (the wizard's default) — you
   need a public IP for SSH and outbound internet access.
2. Security List ingress: keep only the default **SSH (TCP 22)** rule.
   If your home IP is stable, restrict the source from `0.0.0.0/0` to
   `YOUR_IP/32` for tighter security.
3. Security List egress: leave the default **allow all** — the bot needs
   outbound 443.
4. Do **not** add ingress rules for 80/443/8443 — nothing listens on the VM.

**Oracle-specific trap:** Oracle's Ubuntu images ship with restrictive
iptables rules baked into the OS (a REJECT rule after the SSH allow). Inbound
that's fine (you want nothing inbound), and outbound is allowed by default —
so for this bot you normally don't touch iptables at all. But if some future
service on the VM is unreachable despite a correct Security List rule, check
`sudo iptables -L` before blaming the VCN.

Verify connectivity after first login:
```bash
curl -s https://api.telegram.org > /dev/null && echo telegram OK
curl -s https://api.deepseek.com > /dev/null && echo deepseek OK
```

**Important when migrating:** only ONE bot instance may write the Excel file.
When the Oracle bot is live, stop the bot on your old machine — two instances
polling the same token also fight over Telegram updates (Conflict errors),
and two writers on separate copies of the file lose data.

### Run the bot on Oracle VM

After SSHing into the VM and cloning the repo:

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git tmux
git clone https://github.com/YOUR_USERNAME/budget-bot.git
cd budget-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # fill in values
```

Copy your Excel file to the VM:
```bash
# From your local machine:
scp Expenses_Improved.xlsx ubuntu@YOUR_VM_IP:~/budget-bot/data/
```

Start the bot in tmux (survives SSH disconnects):
```bash
tmux new -s bot
source venv/bin/activate
python bot.py
# Ctrl+B then D to detach
```

Auto-start on VM reboot with systemd:
```bash
sudo nano /etc/systemd/system/budget-bot.service
```

Paste this (adjust paths if your username isn't ubuntu):
```ini
[Unit]
Description=Budget Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/budget-bot
ExecStart=/home/ubuntu/budget-bot/venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/budget-bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable budget-bot
sudo systemctl start budget-bot
sudo systemctl status budget-bot    # should show "active (running)"
```

Push new code → SSH in → `git pull && sudo systemctl restart budget-bot`.

### Host and forget: self-updating timer (recommended)

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
update, e.g. `🔄 Bot updated (commit 68331e3 -> 4ad94e9)` followed by a bullet
list of merged PR titles (extracted from commit subjects between the old and
new commit, matched by GitHub's squash-merge suffix `(#<PR number>)` — this
repo is squash-merge-only, so each PR lands as one commit whose subject is
`<PR title> (#<PR number>)`; do not include the PR number yourself in the
title, GitHub appends it once at merge time). If no subjects match that
pattern (e.g. a non-PR push), it falls back to the plain "Bot updated" line
with no bullets. This notification is best-effort and sent via a direct `curl` call
to the Telegram Bot API (not through the bot process) — if it fails, it's
logged but never blocks or rolls back the update/restart that already
happened.

---

## Storage backend comparison

| Backend | Config | Cost | Best for |
|---|---|---|---|
| Local disk | `STORAGE_BACKEND=local` | $0 | Phone (Termux), Oracle VM, any server |
| GCS | `STORAGE_BACKEND=gcs` | $0 | When GitHub Actions also needs to read the file |
| Oracle Object Storage | `STORAGE_BACKEND=s3` + Oracle endpoint | $0 | Oracle VM + GitHub Actions sharing same file |
| Cloudflare R2 | `STORAGE_BACKEND=s3` + R2 endpoint | $0 | Very fast, no egress fees |
| AWS S3 | `STORAGE_BACKEND=s3` (no endpoint) | ~$0.02/mo | Already using AWS |

The bot does not care which backend is active. Switching backends is one line
in `.env`. No code changes needed.

---

## Auto-deploy from GitHub to Oracle VM

Pushing to GitHub can automatically pull and restart the bot on the VM.

Create `.github/workflows/deploy.yml`:
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

Add these GitHub Secrets:
- `VM_HOST` — your Oracle VM's public IP address
- `VM_SSH_KEY` — contents of a **dedicated deploy key**, never your personal key.
  Generate one: `ssh-keygen -t ed25519 -f ~/.ssh/budget_deploy -N ""`, add the .pub
  to the VM's `~/.ssh/authorized_keys`, paste the private part here (`cat ~/.ssh/budget_deploy`)

Now every `git push` to `main` automatically deploys to the VM.

---

## Auto-deploy with Docker (push code → server updates itself)

This is the "push to GitHub and forget" setup. Every time you change code
and push to `main`, GitHub automatically builds a new Docker image and
deploys it to your server. You never SSH in manually.

### How it works

```
You: git push
       ↓
GitHub Actions: builds Docker image → pushes to Docker Hub
       ↓ (automatic, triggered by successful build)
GitHub Actions: SSHes into your server → pulls new image → restarts container
       ↓
Your server: running the new version
```

### Step 1 — Create a Docker Hub account and repository

1. Go to https://hub.docker.com and sign up (free)
2. Click **Create repository**
   - Name: `budget-bot`
   - Visibility: **Private** (free tier includes 1 private repo)
3. Go to **Account Settings → Security → New Access Token**
   - Description: `github-actions`
   - Permissions: Read & Write
   - Copy the token — you only see it once

### Step 2 — Add Docker secrets to GitHub

Go to your repo → Settings → Secrets and variables → Actions

Add these secrets:

| Secret | Value |
|---|---|
| `DOCKER_USERNAME` | Your Docker Hub username |
| `DOCKER_TOKEN` | The access token from Step 1 |

### Step 3 — Add server secrets to GitHub

These tell GitHub where your server is and how to SSH into it.

| Secret | Value |
|---|---|
| `SERVER_HOST` | Your server's public IP address |
| `SERVER_USER` | SSH username (`ubuntu` for Oracle, `root` for most VPS) |
| `SERVER_SSH_KEY` | A dedicated deploy key's private part (see `VM_SSH_KEY` above — never paste your personal `id_rsa`) |

### Step 4 — Prepare the server

SSH into your server once to set it up. After this you never need to SSH again.

**Install Docker:**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for the group change to take effect
```

**Create the env file** (this is where your secrets live on the server — not in the image):
```bash
nano ~/budget-bot.env
```

Paste your environment variables — same as your `.env` file:
```
TELEGRAM_BOT_TOKEN=your_token
ALLOWED_TELEGRAM_IDS=your_id
STORAGE_BACKEND=local
XLSX_PATH=/app/data/Expenses_Improved.xlsx
DISPLAY_CURRENCY=PLN
TIMEZONE=Europe/Warsaw
```

**Copy your Excel file to the server:**
```bash
# Run this from your local machine:
scp Expenses_Improved.xlsx ubuntu@YOUR_SERVER_IP:~/data/
```

**Log in to Docker Hub on the server** (so it can pull your private image):
```bash
docker login
# Enter your Docker Hub username and access token
```

### Step 5 — Push code to trigger first deploy

```bash
git add .
git commit -m "Add Docker deploy"
git push
```

GitHub runs two workflows automatically:
1. **Build and Push** — builds the image and pushes to Docker Hub (~2 min)
2. **Deploy** — SSHes into your server and restarts the container (~30 sec)

Check progress in your repo → Actions tab.

### What happens on every future push

You change something in the root directory or `requirements.txt`, push to `main`:
- New image built and pushed to Docker Hub
- Server pulls new image and restarts the bot
- Zero downtime between stop and start (Telegram bot recovers from brief gaps automatically — it's just polling)

Pushing only the Excel data file (`data/`) does **not** trigger a rebuild — the workflow only watches the root directory, `requirements.txt`, and `Dockerfile`.

---

## Docker Hub vs GitHub Container Registry (GHCR)

Both work. The difference:

| | Docker Hub | GitHub Container Registry (GHCR) |
|---|---|---|
| Free private repos | 1 | Unlimited |
| Pull limits | 100 per 6 hours (free) | None for your own images |
| Setup | Separate account needed | Uses your GitHub account |
| Where images live | hub.docker.com | ghcr.io |

**GHCR is the better free option** since it's already tied to your GitHub account and has no pull limits. To use it instead of Docker Hub, change the workflow tags from:
```
${{ secrets.DOCKER_USERNAME }}/budget-bot:latest
```
to:
```
ghcr.io/${{ github.repository_owner }}/budget-bot:latest
```
And replace the login step with:
```yaml
- uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}   # automatic, no setup needed
```
`GITHUB_TOKEN` is provided automatically by GitHub Actions — no secret to add.
