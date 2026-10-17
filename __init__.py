# -*- coding: utf-8 -*-
"""
Find and focus kitty tabs/windows, open new tabs and SSH sessions via kitty remote control.

Requires in kitty.conf:
    allow_remote_control yes
    listen_on unix:@kitty-{kitty_pid}
"""
from albert import *
from pathlib import Path
import json
import os
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

    def _init_configuration(self):
        for key in ("socket_prefix", "ssh_command", "ssh_border_color"):
            conf = self.readConfig(key, str)
            if not conf:
                self.writeConfig(key, getattr(self, f"_{key}"))
            else:
                setattr(self, f"_{key}", conf)

    def configWidget(self):
        return [
            {
                "type": "label",
                "text": "Requires in kitty.conf (restart kitty afterwards):<br>"
                        "<tt>allow_remote_control yes<br>listen_on unix:@kitty-{kitty_pid}</tt>",
                "widget_properties": {"textFormat": "RichText"}
            },
            {
                "type": "lineedit",
                "label": "Abstract socket prefix",
                "property": "socket_prefix"
            },
            {
                "type": "lineedit",
                "label": "SSH command line (%1 is the host)",
                "property": "ssh_command"
            },
            {
                "type": "lineedit",
                "label": "Active border color of SSH windows",
                "property": "ssh_border_color"
            },
            {
                "type": "label",
                "text": "The SSH window stays at a shell prompt if the command fails."
            },
        ]

    def defaultTrigger(self):
        return "kitty "

    def synopsis(self, query):
        return "search tabs | ssh [user@]<host> | find <text in scrollback>"

    @staticmethod
    def _icon(badge=None):
        """kitty icon with a small badge in the bottom right corner telling the item kind apart,
        same layout as the kdebridge plugin. Theme glyphs are light in dark icon themes and dark
        in light ones, and the palette is not available here, so use a mid gray pill that
        contrasts with both."""
        icon = Icon.theme("kitty")
        if not badge:
            return icon
        pill = Icon.iconified(Icon.theme(badge), Brush(Color(118, 118, 118, 235)), 0.5, 1,
                              Brush(Color(170, 170, 170)))
        return Icon.composed(icon, pill, 0.8, 0.55, 0.0, 0.0, 1.0, 1.0)

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


    def _goto_layout(self, sock, window_id, layout):
        r = self._rc(sock, "goto-layout", "--match", f"window_id:{window_id}", layout)
        if r.returncode != 0:
            self._notify(f"Layout failed: {r.stderr.strip()}")
        self._invalidate()

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
        args = ["launch", *dict((k, a) for k, _, a in self._kinds)[kind]]
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
            what = "no command output (needs shell integration)" if extent == "last_cmd_output" \
                else f"nothing: {r.stderr.strip()}"
            self._notify(f"Copied {what}")
            return
        setClipboardText(text)
        self._notify(f"Copied {text.count(chr(10)) + 1} lines")

    @staticmethod
    def _async(fn, *args, **kwargs):
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()

    def _launch_actions(self, verb, layout, os_window=True, **kwargs):
        """One action per launch kind that makes sense for the target tab's layout, e.g.
        'SSH in new tab' / 'SSH in split below'."""
        kinds = ["tab"] + (["below", "right"] if layout == "splits" else ["window"])
        if os_window:
            kinds.append("oswindow")
        return [Action(kind, f"{verb} {where}",
                       lambda k=kind, kw=kwargs: self._async(self._launch, k, **kw))
                for kind, where, _ in self._kinds if kind in kinds]

    def _active_tab(self, instances):
        """The active tab of the most recently focused OS window, or {}."""
        sock = self._active_socket(instances)
        for s, os_windows in instances:
            if s != sock:
                continue
            osw = max(os_windows, key=self._last_focus, default=None)
            if osw:
                tabs = osw.get("tabs", [])
                return next((t for t in tabs if t.get("is_active")), tabs[0] if tabs else {})
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

    def _os_window_items(self, instances):
        """One item per kitty OS window. An instance (process, socket) can own several."""
        rank_items = []
        latest = max((self._last_focus(o) for _, ows in instances for o in ows), default=0)
        for sock, os_windows in instances:
            pid = sock.rsplit(self._socket_prefix, 1)[-1]
            for osw in os_windows:
                tabs = osw.get("tabs", [])
                active_tab = next((t for t in tabs if t.get("is_active")), tabs[0] if tabs else {})
                wins = active_tab.get("windows", [])
                active = next((w for w in wins if w.get("is_active")), wins[0] if wins else {})
                # Albert has the focus while querying, so is_focused is never set here.
                focused = " · last focused" if self._last_focus(osw) == latest else ""
                # OS window ids restart per process, so name the window like KWin does: by
                # its active tab.
                layout = active_tab.get("layout") or "?"
                panes = f"{len(wins)} pane" + ("s" if len(wins) != 1 else "")
                text = f"{active_tab.get('title') or 'kitty'} · {len(tabs)} tabs{focused}"
                sub = (f"active tab: {layout} layout, {panes} · kitty pid {pid}, window {osw['id']}"
                       f" · tabs: " + ", ".join(t.get("title") or "?" for t in tabs))
                actions = []
                if active:
                    actions.append(Action("focus", "Focus",
                                          lambda s=sock, w=active["id"], t=active.get("title", ""):
                                          self._async(self._focus, s, w, t)))
                    actions += self._launch_actions("Open", layout, os_window=False, sock=sock,
                                                    target=active["id"], cwd=active.get("cwd"))
                    # The enabled layouts as actions, so their names are visible right here.
                    actions += [Action(f"layout-{name}", f"Layout: {name}",
                                       lambda s=sock, w=active["id"], n=name:
                                       self._async(self._goto_layout, s, w, n))
                                for name in active_tab.get("enabled_layouts", []) if name != layout]
                rank_items.append(RankItem(StandardItem(
                    id=f"kitty-osw-{sock}-{osw['id']}",
                    text=text,
                    subtext=sub,
                    icon_factory=lambda: self._icon("window"),
                    actions=actions
                ), 1.0 if self._last_focus(osw) == latest else 0.5))
        return rank_items

    def _window_items(self, instances, matcher):
        rank_items = []
        for sock, os_windows in instances:
            for osw in os_windows:
                for index, tab in enumerate(osw.get("tabs", []), 1):
                    ttitle = tab.get("title") or ""
                    for win in tab.get("windows", []):
                        # The tab title is just the active pane's title, so the window title is
                        # the one that identifies a pane in a split tab.
                        title = win.get("title") or ttitle
                        cwd = self._short(win.get("cwd"))
                        cmd = self._fg_command(win)
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
                        actions = [
                            Action("focus", "Focus",
                                   lambda s=sock, w=wid, t=title: self._async(self._focus, s, w, t)),
                            *([Action("copyout", "Copy last command output",
                                      lambda s=sock, w=wid: self._copy_text(s, w, "last_cmd_output"))]
                              if shell else []),
                            Action("copyscreen", "Copy screen",
                                   lambda s=sock, w=wid: self._copy_text(s, w, "screen")),
                            *([Action("copycmd", f'Copy last command: "{last_cmd[:40]}"',
                                      lambda c=last_cmd: setClipboardText(c))]
                              if shell and last_cmd else []),
                            Action("opendir", "Open directory", lambda c=wcwd: openFile(c)),
                            Action("copycwd", "Copy working directory",
                                   lambda c=wcwd: setClipboardText(c)),
                        ]
                        rank_items.append(RankItem(StandardItem(
                            id=f"kitty-{sock}-{wid}",
                            text=title,
                            subtext=sub,
                            icon_factory=lambda: self._icon("tab-new"),
                            actions=actions
                        ), m))
        return rank_items

    @staticmethod
    def _ssh_hosts():
        hosts, seen = [], set()

        def parse(path):
            if path in seen or not path.is_file():
                return
            seen.add(path)
            try:
                lines = path.read_text(errors="ignore").splitlines()
            except OSError:
                return
            for line in lines:
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                key = parts[0].lower()
                if key == "host":
                    hosts.extend(h for h in parts[1:] if not re.search(r"[*?!]", h))
                elif key == "include":
                    for pattern in parts[1:]:
                        p = Path(os.path.expanduser(pattern))
                        if not p.is_absolute():
                            p = Path.home() / ".ssh" / p
                        for inc in sorted(p.parent.glob(p.name)):
                            parse(inc)

        parse(Path.home() / ".ssh" / "config")
        return list(dict.fromkeys(hosts))

    def _ssh_items(self, arg, layout):
        target = arg.strip()
        user, at, host_part = target.rpartition("@")
        prefix = user + at  # "" or "user@"
        matcher = Matcher(host_part)
        hosts = self._ssh_hosts()
        rank_items = []
        for host in hosts:
            m = matcher.match(host)
            if m:
                rank_items.append(RankItem(self._ssh_item(prefix + host, layout), m))
        if host_part and " " not in target and host_part not in hosts:
            rank_items.append(RankItem(self._ssh_item(target, layout), 0.0))
        return rank_items

    def _ssh_item(self, target, layout):
        host = target.rpartition("@")[2]
        return StandardItem(
            id=f"kitty-ssh-{target}",
            text=f"ssh {target}",
            subtext="SSH session in kitty, stays open on error",
            icon_factory=lambda: self._icon("network-server"),
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
                    icon_factory=lambda: self._icon("edit-find"),
                    actions=[Action("goto", "Show in scrollback",
                                    lambda s=sock, w=wid, t=wtitle, x=text:
                                    self._async(self._goto_match, s, w, t, x)),
                             Action("copy", "Copy line", lambda l=line: setClipboardText(l))]
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
                            lambda: setClipboardText(self._setup_lines))]
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
            return self._os_window_items(instances)
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

    # launch kinds: (action id, where, launch args). --location only matters in the splits
    # layout, kitty's other layouts place a new window themselves.
    _kinds = [
        ("tab", "in new tab", ["--type=tab"]),
        ("window", "in new pane", ["--type=window"]),
        ("below", "in split below", ["--type=window", "--location=hsplit"]),
        ("right", "in split right", ["--type=window", "--location=vsplit"]),
        ("oswindow", "in new OS window", ["--type=os-window"]),
    ]
