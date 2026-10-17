# -*- coding: utf-8 -*-
"""
Find and focus kitty tabs/windows, open new tabs, SSH and commands via kitty remote control.

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
md_description = "Find kitty tabs, open tabs, SSH and commands via remote control"
md_license = "MIT"
md_url = "https://github.com/Bierchermuesli/albert-plugin-kitty"
md_authors = ["@Bierchermuesli"]
md_bin_dependencies = ["kitten"]


class Plugin(PluginInstance, GlobalQueryHandler):

    _socket_prefix = "kitty-"
    _cache_ttl = 1.0

    def __init__(self):
        PluginInstance.__init__(self)
        GlobalQueryHandler.__init__(self)
        self._kitten = shutil.which("kitten") or "kitty"
        self._lock = threading.Lock()
        self._cache = (0.0, [])
        self._init_configuration()

    # --- configuration ------------------------------------------------------

    @property
    def socket_prefix(self):
        return self._socket_prefix

    @socket_prefix.setter
    def socket_prefix(self, value):
        self._socket_prefix = value
        self.writeConfig("socket_prefix", value)

    def _init_configuration(self):
        conf = self.readConfig("socket_prefix", str)
        if conf is None:
            self.writeConfig("socket_prefix", self._socket_prefix)
        else:
            self._socket_prefix = conf

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
        ]

    def defaultTrigger(self):
        return "kitty "

    def synopsis(self, query):
        return "<filter> | ssh <host> | run <cmd> | <dir>"

    @staticmethod
    def _icon():
        return Icon.theme("kitty")

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

    def _active_socket(self, instances):
        """Socket of the instance owning the focused (or last focused) OS window."""
        for key in ("is_focused", "last_focused"):
            for sock, os_windows in instances:
                if any(w.get(key) for w in os_windows):
                    return sock
        return instances[0][0] if instances else None

    def _focus(self, sock, window_id, title=""):
        r = self._rc(sock, "focus-window", "--match", f"id:{window_id}")
        if r.returncode != 0:
            Notification(title="Kitty", text=f"Focus failed: {r.stderr.strip()}").send()
        else:
            self._raise_os_window(sock, title)
        self._invalidate()

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
        """Activate the kitty OS window via a KWin script. focus-window alone only switches the
        tab, since KWin's focus stealing prevention ignores the request on Wayland."""
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

    def _launch(self, cwd=None, cmd=None, title=None):
        """Open a new tab in the active kitty instance, or start kitty if none is reachable."""
        sock = self._active_socket(self._instances())
        if sock is None:
            argv = ["kitty"]
            if cwd:
                argv += ["--directory", cwd]
            if cmd:
                argv += cmd
            runDetachedProcess(argv)
            return
        args = ["launch", "--type=tab"]
        if cwd:
            args.append(f"--cwd={cwd}")
        if title:
            args.append(f"--tab-title={title}")
        if cmd:
            args += ["--", *cmd]
        r = self._rc(sock, *args)
        if r.returncode != 0:
            Notification(title="Kitty", text=f"Launch failed: {r.stderr.strip()}").send()
            return
        window_id = r.stdout.strip()
        if window_id.isdigit():
            self._focus(sock, window_id)
        self._invalidate()

    @staticmethod
    def _async(fn, *args, **kwargs):
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()

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
                        actions = [
                            Action("focus", "Focus",
                                   lambda s=sock, w=wid, t=title: self._async(self._focus, s, w, t)),
                            Action("newtab", "New tab here",
                                   lambda c=wcwd: self._async(self._launch, cwd=c)),
                            Action("copycwd", "Copy working directory",
                                   lambda c=wcwd: setClipboardText(c)),
                        ]
                        rank_items.append(RankItem(StandardItem(
                            id=f"kitty-{sock}-{wid}",
                            text=title,
                            subtext=sub,
                            icon_factory=self._icon,
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

    def _ssh_items(self, arg):
        target = arg.strip()
        matcher = Matcher(target)
        hosts = self._ssh_hosts()
        rank_items = []
        for host in hosts:
            m = matcher.match(host)
            if m:
                rank_items.append(RankItem(self._ssh_item(host), m))
        if target and " " not in target and target not in hosts:
            rank_items.append(RankItem(self._ssh_item(target), 0.0))
        return rank_items

    def _ssh_item(self, host):
        return StandardItem(
            id=f"kitty-ssh-{host}",
            text=f"ssh {host}",
            subtext="Open SSH session in a new kitty tab",
            icon_factory=self._icon,
            input_action_text=f"ssh {host}",
            actions=[Action("ssh", "SSH in new tab",
                            lambda h=host: self._async(self._launch, cmd=["ssh", h], title=h))]
        )

    def _run_item(self, cmd):
        shell = os.environ.get("SHELL", "/bin/sh")
        argv = [shell, "-c", f"{cmd}; exec {shlex.quote(shell)}"]
        return RankItem(StandardItem(
            id="kitty-run",
            text=f"Run '{cmd}'",
            subtext="Run command in a new kitty tab",
            icon_factory=self._icon,
            actions=[Action("run", "Run in new tab",
                            lambda: self._async(self._launch, cwd=str(Path.home()), cmd=argv))]
        ), 1.0)

    def _dir_items(self, arg):
        path = Path(os.path.expanduser(arg))
        if not path.is_absolute():
            return []
        if path.is_dir():
            candidates = [path]
        else:
            parent = path.parent
            if not parent.is_dir():
                return []
            prefix = path.name.lower()
            try:
                candidates = sorted(p for p in parent.iterdir()
                                    if p.is_dir() and p.name.lower().startswith(prefix)
                                    and not p.name.startswith("."))[:20]
            except OSError:
                return []
        return [RankItem(StandardItem(
            id=f"kitty-dir-{p}",
            text=f"New tab in {self._short(str(p))}",
            subtext=str(p),
            icon_factory=self._icon,
            input_action_text=self._short(str(p)) + "/",
            actions=[Action("newtab", "New tab here",
                            lambda d=str(p): self._async(self._launch, cwd=d))]
        ), 1.0 if p == path else 0.5) for p in candidates]

    def _setup_hint(self):
        return RankItem(StandardItem(
            id="kitty-setup",
            text="No kitty remote control socket found",
            subtext="Add 'listen_on unix:@kitty-{kitty_pid}' to kitty.conf and restart kitty",
            icon_factory=self._icon,
        ), 0.0)

    def rankItems(self, ctx):
        query = ctx.query.strip()
        triggered = bool(ctx.trigger)

        if triggered:
            cmd, _, arg = query.partition(" ")
            if cmd == "ssh":
                return self._ssh_items(arg)
            if cmd == "run":
                return [self._run_item(arg.strip())] if arg.strip() else []
            if query.startswith(("/", "~")):
                return self._dir_items(query)
        elif not query:
            return []

        instances = self._instances()
        if triggered and not instances:
            return [self._setup_hint()]
        return self._window_items(instances, Matcher(query))
