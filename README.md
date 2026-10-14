<div align="center">

![silo — many accounts, any history, every agent CLI sandboxed with bubblewrap](assets/banner-v2.png)

**One Python file. Accounts and histories mixed freely. Every agent CLI in its own bubblewrap sandbox.**

[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-0.6.0-blue)](https://github.com/flinner/silo/blob/main/silo)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Sandbox](https://img.shields.io/badge/sandbox-bubblewrap-orange)](https://github.com/containers/bubblewrap)
[![Platform](https://img.shields.io/badge/platform-linux-lightgrey)](#limitations)
[![No sudo](https://img.shields.io/badge/sudo-never-red)](#why)

[Install](#install) ·
[Quick start](#quick-start) ·
[Commands](#commands) ·
[Configuration](#configuration) ·
[Brokers](#brokered-access-ssh-gpg-gh) ·
[How it works](#how-it-works) ·
[Limitations](#limitations)

</div>

---

```console
$ silo ls -a
  Tool      Profile    Login                      Account              Background
  claude    main       main                       me@university.edu    daemon running
  claude    work       work                       me@company.com       -
  claude    research   main                       me@university.edu    -
  codex     main       main                       me@example.org       -
  codex     scratch    scratch (not logged in)    -                    -

$ silo work                     # claude, logged in as work, sandboxed
$ silo main --bg 'fix CI'       # a background agent on the other account, at the same time
$ silo work --login main -c     # continue work's conversation on the main account
$ silo-codex main               # codex, same sandbox rules
```

**A profile is a history; a login is an account.** Each profile is a separate
`CLAUDE_CONFIG_DIR` / `CODEX_HOME` holding its sessions, so any number run
side by side. Logins are stored apart from profiles and picked independently:
several profiles can share one login, and one profile's history can be
continued under any login (handy when an account hits its limit). Every run is wrapped in [bubblewrap](https://github.com/containers/bubblewrap):

- your home is **empty** — only the working directory, the profile and paths
  you choose exist, plus your tools and git identity read-only;
- logins, other profiles and secrets are **never there**, not even read-only;
- `ssh`, `gpg` and `gh` work, but through **brokers on the host**: the agent
  uses your keys and tokens without ever being able to read them.

## Why?

Agent CLIs run arbitrary shell commands with your full user rights, and
juggling accounts means copying credential files around. `silo` fixes both
with no root, no containers and no system service:

| | |
|---|---|
| **No sudo, ever** | Unprivileged user namespaces via `bwrap`. Nothing to install system-wide beyond the packages below. |
| **Accounts side by side** | One config dir per profile, any login per run. `silo work` and `silo main` run concurrently; claude sessions in different profiles can still list and message each other. |
| **Empty home** | The sandbox starts from an empty home. You map back what the agent needs; everything else, from browser profiles to `~/.aws`, simply isn't there. |
| **Brokered keys** | `ssh`/`scp`/`git push` to hosts you allow, `gpg` signing through your agent, allowlisted `gh` subcommands with your token — none of the secrets enter the sandbox. |
| **Polite by default** | Runs at `nice 10` and idle IO priority; an optional memory cap (a systemd user scope) covers the agent and everything it spawns. |
| **Long-lived agents work** | Background agents (`--bg`), their daemon and Remote Control keep working across runs. |
| **Any CLI** | claude and codex are built in; another agent CLI is one table entry. |

## Install

`silo` is one file. Download it, read it if you like, and put it on your `PATH`:

```bash
curl -fLo ~/.local/bin/silo https://raw.githubusercontent.com/flinner/silo/main/silo
chmod +x ~/.local/bin/silo
ln -s silo ~/.local/bin/silo-codex      # optional: codex by default
```

Or keep a git checkout and update with `git pull`:

```bash
git clone https://github.com/flinner/silo ~/.local/share/silo
ln -s ~/.local/share/silo/silo ~/.local/bin/silo
```

Requirements: Linux, `bwrap`, Python 3.9+ with `click`, `rich` and
`prompt_toolkit` (silo tells you if one is missing):

```bash
sudo pacman -S bubblewrap python-click python-rich python-prompt_toolkit          # Arch
sudo apt install bubblewrap python3-click python3-rich python3-prompt-toolkit    # Debian/Ubuntu
sudo dnf install bubblewrap python3-click python3-rich python3-prompt-toolkit    # Fedora
```

**Updates.** `silo check-update` tells you when a newer version exists and
`silo update` installs it in place, after checking the download compiles
(a git checkout is told to `git pull` instead).
Normal commands check at most once a day — configurable with
`check_updates = "ask" | "always" | "never"` (`ask` only prints a hint,
`always` installs, `never` stays offline).

## Quick start

```bash
silo init                     # onboarding: logins, filesystem, brokers, limits, updates
silo ls -a                    # see the profiles
silo new work                 # a fresh profile, with its own login 'work' ...
silo work auth login          # ... logged in (codex: silo-codex work login)
silo work                     # run claude as 'work'
silo new research --login main      # another history on an existing login
silo work --login main              # this run only: work's history, main's account
silo login use work main            # from now on
silo status -a                      # 5h / weekly / per-model limits of every login
```

```console
$ silo status -a
main claude  me@university.edu
  5h        ▀▀▀▀▀▀▀▀▀▀▀▀▀▀  29%  slow -22%               2h 27m
  7d        ▀▀▀▀▀▀▀▀▀▀▀▀▀▀  80%  fast +64% · out in 1d   5d 19h
  7d Opus   ▀▀▀▀▀▀▀▀▀▀▀▀▀▀ 100%  used up                 5d 19h
main codex  me@example.org
  5h        ▀▀▀▀▀▀▀▀▀▀▀▀▀▀   0%  new window              4h 59m
  7d        ▀▀▀▀▀▀▀▀▀▀▀▀▀▀  12%  on pace                 5d 23h
bars: top = used, bottom = time gone
```

Each bar is two in one row of half blocks: the top half (green, yellow, red)
is how much you have used, the bottom half (grey) how much of the window has
passed — a top bar running ahead of the bottom one means you are fast.
The pace column compares the two (within 10
points is "on pace") and, when you are fast, says when the limit runs out at
your average rate so far. One heading per login and a bar that shrinks with the
terminal keep it readable in a narrow window. Answers are cached for a minute;
when the endpoint rate-limits, the last answer is shown with its age.

`status` asks the same endpoints claude's `/usage` and codex's limit display
use. It never refreshes a token (that would race the tool's own refresh); an
expired one says so, and the next run of any profile with that login renews it.

`silo init` walks through six steps: **logins** (if claude or codex is logged
in, import it as a login, with a profile of the same name if none exists), **filesystem** (extra writable and read-only paths,
your PATH tools, git config), **brokered access** (ssh key and allowed hosts,
gpg, gh), **hidden paths**, **resources** (nice, IO priority, memory) and
**updates** (whether to check automatically). Tab completes paths, keys and
hosts; Enter keeps the current answer; bad answers are asked again. Change a
single setting later with `silo config KEY VALUE`.

silo refuses to run from your home directory itself, since the working
directory is mounted read-write. Run it from a project directory.

## Commands

| Command | Does |
|---|---|
| `init` | Interactive onboarding; writes `~/.config/silo/config.json` |
| `config [KEY [VALUE...]]` | Show all settings, read one, or set one (`--add` / `--drop` for lists, `--unset`, `--edit`) |
| `ls [-a]` | Profiles of the selected tool (`-a`: all tools) with login, account and background-daemon state |
| `new NAME [--login L] [--current]` | Create a profile using login `L` (default: `NAME`); `--current` imports this machine's current login as it |
| `rm NAME [-y]` | Delete a profile, stopping its background agents and ssh broker first; its login is kept |
| `login [ls [-a]]` | Logins, their accounts and the profiles that default to them |
| `login add NAME [--current]` | Create an empty login (log in with `silo PROFILE --login NAME auth login`), or import the current one |
| `login use PROFILE LOGIN` | Make `LOGIN` the default login of `PROFILE` |
| `status [-a]` | Usage limits of every login: 5-hour, weekly and per-model windows, how much is used and when each resets |
| `login rm NAME [-y]` | Delete a login (refused while a profile defaults to it) |
| `NAME [--login L] [ARGS...]` | Run the tool as profile `NAME` (with login `L` for this run); every other flag passes through (`silo work -c`, `silo work --bg '...'`) |
| `NAME --shell` | A shell inside `NAME`'s sandbox, to see exactly what the agent sees |
| `check-update` / `update` | Check for / install a newer silo |
| `-t, --tool claude\|codex` | Choose the tool (default: claude; `silo-codex` defaults to codex) |

## Configuration

`~/.config/silo/config.json`, written by `silo init` and `silo config`:

```console
$ silo config nice 5
✓ nice = 5
$ silo config writable --add ~/data
✓ writable = ~/code/tmp, ~/data
$ silo config memory_max --unset
$ silo config --edit              # or open the JSON in $EDITOR
```


```json
{
  "config_version": "1.2",
  "silo_min_version": "0.6.0",
  "writable": ["~/code/tmp"],
  "readable": ["~/datasets"],
  "path_dirs": true,
  "git_config": true,
  "gpg": true,
  "brokered": {"gh": ["pr", "issue", "run list", "run view", "repo view"]},
  "hidden": ["~/.config/gh", "~/.git-credentials", "~/.netrc", "~/.gnupg", "~/.aws"],
  "ssh_keys": ["id_ed25519", "id_work"],
  "ssh_config": true,
  "ssh_hosts": ["mycluster", "*.lab.example.org"],
  "nice": 10,
  "ionice": "idle",
  "memory_max": "8G",
  "swap_max": "0",
  "check_updates": "ask",
  "logins": {"claude/research": "main"}
}
```

| Key | Default | Meaning |
|---|---|---|
| `writable` | `[]` | Extra read-write paths (the cwd and the profile always are) |
| `readable` | `[]` | Extra read-only paths |
| `path_dirs` | `true` | Expose the `PATH` directories under your home (your installed tools), read-only |
| `git_config` | `true` | Expose `~/.gitconfig` and `~/.config/git`, read-only |
| `gpg` | `false` | Sign/decrypt through your gpg-agent's restricted socket |
| `brokered` | `gh`: common subcommands | Commands run on the host, by allowed subcommand prefix |
| `hidden` | common secret paths | Masked even inside mapped paths, on top of every tool's login files |
| `ssh_keys` | `[]` | Keys in `~/.ssh` loaded into the profile's private ssh-agent; empty = no ssh |
| `ssh_config` | `false` | Let brokered ssh use your `~/.ssh/config` (identity lines stripped) |
| `ssh_hosts` | `[]` | Allowed ssh destinations, globs ok; empty = any host |
| `nice` | `10` | CPU niceness, 0 (normal) to 19 (lowest) |
| `ionice` | `idle` | IO priority: `idle` \| `low` \| `normal` |
| `memory_max` | `""` | Memory cap, e.g. `8G` or `50%`; needs a systemd user session, skipped with a warning otherwise |
| `swap_max` | `""` | Swap cap alongside `memory_max`, e.g. `0` |
| `logins` | `{}` | `"tool/profile": login` for profiles not using the login of their own name (`silo login use`) |
| `check_updates` | `ask` | `ask` \| `always` \| `never` |

Environment overrides: `SILO_ROOT` (default `~/.config/silo`), `SILO_SSH_KEYS` (space- or comma-separated).
They apply to one run and are never written to the file.

**Versioned.** The file records `config_version` and `silo_min_version`, the
oldest silo that understands it. An older silo refuses a config that needs a
newer release (and says `silo update`), refuses a newer major config version,
and only warns on a newer minor one. Configs from before versioning load as-is
and are stamped on the next save.

## Brokered access: ssh, gpg, gh

### ssh

Inside the sandbox `~/.ssh` does not exist and `/usr/bin/ssh` is a
dozen-line shim. It hands its arguments and its stdin/stdout/stderr (the actual
file descriptors, so interactive terminals work) to a broker running on the
host, which:

1. **vets the arguments** — refuses `-F`, `-i`, `-E`, `-S`, `-G`, `-J`, `-v`,
   any `-o` outside a small safe list (so no `ProxyCommand` or `LocalCommand`),
   unix-socket forwards, and destinations outside `ssh_hosts`;
2. **runs the real ssh** with a per-profile `ssh-agent` holding only your
   chosen keys (dropping one from the config restarts the agent without it), and optionally your ssh config with every `IdentityFile`,
   `IdentityAgent` and `CertificateFile` line removed;
3. **ties lifetimes together** — if the agent's ssh is killed, the host ssh
   and anything it spawned are killed too.

`scp`, `rsync -e ssh` and `git` over ssh go through the same shim. The private
key never enters the sandbox; the agent can use it only against hosts you allow.

### gpg

With `gpg` on, the profile gets its own `GNUPGHOME` holding **public keys and
ownertrust only**, copied from your keyring on each run. Its agent socket is
your gpg-agent's `extra` socket, the restricted socket gpg provides for
forwarding: it can sign and decrypt, prompts with pinentry **on the host**, and
cannot export or change secret keys. Signed git commits work as usual.

### gh and other commands

`brokered` maps a command to allowed subcommand prefixes. The command's shim
sends its arguments, working directory and terminal to the host broker, which
runs the real `gh` with your login. A call is refused unless it matches a
prefix (`gh pr create` matches `pr`; `gh auth token` and `gh api` match
nothing by default) **and** the working directory is inside the sandbox's
writable paths. The token in `~/.config/gh` is hidden from the sandbox.

Git over **https** has no broker: use ssh remotes (brokered above) or `gh`.

## How it works

```
 host                                           sandbox (bwrap, per run)
┌───────────────────────────────┐            ┌──────────────────────────────────┐
│ silo NAME ...                 │   exec     │ claude / codex                   │
│  · reads config.json          │ ─────────► │  CLAUDE_CONFIG_DIR / CODEX_HOME  │
│  · starts broker + ssh-agent  │            │   = ~/.config/silo/<tool>/NAME   │
│                               │            │                                  │
│ ssh broker (per profile)      │ ◄───────── │ /usr/bin/ssh  = shim             │
│  · vets argv, runs real ssh   │  unix sock │ ~/.ssh        = empty            │
│  · ssh-agent: chosen keys only│  + fds     │ /             = read-only        │
│  · gh with your token         │            │ ~             = empty tmpfs      │
│ $XDG_RUNTIME_DIR (hidden)     │            │ cwd, profile, writable = rw      │
│ host ssh-agent, dbus (hidden) │            │ /tmp = NAME/tmp (persistent)     │
└───────────────────────────────┘            └──────────────────────────────────┘
```

**Profiles.** `~/.config/silo/<tool>/<name>/` is the tool's whole config
directory, minus the login. A new profile copies your settings (`settings.json`,
`config.toml`) and symlinks shared instructions (`CLAUDE.md`, `AGENTS.md`,
skills), so edits to those apply everywhere.

**Logins.** `~/.config/silo/logins/<tool>/<name>/` holds one account: the
credential file (`.credentials.json`, `auth.json`) and, for claude, the
`oauthAccount` record from `.claude.json`. A profile defaults to the login of
its own name; `silo login use` changes that (stored as `logins` in
`config.json`) and `--login` overrides it for one run. The login is chosen
**per sandbox**: silo binds only that login's directory into the run and points
the tool at it — claude through `CLAUDE_SECURESTORAGE_CONFIG_DIR`, which
relocates just its credentials (claude refuses symlinked credentials and
replaces the file by rename, so neither a link nor a file bind would do); codex
through a symlink from the profile's `auth.json`. So one profile can run under
several logins at once, and the other logins stay hidden. silo also writes the
login's account record into the profile's `.claude.json`, saving the previous
one back to its login. Profiles from silo < 0.6 migrate the same way on
their first run: their credentials become the login of the same name.

**Mount layout.** `/` is bound read-only; `/tmp` is the profile's own
persistent directory; `$XDG_RUNTIME_DIR` is replaced by an empty tmpfs (it
holds the host ssh-agent, the session bus and editor/terminal servers — all
ways out); your home is replaced by an empty tmpfs. Mapped back read-only: your
`readable` paths, the `PATH` directories under your home, git config, the
tool's own binary and claude's shared instructions. Mapped back read-write: the
working directory, the profile and your `writable` paths. Finally every login
file and `hidden` path inside anything mapped back is masked. Writes elsewhere
in home land in the tmpfs and vanish when the run ends.

**Resource limits.** `silo` execs `systemd-run --user --scope` (when a memory
limit is set), then `nice` and `ionice`, then `bwrap`. Limits are inherited, so
background agents and every tool the agent runs share the same cap.

**Background agents and Remote Control.** Claude Code's background daemon
listens on a socket under `/tmp`. Because each profile's `/tmp` persists,
`silo work --bg 'task'` keeps running after you exit, and the next
`silo work agents` finds it. Remote Control works unchanged. `silo ls` shows
which profiles have a daemon running.

```bash
silo work agents                    # list background sessions (attach, logs, stop by id)
silo work stop ID                   # stop one session
silo work daemon stop --any         # stop the daemon and all its sessions
silo work daemon stop --any --keep-workers   # stop the daemon, leave sessions running
```

The daemon is started on demand ("transient"), which is why `daemon stop`
needs `--any`. Run these from a project directory like any other silo command.

**The ssh broker** (and the profile's ssh-agent) also run per profile, started
on demand and idle otherwise. `silo rm NAME` stops them; to stop them earlier:

```bash
kill $(cat /run/user/$UID/silo/claude-NAME/broker.pid /run/user/$UID/silo/claude-NAME/agent.pid)
```

They start again on the profile's next run.

**Talking between sessions.** Claude Code discovers peers through a session
registry and sockets, and ignores peers in another PID namespace. silo shares
the registry (`~/.claude/sessions`) and socket directory across all profiles
and keeps the host PID namespace, so sessions of different accounts — and
your unsandboxed claude — can list and message each other.

**Adding a tool.** A tool is one `Tool(...)` entry: binary, the environment
variable that relocates its config, files to copy or link into new profiles,
its login files, and how to read the account email.

## Limitations

- Linux only (bubblewrap); unprivileged user namespaces must be enabled.
- One claude profile can run under several logins at once, but its
  `.claude.json` holds a single account record (email, organization), which
  follows the latest launch; credentials are unaffected. Codex profiles share
  one `auth.json` link, so concurrent codex runs of a profile use the latest
  launch's login.
- The network namespace is shared (agents need the network), so abstract
  unix sockets such as X11's remain reachable.
- Window resizes are not forwarded to brokered interactive ssh sessions.
- Everything under a mapped-back path is visible, so check what your
  `readable`/`writable` paths and the PATH directories under your home contain.
- Git over https has no credential broker; use ssh remotes or `gh`.
- `--shell` must be the only argument after the profile name.

## License

[MIT](LICENSE)
