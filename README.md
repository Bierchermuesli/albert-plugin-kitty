# Kitty

Albert plugin to find and control [kitty](https://sw.kovidgoyal.net/kitty/) tabs, search their scrollback and open SSH sessions via kitty's remote control.

Default trigger: `kitty `. The icon shows the kind of result:
- the kitty icon for an OS window
- a tab for a tab
- a terminal for a pane
- a plug for an SSH host
- a magnifier for a scrollback match

Terms: an *OS window* is a top-level window, a *tab* lives in it, and a *pane* is a split inside a tab (kitty calls panes "windows").

## OS windows

`kitty` alone lists the kitty OS windows as `w1`, `w2`, … most recently focused first, followed by all tabs. An instance (one kitty process, one socket) can own several OS windows and several instances can run; the entry is named after the window's active tab and tells the tab count, the active tab's layout and pane count and the pid.

Tab completes the input to `kitty w1 `, which lists only that window's tabs; `kitty w1 <filter>` searches its panes.

Actions: focus, open a new tab or a new pane / split in it.

<img width="899" height="559" alt="image" src="https://github.com/user-attachments/assets/82c78037-77f0-4276-a43a-7451291a3c1b" />


## Tabs

`kitty` and `kitty w1` list tabs, one entry each. Tab completes the input to `kitty w1 t2 `, which lists the panes of that tab.

Actions: focus, a new pane or split next to its active pane, switch the tab to one of the enabled layouts (all seven by default, see [Setup](#setup) for limiting them), give the tab a random color from the Nord palette or reset it, move the tab to a new OS window or to another one (`Move to w2`; only between OS windows of the same kitty process).

## Panes

`kitty <filter>` finds panes by pane title, tab title, working directory or running command, e.g. `vi` or `ssh server`. Every pane is a result of its own, so the second half of a split tab is found too. Enter focuses the pane and raises the window, Tab completes the filter to the pane title.

Actions: focus, copy the last command or its output (needs kitty's shell integration, not offered while a full screen program like vi or htop runs), copy the screen, open or copy the working directory.

Naming panes and tabs makes them easier to find. A pane's title is set by the program in it (shells put the working directory there), a tab's title is its active pane's title unless you set one. See [Setup](#setup) for shortcuts, or run `kitten @ set-window-title <name>` / `kitten @ set-tab-title <name>` inside.

<img width="895" height="392" alt="image" src="https://github.com/user-attachments/assets/e3f5bc44-46bf-4997-b4c0-7b861d02539a" />


## Find

`kitty find <text>` searches the scrollback of every pane. Results show the matching line with pane, tab and line number, newest first. Enter focuses the pane and opens its scrollback in a `less` overlay at the last match, like kitty's own show_scrollback; `q` closes it. The other action copies the line.

<img width="892" height="271" alt="image" src="https://github.com/user-attachments/assets/65a863af-eaa2-4166-a4bb-cac756e07d8f" />


## SSH

`kitty ssh [user@]<host>` opens an SSH session in the window you are working in: in a new tab, in a split (or a new pane, depending on the tab's layout) or in a new OS window. Hosts come from `~/.ssh/config` including `Include`, unknown hosts are accepted as typed. The window is titled after the host, so `kitty <host>` finds the session again, and stays at a shell prompt if the command fails.

Settings: the SSH command line (`kitten ssh %1`, `%1` is the host) and the active border color of SSH windows (`#cc2222`, red while connected).

<img width="912" height="271" alt="image" src="https://github.com/user-attachments/assets/d4ad9e43-4690-4ea4-8849-ffa64495edbc" />


The ssh feature overlaps with Albert's own [SSH plugin](https://github.com/albertlauncher/albert-plugin-ssh) which opens every connection in a new window of the system terminal. This plugin opens it in the kitty window you are working in. It only reads `~/.ssh/config`, has no remote script option and does not take part in the global query. Keep both: the native plugin for the global query and new windows, `kitty ssh` for tabs.

## Setup

Clone into `~/.local/share/albert/python/plugins/kitty` and add to `kitty.conf`, then restart kitty:

```
# required: remote control, one socket per kitty process
allow_remote_control yes
listen_on unix:@kitty-{kitty_pid}

# recommended: only the layouts you use, keeps the layout actions short
enabled_layouts splits,stack

# recommended: name tabs and panes, they are easier to find that way
# (kitty's default for set_tab_title is ctrl+shift+alt+t, set_window_title has none)
map f2 set_tab_title
map f3 set_window_title
```

Until then the plugin shows a hint whose action copies the two required lines to the clipboard.

Instances are discovered via their abstract sockets in `/proc/net/unix` (Linux only, the socket prefix `kitty-` is a setting). Raising the OS window on focus works out of the box on X11. On KDE Plasma (Wayland) KWin's focus stealing prevention ignores kitty's raise request, so the plugin activates the window through a KWin script over D-Bus (`qdbus6`) there. On other Wayland compositors only the tab is switched. Splits need the `splits` layout; the plugin assumes kitty's defaults otherwise and needs no custom keybindings.
