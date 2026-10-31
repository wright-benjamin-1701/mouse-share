# mouse-share Runbook

Setup, installation, and auto-start guide for Linux, macOS, and Windows.

## Prerequisites

- **Python 3.12+** installed
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — fast Python package manager
- **Git**

---

## 1. Clone and Install

### All platforms

```bash
git clone https://github.com/YOUR_USER/mouse-share.git
cd mouse-share
```

### Linux

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install with Linux extras
uv sync --extra linux --extra dev

# Verify
uv run mouse-share
```

**Permissions for input capture** (needed for evdev/uinput backends):

```bash
# Add yourself to the input group (log out and back in after)
sudo usermod -aG input $USER

# Or use udev rules for uinput access
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
```

### macOS

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install with macOS extras
uv sync --extra macos --extra dev

# Verify
uv run mouse-share
```

**Permissions**: macOS will prompt for Accessibility access on first run.
Go to **System Settings > Privacy & Security > Accessibility** and enable mouse-share.

### Windows

```powershell
# Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Create venv and install (no extra deps needed — uses ctypes)
uv sync --extra dev

# Verify
uv run mouse-share
```

---

## 2. Running

### Manual start

```bash
uv run mouse-share
```

### Development mode (with tests)

```bash
# Run tests
uv run python -m pytest tests/unit/ -v

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/
```

---

## 3. Auto-Start on Boot

### Linux (systemd user service)

Create the service file:

```bash
mkdir -p ~/.config/systemd/user
```

```bash
cat > ~/.config/systemd/user/mouse-share.service << 'EOF'
[Unit]
Description=mouse-share — keyboard/mouse sharing
After=network-online.target graphical-session.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/Documents/GitHub/mouse-share/.venv/bin/mouse-share
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0

[Install]
WantedBy=default.target
EOF
```

> **Note**: Adjust `ExecStart` to match your clone location. `%h` expands to
> your home directory. If you installed globally with `uv tool install`, use
> `ExecStart=%h/.local/bin/mouse-share` instead.

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable mouse-share.service
systemctl --user start mouse-share.service
```

Check status:

```bash
systemctl --user status mouse-share.service
journalctl --user -u mouse-share.service -f
```

Stop / disable:

```bash
systemctl --user stop mouse-share.service
systemctl --user disable mouse-share.service
```

### macOS (launchd)

Create the plist:

```bash
cat > ~/Library/LaunchAgents/com.local.mouse-share.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.mouse-share</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USER/Documents/GitHub/mouse-share/.venv/bin/mouse-share</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/mouse-share.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/mouse-share-error.log</string>
</dict>
</plist>
EOF
```

> **Note**: Replace `YOUR_USER` with your macOS username, and adjust the path
> to match your clone location. If installed globally: use
> `/Users/YOUR_USER/.local/bin/mouse-share`.

Load and start:

```bash
launchctl load ~/Library/LaunchAgents/com.local.mouse-share.plist
```

Check status:

```bash
launchctl list | grep mouse-share
cat /tmp/mouse-share.log
```

Stop / unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.local.mouse-share.plist
```

### Windows (Task Scheduler)

Open PowerShell as your normal user and run:

```powershell
$MouseShareExe = "$env:USERPROFILE\Documents\GitHub\mouse-share\.venv\Scripts\mouse-share.exe"

$Action   = New-ScheduledTaskAction -Execute $MouseShareExe
$Trigger  = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan)

Register-ScheduledTask `
    -TaskName "mouse-share" `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "mouse-share - keyboard/mouse sharing" `
    -Force
```

> **Note**: Adjust `$MouseShareExe` if your clone is in a different location.
> If installed globally with `uv tool install`, use
> `$env:USERPROFILE\.local\bin\mouse-share.exe`.

Check status:

```powershell
schtasks /query /tn "mouse-share"
```

Remove:

```powershell
Unregister-ScheduledTask -TaskName "mouse-share" -Confirm:$false
```

---

## 4. Network Setup

mouse-share communicates over your LAN. Both machines need:

| Port  | Protocol | Purpose           |
|-------|----------|-------------------|
| 24800 | TCP      | Control channel   |
| 24801 | UDP      | Input events      |
| 24802 | UDP      | Link probing      |

### Firewall rules

**Linux (ufw)**:

```bash
sudo ufw allow 24800:24802/tcp
sudo ufw allow 24800:24802/udp
```

**Linux (firewalld)**:

```bash
sudo firewall-cmd --permanent --add-port=24800-24802/tcp
sudo firewall-cmd --permanent --add-port=24800-24802/udp
sudo firewall-cmd --reload
```

**macOS**: The firewall prompt should appear on first run. Click "Allow".

**Windows**: A Windows Firewall prompt should appear on first run. Click
"Allow access". If it doesn't, add manually:

```powershell
New-NetFirewallRule -DisplayName "mouse-share TCP" -Direction Inbound -Protocol TCP -LocalPort 24800-24802 -Action Allow
New-NetFirewallRule -DisplayName "mouse-share UDP" -Direction Inbound -Protocol UDP -LocalPort 24800-24802 -Action Allow
```

### Optimal performance

For lowest latency on a dedicated ethernet link, mouse-share auto-detects the
fastest NIC between two peers (see `net/link_selector.py`). To get the best
results:

- Connect both machines with a direct ethernet cable or through a gigabit switch
- Ensure both machines have static IPs or reliable DHCP on the LAN
- The link prober runs automatically during handshake — no manual config needed

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: mouse_share` | Run from the project dir with `uv run`, or `uv sync` first |
| `Permission denied` on Linux evdev | Add yourself to the `input` group (see above) |
| macOS blocks input capture | Enable Accessibility in System Settings |
| High latency | Check that traffic is on ethernet, not Wi-Fi (`ip route get <peer_ip>`) |
| Firewall blocking | Open ports 24800-24802 TCP+UDP (see above) |
| Service won't start | Check logs: `journalctl --user -u mouse-share` (Linux) or `/tmp/mouse-share.log` (macOS) |
