# Kitty

Albert plugin to find and control [kitty](https://sw.kovidgoyal.net/kitty/) tabs via remote control.

- `kitty <filter>`: find tabs and windows by tab title, window title, working directory or running command (e.g. `claude`, `ssh wall-e`). Enter focuses the window. Further actions: new tab, split below, split right or new OS window in that directory, copy the working directory.
- `kitty ssh [user@]<host>`: open an SSH session. Hosts are read from `~/.ssh/config` (including `Include`). The window stays open at a shell if ssh fails.
- `kitty run <cmd>`: run a command, then drop into a shell.
- `kitty ~/path`: open a directory, with completion.

Every launch offers the same choices: new tab (default), split below, split right or new OS window. Splits need the `splits` layout. The plugin can also run as a global query handler, but then the active tab shows up twice if the KDE Bridge windows plugin is enabled.

Multiple kitty instances are supported. New tabs open in the most recently focused instance, or a new kitty is started if none is reachable.

## Setup

Clone into `~/.local/share/albert/python/plugins/kitty` and add to `kitty.conf`, then restart kitty:

```
allow_remote_control yes
listen_on unix:@kitty-{kitty_pid}
```

Instances are discovered via their abstract sockets in `/proc/net/unix` (Linux only). The socket prefix can be changed in the plugin settings.

On KDE Plasma (Wayland) `kitty @ focus-window` only switches the tab, since KWin's focus stealing prevention ignores the raise request. The plugin therefore activates the kitty OS window through a KWin script over D-Bus (`qdbus6`). On other desktops only the tab is switched.
