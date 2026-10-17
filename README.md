# Kitty

Albert plugin to find and control [kitty](https://sw.kovidgoyal.net/kitty/) tabs, search their scrollback and open SSH sessions via kitty's remote control.

Default trigger: `kitty `. Every result carries the kitty icon with a small badge for its kind.

## Windows

`kitty` alone lists the kitty OS windows, most recently focused first. An instance (one kitty process, one socket) can own several OS windows and several instances can run; the entry is named after the window's active tab, as KWin shows it, and tells the active tab's layout and pane count.

Actions: focus, open a new tab or a new window / split in it, switch the active tab to one of the enabled layouts.

<!-- ![Windows](screenshots/windows.png) -->

## Tabs

`kitty <filter>` finds tabs and panes by tab title, window title, working directory or running command, e.g. `claude` or `ssh wall-e`. Enter focuses the pane and raises the window.

Actions: focus, copy the last command or its output (needs kitty's shell integration, not offered while a full screen program like vi or htop runs), copy the screen, open or copy the working directory.

<!-- ![Tabs](screenshots/tabs.png) -->

## Find

`kitty find <text>` searches the scrollback of every pane. Results show the matching line with pane, tab and line number, newest first. Enter focuses the pane and opens its scrollback in a `less` overlay at the last match, like kitty's own show_scrollback; `q` closes it. The other action copies the line.

<!-- ![Find](screenshots/find.png) -->

## SSH

`kitty ssh [user@]<host>` opens an SSH session in the window you are working in: in a new tab, in a split (or a new window of the tab, depending on the tab's layout) or in a new OS window. Hosts come from `~/.ssh/config` including `Include`, unknown hosts are accepted as typed. The window is titled after the host, so `kitty <host>` finds the session again, gets a red active border while connected and stays at a shell prompt if the command fails.

<!-- ![SSH](screenshots/ssh.png) -->

### Compared to Albert's SSH plugin

Albert's own [SSH plugin](https://github.com/albertlauncher/albert-plugin-ssh) opens every connection in a new window of the system terminal. This plugin opens it in the kitty window you are working in. It only reads `~/.ssh/config`, has no remote script option and does not take part in the global query. Keep both: the native plugin for the global query and new windows, `kitty ssh` for tabs.

## Setup

Clone into `~/.local/share/albert/python/plugins/kitty` and add to `kitty.conf`, then restart kitty:

```
allow_remote_control yes
listen_on unix:@kitty-{kitty_pid}
```

Until then the plugin shows a hint whose action copies these two lines to the clipboard.

Instances are discovered via their abstract sockets in `/proc/net/unix` (Linux only). On KDE Plasma (Wayland) `kitty @ focus-window` only switches the tab, since KWin's focus stealing prevention ignores the raise request; the plugin therefore activates the OS window through a KWin script over D-Bus (`qdbus6`). On other desktops only the tab is switched. Splits need the `splits` layout; the plugin assumes kitty's defaults otherwise and needs no custom keybindings.

## Settings

- Abstract socket prefix (`kitty-`)
- SSH command line, `%1` is the host (`kitten ssh %1`)
- Active border color of SSH windows (`#cc2222`)
