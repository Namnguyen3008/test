# V8 administrator action required: enable WSL 2 prerequisites

Observed: 2026-08-03. This is the **only** V8 action document requiring elevation.

`wsl --status` reports that the Windows Subsystem for Linux and Virtual Machine Platform optional components are not
enabled. Codex did not attempt to bypass UAC, modify firmware, or reboot the machine.

Open **PowerShell as Administrator** and run exactly:

```powershell
wsl --install --no-distribution
```

Approve the normal UAC prompt. If Windows requests a restart, restart only when convenient, then return to Codex.
Do not change BIOS/UEFI virtualization settings unless Windows still reports that virtualization is unavailable after
this command and restart.

After restart, in a normal non-admin PowerShell, run:

```powershell
wsl --update
wsl --set-default-version 2
wsl --status
```

Docker Desktop may be installed only after this prerequisite is healthy. Its official Winget package and SHA-256 will
be rechecked at install time; if its standard installer displays UAC, approve it only if you intend to install Docker
Desktop for this local VMEC rehearsal.
