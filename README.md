# Kitty

Albert plugin to find and control [kitty](https://sw.kovidgoyal.net/kitty/) tabs and open SSH sessions via remote control.

- `kitty`: list the kitty OS windows with their tabs and the active tab's layout. Actions: focus, open a new tab or window in it, switch the active tab to one of the enabled layouts.
- `kitty <filter>`: find tabs and windows by tab title, window title, working directory or running command (e.g. `claude`, `ssh wall-e`). Enter focuses the window. Other actions: copy the last command's output (needs kitty's shell integration) or the screen, open or copy the working directory.
- `kitty ssh [user@]<host>`: open an SSH session. Hosts are read from `~/.ssh/config` (including `Include`). The SSH command line is configurable (default `kitten ssh %1`), the window is titled after the host and can get its own active border color while connected. It stays open at a shell if ssh fails.

ssh offers the same choices: in new tab (default), in a new window of the current tab or in a new OS window. If the current tab uses the `splits` layout, the window choice becomes split below / split right. The plugin assumes kitty's defaults otherwise and needs no custom keybindings. The plugin can also run as a global query handler, but then the active tab shows up twice if the KDE Bridge windows plugin is enabled.

Multiple kitty instances are supported. New tabs open in the most recently focused instance, or a new kitty is started if none is reachable.

## Compared to Albert's SSH plugin

Albert's own [SSH plugin](https://github.com/albertlauncher/albert-plugin-ssh) opens every connection in a new window of the system terminal. This plugin opens it in the kitty window you are working in, as a tab or a split, and names the window after the host so you find the session again with `kitty <host>`. It only reads `~/.ssh/config`, has no remote script option and does not take part in the global query. Keep both: the native plugin for the global query and new windows, `kitty ssh` for tabs.

## Setup

Clone into `~/.local/share/albert/python/plugins/kitty` and add to `kitty.conf`, then restart kitty:

```
allow_remote_control yes
listen_on unix:@kitty-{kitty_pid}
```

Instances are discovered via their abstract sockets in `/proc/net/unix` (Linux only). The socket prefix can be changed in the plugin settings.

On KDE Plasma (Wayland) `kitty @ focus-window` only switches the tab, since KWin's focus stealing prevention ignores the raise request. The plugin therefore activates the kitty OS window through a KWin script over D-Bus (`qdbus6`). On other desktops only the tab is switched.
