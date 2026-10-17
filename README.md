# Kitty

Albert plugin to find and control [kitty](https://sw.kovidgoyal.net/kitty/) tabs, search their scrollback and open SSH sessions via kitty's remote control.

Default trigger: `kitty `. Every result carries the kitty icon with a small badge for its kind.

Terms: an *OS window* is a top-level window, a *tab* lives in it, and a *pane* is a split inside a tab (kitty calls panes "windows").

## OS windows

`kitty` alone lists the kitty OS windows as `w1`, `w2`, … most recently focused first, followed by all tabs. An instance (one kitty process, one socket) can own several OS windows and several instances can run; the entry is named after the window's active tab, as KWin shows it, and tells the active tab's layout and pane count.

Tab completes the input to `kitty w1 `, which lists only that window's tabs; `kitty w1 <filter>` searches within it.

Actions: focus, open a new tab or a new pane / split in it, switch the active tab to one of the enabled layouts.

<!-- ![OS windows](screenshots/os-windows.png) -->

## Tabs

`kitty <filter>` finds tabs and panes by tab title, pane title, working directory or running command, e.g. `claude` or `ssh wall-e`. Enter focuses the pane and raises the window, Tab completes the filter to the pane title.

Actions: focus, copy the last command or its output (needs kitty's shell integration, not offered while a full screen program like vi or htop runs), copy the screen, open or copy the working directory, give the tab a random color from the Nord palette or reset it. New tabs opened by the plugin can get a random color too (setting, off by default).

Panes and tabs can be named, which makes them easier to find. A pane's title is set by the program in it (shells put the working directory there); override it with `kitten @ set-window-title <name>` inside the pane or map a key, e.g. `map ctrl+f3 set_window_title`. A tab's title is its active pane's title unless you set one: kitty's default shortcut is `ctrl+shift+alt+t` (`set_tab_title`), remap it with e.g. `map f2 set_tab_title`, or run `kitten @ set-tab-title <name>` inside the tab.

<!-- ![Tabs](screenshots/tabs.png) -->

## Find

`kitty find <text>` searches the scrollback of every pane. Results show the matching line with pane, tab and line number, newest first. Enter focuses the pane and opens its scrollback in a `less` overlay at the last match, like kitty's own show_scrollback; `q` closes it. The other action copies the line.

<!-- ![Find](screenshots/find.png) -->

## SSH

`kitty ssh [user@]<host>` opens an SSH session in the window you are working in: in a new tab, in a split (or a new pane, depending on the tab's layout) or in a new OS window. Hosts come from `~/.ssh/config` including `Include`, unknown hosts are accepted as typed. The window is titled after the host, so `kitty <host>` finds the session again, gets a red active border while connected and stays at a shell prompt if the command fails.

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

Instances are discovered via their abstract sockets in `/proc/net/unix` (Linux only). Raising the OS window on focus works out of the box on X11. On KDE Plasma (Wayland) KWin's focus stealing prevention ignores kitty's raise request, so the plugin activates the window through a KWin script over D-Bus (`qdbus6`) there. On other Wayland compositors only the tab is switched. Splits need the `splits` layout; the plugin assumes kitty's defaults otherwise and needs no custom keybindings.

## Settings

- Abstract socket prefix (`kitty-`)
- SSH command line, `%1` is the host (`kitten ssh %1`)
- Active border color of SSH windows (`#cc2222`)
- Give new tabs a random color (off)
