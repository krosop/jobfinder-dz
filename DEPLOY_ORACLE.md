# Deploying 24/7 on an Oracle Cloud Always Free VPS

This runs the **whole system** — responsive Telegram bot (wizard + commands)
**and** the 06:00 daily refresh — on a free VM. Your PC can be off forever.

> Free tier reality check (verified 2026-09-30): Ampere A1 ARM VMs are Always
> Free (now **2 OCPU / 12 GB** after Oracle's 2026 cut — plenty: our stack
> idles under 1 GB). ARM instances in busy regions often say "Out of
> capacity" — retry at different hours; it clears. Oracle reclaims **idle**
> Always-Free VMs; our bot polls Telegram continuously, which counts as
> activity, but see the keep-alive note at the bottom.

## 0. Prerequisites (one-time, ~10 min)

1. Oracle Cloud account: <https://www.oracle.com/cloud/free/> (needs a card
   for verification; it is NOT charged on Always Free resources)
2. Note your **home region** — Always Free A1 capacity is per-region and
   cannot be changed later.

## 1. Create the VM (console → Compute → Instances → Create)

- Name: `jobfinderdz`
- Image: **Ubuntu 24.04** (aarch64)
- Shape: **Ampere A1 Flex** — 2 OCPU, 12 GB (or 1 OCPU / 6 GB; both free)
- Boot volume: default 47 GB is fine
- SSH keys: add your public key (generate with `ssh-keygen -t ed25519` on
  your PC if you don't have one; paste `~/.ssh/id_ed25519.pub`)
- Create → wait for RUNNING → note the **Public IP address**

## 2. Open nothing (security)

The bot only makes **outbound** HTTPS calls. Default Oracle security list
already allows SSH (port 22) for your setup; no inbound ports need opening.
Do NOT open 8080/80 — nothing listens.

## 3. Install Docker on the VM (2 min)

```bash
ssh ubuntu@<PUBLIC_IP>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu     # log out/in once after this
```

## 4. Get the code onto the VM

On your PC (private repo → use HTTPS with a token, or your SSH key):

```bash
cd "C:/Users/hboaz/Documents/test bot/laya-jobs"
git remote add vps ubuntu@<PUBLIC_IP>:~/jobfinderdz.git
# simplest: clone from GitHub on the VM instead (private repo → gh or token)
```

On the VM (recommended path — clone from your private GitHub repo):

```bash
git clone https://github.com/krosop/jobfinderdz.git jobfinderdz
cd jobfinderdz
# auth once: git credential or a fine-grained PAT when prompted
```

## 5. Configure + launch

```bash
cp .env.example .env
nano .env        # TELEGRAM_TOKEN=...  TELEGRAM_CHAT_ID=1643138088
docker compose up -d --build
docker compose logs -f        # should print "polling as @jobfinderDZBOT"
```

Message the bot on Telegram — it answers **from the VM now**. `Ctrl+C`
leaves the logs (container keeps running).

## 6. What the container does

- Long-polls Telegram 24/7 → wizard, /city, /digest, all commands respond
- Built-in thread fires the full harvest + digests at **06:00 Algeria time**
- `restart: unless-stopped` → survives crashes **and VM reboots**
- `data/` volume persists `jobs.db` (NEW/REMAINING continuity)

## 7. Operations cheat-sheet

```bash
docker compose logs --tail 50      # recent activity
docker compose restart             # after changing .env
docker compose up -d --build       # after git pull (updates)
docker compose down                # stop
```

Update the code later:

```bash
git pull && docker compose up -d --build
```

## 8. Keep-alive (important on Always Free)

Oracle may email you about idle instances. Our bot is never idle (continuous
polling + daily harvests), but for belt-and-braces you can add a tiny
CPU/heartbeat service or simply use the VM for one more small project. If
you ever get a reclaim warning, `docker compose restart` + some traffic is
enough to reset the meter.

## 9. Cost

**0 €/month.** Bandwidth outbound ≤ 10 TB/mo free; our traffic is megabytes.
