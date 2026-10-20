# -*- coding: utf-8 -*-
"""
Find and focus kitty tabs/windows, open new tabs and SSH sessions via kitty remote control.

Requires in kitty.conf:
    allow_remote_control yes
    listen_on unix:@kitty-{kitty_pid}
"""
from albert import *
from functools import partial
from pathlib import Path
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import threading
import time

md_iid = "5.0"
md_version = "1.0"
md_name = "Kitty"
md_description = "Find kitty tabs, open tabs and SSH sessions via remote control"
md_license = "MIT"
md_url = "https://github.com/Bierchermuesli/albert-plugin-kitty"
md_authors = ["@Bierchermuesli"]
md_bin_dependencies = ["kitten"]


class Plugin(PluginInstance, GlobalQueryHandler):

    _socket_prefix = "kitty-"
    _ssh_command = "kitten ssh %1"
    _ssh_border_color = "#cc2222"
    _color_new_tabs = False
    _cache_ttl = 1.0
    _scrollback_ttl = 10.0

    def __init__(self):
        PluginInstance.__init__(self)
        GlobalQueryHandler.__init__(self)
        self._kitten = shutil.which("kitten") or "kitty"
        self._lock = threading.Lock()
        self._cache = (0.0, [])
        self._scrollback = (0.0, [])
        self._init_configuration()

    # --- configuration ------------------------------------------------------

    @property
    def socket_prefix(self):
        return self._socket_prefix

    @socket_prefix.setter
    def socket_prefix(self, value):
        self._socket_prefix = value
        self.writeConfig("socket_prefix", value)

    @property
    def ssh_command(self):
        return self._ssh_command

    @ssh_command.setter
    def ssh_command(self, value):
        self._ssh_command = value
        self.writeConfig("ssh_command", value)

    @property
    def ssh_border_color(self):
        return self._ssh_border_color

    @ssh_border_color.setter
    def ssh_border_color(self, value):
        self._ssh_border_color = value
        self.writeConfig("ssh_border_color", value)

    @property
    def color_new_tabs(self):
        return self._color_new_tabs

    @color_new_tabs.setter
    def color_new_tabs(self, value):
        self._color_new_tabs = value
        self.writeConfig("color_new_tabs", value)

    def _init_configuration(self):
        for key in ("socket_prefix", "ssh_command", "ssh_border_color"):
            conf = self.readConfig(key, str)
            if not conf:
                self.writeConfig(key, getattr(self, f"_{key}"))
            else:
                setattr(self, f"_{key}", conf)
        conf = self.readConfig("color_new_tabs", bool)
        if conf is None:
            self.writeConfig("color_new_tabs", self._color_new_tabs)
        else:
            self._color_new_tabs = conf

    def configWidget(self):
        return [
            {
                "type": "label",
                "text": "Requires in kitty.conf (restart kitty afterwards):<br>"
                        "<tt>allow_remote_control yes<br>listen_on unix:@kitty-{kitty_pid}</tt><br>"
                        f"Recommended settings and details: <a href='{md_url}#setup'>Setup</a>",
                "widget_properties": {"textFormat": "RichText", "openExternalLinks": True}
            },
            {
                "type": "lineedit",
                "label": "Socket prefix",
                "property": "socket_prefix"
            },
            {
                "type": "lineedit",
                "label": "SSH command (%1 is the host)",
                "property": "ssh_command"
            },
            {
                "type": "lineedit",
                "label": "SSH window border color",
                "property": "ssh_border_color"
            },
            {
                "type": "checkbox",
                "label": "Random color for new tabs",
                "property": "color_new_tabs"
            },
        ]

    def defaultTrigger(self):
        return "kitty "

    def synopsis(self, query):
        return "search panes | w<N> [t<M>] [filter] | ssh [user@]<host> | find <text in scrollback>"

    # item kind -> theme icon. The kitty icon marks the OS window itself, the others show the
    # kind of thing inside it.
    _icons = {"window": "kitty", "tab": "preferences-tabs", "pane": "utilities-terminal", "ssh": "network-connect",
              "find": "edit-find"}

    @classmethod
    def _icon(cls, kind=None):
        return Icon.theme(cls._icons[kind] if kind else "kitty")

    # --- remote control -----------------------------------------------------

    def _sockets(self):
        """Abstract sockets '@<prefix><pid>' of running kitty instances, sorted by pid."""
        found = set()
        try:
            with open("/proc/net/unix") as f:
                for line in f:
                    path = line.split()[-1]
                    if path.startswith("@" + self._socket_prefix):
                        found.add(path)
        except OSError as e:
            warning(f"Cannot read /proc/net/unix: {e}")
        alive = []
        for path in found:
            pid = path[len(self._socket_prefix) + 1:]
            if not pid.isdigit() or Path(f"/proc/{pid}").exists():
                alive.append(f"unix:{path}")
        return sorted(alive)

    def _rc(self, to, *args, timeout=3):
        return subprocess.run([self._kitten, "@", "--to", to, *args],
                              capture_output=True, text=True, timeout=timeout)

    def _instances(self):
        """[(socket, os_windows)] with a short cache, since rankItems runs on every keystroke."""
        with self._lock:
            stamp, data = self._cache
            if time.monotonic() - stamp < self._cache_ttl:
                return data
            data = []
            for sock in self._sockets():
                try:
                    r = self._rc(sock, "ls")
                    if r.returncode == 0:
                        data.append((sock, json.loads(r.stdout)))
                    else:
                        warning(f"kitty @ ls via {sock} failed: {r.stderr.strip()}")
                except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
                    warning(f"kitty @ ls via {sock} failed: {e}")
            self._cache = (time.monotonic(), data)
            return data

    def _invalidate(self):
        with self._lock:
            self._cache = (0.0, [])

    def _scrollbacks(self):
        """[(sock, window, tab index, tab title, lines)] of every window, cached a bit longer
        than ls since dumping all scrollbacks costs a few hundred ms."""
        with self._lock:
            stamp, data = self._scrollback
            if time.monotonic() - stamp < self._scrollback_ttl:
                return data
        data = []
        for sock, os_windows in self._instances():
            for osw in os_windows:
                for index, tab in enumerate(osw.get("tabs", []), 1):
                    for win in tab.get("windows", []):
                        try:
                            r = self._rc(sock, "get-text", "--match", f"id:{win['id']}",
                                         "--extent=all")
                        except subprocess.TimeoutExpired:
                            continue
                        if r.returncode == 0:
                            data.append((sock, win, index, tab.get("title") or "",
                                         r.stdout.splitlines()))
        with self._lock:
            self._scrollback = (time.monotonic(), data)
        return data

    def _goto_match(self, sock, window_id, title, text):
        """Focus the window and open its scrollback in a less overlay at the last match, the
        way kitty's show_scrollback does it. q closes the overlay."""
        self._focus(sock, window_id, title)
        r = self._rc(sock, "launch", "--type=overlay", "--match", f"window_id:{window_id}",
                     "--stdin-source=@screen_scrollback", "--stdin-add-formatting", "--",
                     "less", "-R", "-i", "+G", f"+?{re.escape(text)}")
        if r.returncode != 0:
            self._notify(f"Scrollback failed: {r.stderr.strip()}")

    @staticmethod
    def _last_focus(osw):
        """When a window of this OS window was last focused. is_focused/last_focused are per
        process, this timestamp compares across processes."""
        return max((w.get("last_focused_at") or 0
                    for t in osw.get("tabs", []) for w in t.get("windows", [])), default=0)

    def _active_socket(self, instances):
        """Socket of the instance owning the most recently focused OS window."""
        best = None
        for sock, os_windows in instances:
            for osw in os_windows:
                if osw.get("is_focused"):
                    return sock
                if best is None or self._last_focus(osw) > best[0]:
                    best = (self._last_focus(osw), sock)
        return best[1] if best else None

    def _focus(self, sock, window_id, title=""):
        r = self._rc(sock, "focus-window", "--match", f"id:{window_id}")
        if r.returncode != 0:
            self._notify(f"Focus failed: {r.stderr.strip()}")
        else:
            self._raise_os_window(sock, title)  # optional, see the end of the class
        self._invalidate()

    # Nord Aurora + Frost: (active bg, inactive bg); dark text on the pastel active tab, light
    # text on the dimmed inactive one.
    _tab_colors = [("#bf616a", "#432225"), ("#d08770", "#492f27"), ("#ebcb8b", "#524731"),
                   ("#a3be8c", "#394331"), ("#b48ead", "#3f323d"), ("#8fbcbb", "#324241"),
                   ("#88c0d0", "#304349"), ("#81a1c1", "#2d3844")]

    def _color_tab(self, sock, window_id, reset=False):
        """Color the tab containing window_id randomly, or revert it to the default colors."""
        if reset:
            colors = ["active_bg=NONE", "active_fg=NONE", "inactive_bg=NONE", "inactive_fg=NONE"]
        else:
            active, inactive = random.choice(self._tab_colors)
            colors = [f"active_bg={active}", "active_fg=#2e3440",
                      f"inactive_bg={inactive}", "inactive_fg=#d8dee9"]
        r = self._rc(sock, "set-tab-color", "--match", f"window_id:{window_id}", *colors)
        if r.returncode != 0:
            self._notify(f"Tab color failed: {r.stderr.strip()}")

    def _goto_layout(self, sock, window_id, layout):
        r = self._rc(sock, "goto-layout", "--match", f"window_id:{window_id}", layout)
        if r.returncode != 0:
            self._notify(f"Layout failed: {r.stderr.strip()}")
        self._invalidate()

    # launch kinds: id -> (label, launch args). --location only matters in the splits layout,
    # kitty's other layouts place a new window themselves.
    _kinds = {
        "tab": ("new tab", ["--type=tab"]),
        "window": ("new pane", ["--type=window"]),
        "below": ("split below", ["--type=window", "--location=hsplit"]),
        "right": ("split right", ["--type=window", "--location=vsplit"]),
        "oswindow": ("new OS window", ["--type=os-window"]),
    }

    def _launch(self, kind="tab", cwd=None, cmd=None, title=None, sock=None, target=None,
                border_color=None):
        """Launch a window of the given kind in the tab/OS window of window target (default:
        the active one), splits next to its active window. Starts kitty if no instance is
        reachable."""
        if sock is None:
            sock = self._active_socket(self._instances())
        if sock is None:
            argv = ["kitty"]
            if cwd:
                argv += ["--directory", cwd]
            if cmd:
                argv += cmd
            runDetachedProcess(argv)
            return
        args = ["launch", *self._kinds[kind][1]]
        if target is not None:
            args += ["--match", f"window_id:{target}"]
        if cwd:
            args.append(f"--cwd={cwd}")
        if title:
            args += [f"--tab-title={title}", f"--title={title}"]
        if cmd:
            args += ["--", *cmd]
        r = self._rc(sock, *args)
        if r.returncode != 0:
            self._notify(f"Launch failed: {r.stderr.strip()}")
            return
        window_id = r.stdout.strip()
        if window_id.isdigit():
            if kind == "tab" and self.color_new_tabs:
                self._color_tab(sock, window_id)
            if border_color:
                self._rc(sock, "set-colors", "--match", f"id:{window_id}",
                         f"active_border_color={border_color}")
            self._focus(sock, window_id)
        self._invalidate()

    def _notify(self, text):
        # Keep a reference, the notification is dismissed when the object is destroyed.
        self._notification = Notification(title="Kitty", text=text)
        self._notification.send()

    def _copy_text(self, sock, window_id, extent):
        """Runs on the main thread: the clipboard is not usable from a worker thread."""
        r = self._rc(sock, "get-text", "--match", f"id:{window_id}", f"--extent={extent}")
        text = r.stdout.rstrip("\n") if r.returncode == 0 else ""
        if not text:
            if extent == "last_cmd_output":
                self._notify("Copied no command output (needs shell integration)")
            else:
                self._notify(f"Copied nothing: {r.stderr.strip()}")
            return
        setClipboardText(text)
        self._notify(f"Copied {text.count(chr(10)) + 1} lines")

    @staticmethod
    def _async(fn, *args, **kwargs):
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()

    def _launch_actions(self, verb, layout, os_window=True, new_tab=True, **kwargs):
        """One action per launch kind that makes sense for the target tab's layout, e.g.
        'SSH in new tab' / 'SSH in split below', or just 'New tab' / 'Split below' without a
        verb."""
        kinds = (["tab"] if new_tab else []) + (["below", "right"] if layout == "splits" else ["window"])
        if os_window:
            kinds.append("oswindow")
        actions = []
        for kind in kinds:
            label = self._kinds[kind][0]
            text = f"{verb} in {label}" if verb else label.capitalize()
            actions.append(Action(kind, text, partial(self._async, self._launch, kind, **kwargs)))
        return actions

    @staticmethod
    def _active(items):
        """The item flagged is_active, else the first one, else {} (tabs and windows in ls)."""
        for item in items:
            if item.get("is_active"):
                return item
        return items[0] if items else {}

    @staticmethod
    def _plural(n, word):
        return f"{n} {word}" + ("" if n == 1 else "s")

    def _active_tab(self, instances):
        """The active tab of the most recently focused OS window, or {}."""
        sock = self._active_socket(instances)
        for s, os_windows in instances:
            if s == sock and os_windows:
                osw = max(os_windows, key=self._last_focus)
                return self._active(osw.get("tabs", []))
        return {}

    @staticmethod
    def _shell_cmd(cmd):
        """Run cmd in the user's shell and stay at a shell prompt if it fails, like Albert's
        ssh plugin does."""
        shell = os.environ.get("SHELL", "/bin/sh")
        return [shell, "-c", f"{cmd} || exec {shlex.quote(shell)}"]

    # --- items --------------------------------------------------------------

    @staticmethod
    def _short(path):
        home = str(Path.home())
        return "~" + path[len(home):] if path and path.startswith(home) else (path or "")

    @staticmethod
    def _fg_command(window):
        procs = window.get("foreground_processes") or []
        argv = (procs[-1].get("cmdline") if procs else window.get("cmdline")) or []
        if not argv:
            return ""
        cmd = " ".join([Path(argv[0]).name, *argv[1:]])
        return cmd if len(cmd) <= 40 else cmd[:39] + "…"

    def _ordered_os_windows(self, instances):
        """[(sock, os window)] most recently focused first. The position is the N in 'wN'."""
        return sorted(((sock, osw) for sock, ows in instances for osw in ows),
                      key=lambda e: self._last_focus(e[1]), reverse=True)

    def _os_window_items(self, instances):
        """One item per kitty OS window, numbered wN. An instance (process, socket) can own
        several. Tab completes the input to 'wN ', which lists the tabs of that window."""
        rank_items = []
        for n, (sock, osw) in enumerate(self._ordered_os_windows(instances), 1):
            pid = sock.rsplit(self._socket_prefix, 1)[-1]
            tabs = osw.get("tabs", [])
            tab = self._active(tabs)
            win = self._active(tab.get("windows", []))
            # Albert has the focus while querying, so is_focused is never set here.
            focused = " · last focused" if n == 1 else ""
            # OS window ids restart per process, so name the window like KWin does: by its
            # active tab.
            layout = tab.get("layout") or "?"
            text = f"w{n}: {tab.get('title') or 'kitty'}{focused}"
            sub = (f"{self._plural(len(tabs), 'tab')} · active tab: {layout} layout, "
                   f"{self._plural(len(tab.get('windows', [])), 'pane')} · pid {pid}")
            actions = []
            if win:
                wid = win["id"]
                actions.append(Action("focus", "Focus",
                                      partial(self._async, self._focus, sock, wid, win.get("title", ""))))
                actions += self._launch_actions("", layout, os_window=False, sock=sock,
                                                target=wid, cwd=win.get("cwd"))
            rank_items.append(RankItem(StandardItem(
                id=f"kitty-osw-{sock}-{osw['id']}",
                text=text,
                subtext=sub,
                icon_factory=partial(self._icon, "window"),
                input_action_text=f"w{n} ",
                actions=actions
            ), 1.0 - 0.01 * n))
        return rank_items

    def _detach_tab(self, sock, tab_id):
        r = self._rc(sock, "detach-tab", "--match", f"id:{tab_id}")
        if r.returncode != 0:
            self._notify(f"Move failed: {r.stderr.strip()}")
        self._invalidate()

    def _tab_items(self, instances, only=None):
        """One item per tab, in tab order, optionally only of the OS window (sock, os window
        id) given as only. Tab completes the input to 'wN tM ', which lists the tab's panes."""
        rank_items = []
        for n, (sock, osw) in enumerate(self._ordered_os_windows(instances), 1):
            if only and (sock, osw["id"]) != only:
                continue
            for index, tab in enumerate(osw.get("tabs", []), 1):
                wins = tab.get("windows", [])
                win = self._active(wins)
                if not win:
                    continue
                wid, title = win["id"], tab.get("title") or win.get("title") or ""
                layout = tab.get("layout") or "?"
                sub = " · ".join(s for s in (f"tab {index}", self._plural(len(wins), "pane"),
                                             f"{layout} layout", self._short(win.get("cwd"))) if s)
                actions = [Action("focus", "Focus", partial(self._async, self._focus, sock, wid, title))]
                # New pane or splits next to the tab's active pane, in its directory.
                actions += self._launch_actions("", layout, os_window=False, new_tab=False, sock=sock,
                                                target=wid, cwd=win.get("cwd"))
                # The enabled layouts as actions, so their names are visible right here.
                for name in tab.get("enabled_layouts", []):
                    if name != layout:
                        actions.append(Action(f"layout-{name}", f"Layout: {name}",
                                              partial(self._async, self._goto_layout, sock, wid, name)))
                actions += [
                    Action("color", "Random tab color", partial(self._async, self._color_tab, sock, wid)),
                    Action("uncolor", "Reset tab color", partial(self._async, self._color_tab, sock, wid, True)),
                    Action("detach", "Move to new OS window", partial(self._async, self._detach_tab, sock, tab["id"])),
                ]
                rank_items.append(RankItem(StandardItem(
                    id=f"kitty-tab-{sock}-{tab['id']}",
                    text=title,
                    subtext=sub,
                    icon_factory=partial(self._icon, "tab"),
                    input_action_text=f"w{n} t{index} ",
                    actions=actions
                ), 0.5 - 0.001 * len(rank_items)))  # tab order, below the windows
        return rank_items

    def _window_items(self, instances, matcher=None, only=None, tab_index=None):
        """Pane items matching matcher (None: all, in tab order), optionally only those of the
        OS window (sock, os window id) given as only, and of its tab number tab_index."""
        rank_items = []
        for sock, os_windows in instances:
            for osw in os_windows:
                if only and (sock, osw["id"]) != only:
                    continue
                for index, tab in enumerate(osw.get("tabs", []), 1):
                    if tab_index is not None and index != tab_index:
                        continue
                    ttitle = tab.get("title") or ""
                    for win in tab.get("windows", []):
                        # The tab title is just the active pane's title, so the window title is
                        # the one that identifies a pane in a split tab.
                        title = win.get("title") or ttitle
                        cwd = self._short(win.get("cwd"))
                        cmd = self._fg_command(win)
                        if matcher is None:
                            m = 0.5 - 0.001 * len(rank_items)  # tab order, below the windows
                        else:
                            m = matcher.match(title, ttitle, cwd, cmd)
                            if not m:
                                continue
                        tab_label = f"tab {index}" + (f": {ttitle}" if ttitle != title else "")
                        sub = " · ".join(s for s in (tab_label, cwd, cmd) if s)
                        wid, wcwd = win["id"], win.get("cwd") or ""
                        last_cmd = (win.get("last_reported_cmdline") or "").strip()
                        # Full screen programs (vi, htop, claude) run in the alternate screen;
                        # there is no shell prompt, so neither command nor output to copy.
                        shell = not win.get("in_alternate_screen")
                        actions = [Action("focus", "Focus",
                                          partial(self._async, self._focus, sock, wid, title))]
                        if shell:
                            actions.append(Action("copyout", "Copy last command output",
                                                  partial(self._copy_text, sock, wid, "last_cmd_output")))
                        actions.append(Action("copyscreen", "Copy screen",
                                              partial(self._copy_text, sock, wid, "screen")))
                        if shell and last_cmd:
                            actions.append(Action("copycmd", f'Copy last command: "{last_cmd[:40]}"',
                                                  partial(setClipboardText, last_cmd)))
                        actions += [
                            Action("opendir", "Open directory", partial(openFile, wcwd)),
                            Action("copycwd", "Copy working directory", partial(setClipboardText, wcwd)),
                        ]
                        rank_items.append(RankItem(StandardItem(
                            id=f"kitty-{sock}-{wid}",
                            text=title,
                            subtext=sub,
                            icon_factory=partial(self._icon, "pane"),
                            input_action_text=title,
                            actions=actions
                        ), m))
        return rank_items

    @staticmethod
    def _ssh_hosts():
        """{host alias: {option: value}} from ~/.ssh/config and its includes, in file order.
        Only the options worth showing are kept."""
        hosts, seen = {}, set()
        wanted = {"hostname", "user", "port", "proxyjump"}

        def parse(path):
            if path in seen or not path.is_file():
                return
            seen.add(path)
            try:
                lines = path.read_text(errors="ignore").splitlines()
            except OSError:
                return
            current = []
            for line in lines:
                parts = line.strip().replace("=", " ", 1).split()
                if len(parts) < 2 or parts[0].startswith("#"):
                    continue
                key = parts[0].lower()
                if key == "host":
                    current = [h for h in parts[1:] if not re.search(r"[*?!]", h)]
                    for h in current:
                        hosts.setdefault(h, {})
                elif key == "match":
                    current = []
                elif key == "include":
                    for pattern in parts[1:]:
                        p = Path(os.path.expanduser(pattern))
                        if not p.is_absolute():
                            p = Path.home() / ".ssh" / p
                        for inc in sorted(p.parent.glob(p.name)):
                            parse(inc)
                elif key in wanted:
                    for h in current:
                        hosts[h].setdefault(key, parts[1])

        parse(Path.home() / ".ssh" / "config")
        return hosts

    def _ssh_items(self, arg, layout):
        target = arg.strip()
        user, at, host_part = target.rpartition("@")
        prefix = user + at  # "" or "user@"
        matcher = Matcher(host_part)
        hosts = self._ssh_hosts()
        rank_items = []
        for host, info in hosts.items():
            m = matcher.match(host)
            if m:
                rank_items.append(RankItem(self._ssh_item(prefix + host, layout, info), m))
        if host_part and " " not in target and host_part not in hosts:
            rank_items.append(RankItem(self._ssh_item(target, layout, {}), 0.0))
        return rank_items

    def _ssh_item(self, target, layout, info):
        user, _, host = target.rpartition("@")
        user = user or info.get("user", "")
        address = info.get("hostname") or host
        port = info.get("port", "")
        if port and port != "22":
            if ":" in address:  # IPv6
                address = f"[{address}]"
            address += f":{port}"
        if user:
            address = f"{user}@{address}"
        details = [address] if info else []
        if info.get("proxyjump"):
            details.append(f"via {info['proxyjump']}")
        return StandardItem(
            id=f"kitty-ssh-{target}",
            text=f"ssh {target}",
            subtext=" · ".join(details),
            icon_factory=partial(self._icon, "ssh"),
            input_action_text=f"ssh {target}",
            actions=self._launch_actions(
                "SSH", layout, cmd=self._shell_cmd(self.ssh_command.replace("%1", shlex.quote(target))),
                title=host, border_color=self.ssh_border_color)
        )

    def _find_items(self, text):
        """Lines of any scrollback containing text, newest first per window, 20 per window."""
        if len(text) < 2:
            return []
        needle = text.lower()
        rank_items = []
        for sock, win, index, ttitle, lines in self._scrollbacks():
            hits = [(n, l) for n, l in enumerate(lines, 1) if needle in l.lower()]
            for n, line in reversed(hits[-20:]):
                wid, wtitle = win["id"], win.get("title") or ttitle
                rank_items.append(RankItem(StandardItem(
                    id=f"kitty-find-{sock}-{wid}-{n}",
                    text=line.strip(),
                    subtext=f"{wtitle} · tab {index} · line {n} of {len(lines)}",
                    icon_factory=partial(self._icon, "find"),
                    actions=[Action("goto", "Show in scrollback",
                                    partial(self._async, self._goto_match, sock, wid, wtitle, text)),
                             Action("copy", "Copy line", partial(setClipboardText, line))]
                ), n / len(lines)))
        return rank_items

    _setup_lines = "allow_remote_control yes\nlisten_on unix:@kitty-{kitty_pid}\n"

    def _setup_hint(self):
        return RankItem(StandardItem(
            id="kitty-setup",
            text="No kitty remote control socket found",
            subtext="Add the two lines to kitty.conf and restart kitty",
            icon_factory=self._icon,
            actions=[Action("copy", "Copy kitty.conf lines",
                            partial(setClipboardText, self._setup_lines))]
        ), 0.0)

    def rankItems(self, ctx):
        query = ctx.query.strip()
        triggered = bool(ctx.trigger)

        if triggered:
            cmd, _, arg = query.partition(" ")
            if cmd == "ssh":
                return self._ssh_items(arg, self._active_tab(self._instances()).get("layout"))
            if cmd == "find":
                return self._find_items(arg.strip())
        elif not query:
            return []

        instances = self._instances()
        if triggered and not instances:
            return [self._setup_hint()]
        if triggered and not query:
            return self._os_window_items(instances) + self._tab_items(instances)
        if triggered and (m := re.fullmatch(r"w(\d+)(?:\s+t(\d+))?(?:\s+(.*))?", query)):
            ordered = self._ordered_os_windows(instances)
            n, tab_index, text = int(m.group(1)), m.group(2), (m.group(3) or "").strip()
            if 1 <= n <= len(ordered):
                sock, osw = ordered[n - 1]
                only = (sock, osw["id"])
                if tab_index is None and not text:
                    return self._tab_items(instances, only=only)
                return self._window_items(instances, Matcher(text) if text else None, only=only,
                                          tab_index=int(tab_index) if tab_index else None)
        return self._window_items(instances, Matcher(query))

    # --- optional: raise the OS window on KDE Plasma (Wayland) ----------------------------------
    #
    # Everything above works with kitty's remote control alone. This part only exists because
    # on Wayland KWin's focus stealing prevention ignores kitty's request to raise its OS
    # window, so focus-window would switch the tab but leave the window behind. It activates
    # the window through KWin's scripting D-Bus interface instead. On X11 kitty raises the
    # window itself and this is not needed, so it is skipped there, as it is without qdbus6 or
    # when KWin does not answer. Other Wayland compositors would need their own way (swaymsg,
    # hyprctl); until someone adds one, they just get the tab switched.

    _kwin_script = """
const pid = %d;
const title = %s;
const ws = workspace.windowList().filter(w => w.pid === pid && w.normalWindow);
if (ws.length) {
  const w = ws.find(w => w.caption.includes(title)) || ws[0];
  w.minimized = false;
  if (!w.onAllDesktops && !w.desktops.includes(workspace.currentDesktop))
    workspace.currentDesktop = w.desktops[0];
  workspace.activeWindow = w;
}
"""

    def _raise_os_window(self, sock, title):
        """Best effort, KDE Wayland only: activate the kitty OS window of the instance behind
        sock whose caption contains title, via a throwaway KWin script. Does nothing elsewhere."""
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "x11":
            return
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        pid = sock.rsplit(self._socket_prefix, 1)[-1]
        if not qdbus or not pid.isdigit():
            return
        name = f"albert-kitty-{os.getpid()}"
        script = Path(self.cacheLocation()) / "raise.js"
        try:
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(self._kwin_script % (int(pid), json.dumps(title)))

            def call(path, method, *args):
                return subprocess.run([qdbus, "org.kde.KWin", path, method, *args],
                                      capture_output=True, text=True, timeout=2)

            call("/Scripting", "org.kde.kwin.Scripting.unloadScript", name)  # leftovers
            r = call("/Scripting", "org.kde.kwin.Scripting.loadScript", str(script), name)
            script_id = r.stdout.strip()
            if r.returncode != 0 or not script_id.isdigit():
                warning(f"KWin loadScript failed: {r.stderr.strip() or script_id}")
                return
            call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script.run")
            time.sleep(0.5)
            call("/Scripting", "org.kde.kwin.Scripting.unloadScript", name)
        except (OSError, subprocess.TimeoutExpired) as e:
            warning(f"KWin script failed: {e}")
