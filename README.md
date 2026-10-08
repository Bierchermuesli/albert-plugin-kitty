# Kitty

Albert plugin to find and control [kitty](https://sw.kovidgoyal.net/kitty/) tabs via remote control.

- Global query: find tabs and windows by tab title, window title, working directory or running command (e.g. `claude`, `ssh wall-e`). Enter focuses the window. Further actions: open a new tab in the same directory, copy the working directory.
- `kitty ssh <host>`: open an SSH session in a new tab. Hosts are read from `~/.ssh/config` (including `Include`).
- `kitty run <cmd>`: run a command in a new tab.
- `kitty ~/path`: open a new tab in a directory, with completion.

Multiple kitty instances are supported. New tabs open in the most recently focused instance, or a new kitty is started if none is reachable.

## Setup

Clone into `~/.local/share/albert/python/plugins/kitty` and add to `kitty.conf`, then restart kitty:

```
allow_remote_control yes
listen_on unix:@kitty-{kitty_pid}
```

Instances are discovered via their abstract sockets in `/proc/net/unix` (Linux only). The socket prefix can be changed in the plugin settings.
