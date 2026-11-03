import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import theme
from core.config import ConfigManager
from core.deployer import deploy_mods, get_deployed_mods, is_deploy_interrupted, purge_mods

POLL_INTERVAL_MS = 2000
LOG_INTERVAL_MS = 100
NO_GAME = "Aucun jeu"
_TASK_DONE = object()  # end-of-task marker in the log queue


class ModsTab(ctk.CTkFrame):
    """Main tab: game selection, load order management, deployment."""

    def __init__(self, master, cfg: ConfigManager):
        super().__init__(master, fg_color="transparent", border_width=0)
        self.cfg = cfg
        self.game_var = ctk.StringVar(value=NO_GAME)
        self.force_copy_var = ctk.BooleanVar(value=False)  # real copy instead of hard links (per game)
        self.load_order: list[str] = []
        self.available_mods: list[str] = []
        self._snapshot = None
        self.busy = False  # true during a deployment / purge (run in a thread)
        self._log_queue: queue.Queue = queue.Queue()
        self._action_widgets: list = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # mods area
        self.grid_rowconfigure(3, weight=1)  # logs

        self.build_ui()
        self.refresh()
        self.after(POLL_INTERVAL_MS, self._poll)

    # ------------------------------------------------------------------ UI
    def build_ui(self):
        # --- Top bar: game + refresh + open folder ---
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        theme.section_label(top, "Jeu :").grid(row=0, column=0, padx=10, pady=10)
        self.game_combo = ctk.CTkComboBox(
            top, variable=self.game_var, values=[NO_GAME], state="readonly", command=self.on_game_selected
        )
        self.game_combo.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        btn_refresh = ctk.CTkButton(
            top,
            text="🔄 Rafraîchir",
            width=110,
            command=self.refresh,
            fg_color="transparent",
            border_width=1,
            border_color=theme.CYAN,
            hover_color=theme.PANEL_ALT,
        )
        btn_refresh.grid(row=0, column=2, padx=5, pady=10)
        ctk.CTkButton(
            top,
            text="📂 Ouvrir Mods",
            width=110,
            command=self.open_mods_folder,
            fg_color="transparent",
            border_width=1,
            border_color=theme.CYAN,
            hover_color=theme.PANEL_ALT,
        ).grid(row=0, column=3, padx=(5, 10), pady=10)
        self._action_widgets += [self.game_combo, btn_refresh]

        # --- Load order management ---
        frame_mods = ctk.CTkFrame(self)
        frame_mods.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        frame_mods.grid_columnconfigure(0, weight=1)
        frame_mods.grid_columnconfigure(2, weight=1)
        frame_mods.grid_rowconfigure(1, weight=1)

        theme.section_label(frame_mods, "Bibliothèque (hors liste de déploiement)").grid(row=0, column=0, pady=(10, 5))
        self.list_available = self._make_listbox(frame_mods)
        self.list_available.grid(row=1, column=0, padx=(15, 5), pady=(0, 15), sticky="nsew")

        frame_transfer = ctk.CTkFrame(frame_mods, fg_color="transparent", border_width=0)
        frame_transfer.grid(row=1, column=1, padx=5)
        btn_enable = ctk.CTkButton(frame_transfer, text="Activer ►", width=90, command=self.activate_mod)
        btn_enable.pack(pady=5)
        btn_remove = ctk.CTkButton(
            frame_transfer,
            text="◄ Retirer",
            width=90,
            command=self.deactivate_mod,
            fg_color=theme.DANGER_SOFT,
            hover_color=theme.DANGER_SOFT_HOVER,
        )
        btn_remove.pack(pady=5)

        theme.section_label(frame_mods, "Ordre de déploiement (plus bas = prioritaire)").grid(
            row=0, column=2, pady=(10, 5)
        )
        self.list_active = self._make_listbox(frame_mods)
        self.list_active.grid(row=1, column=2, padx=5, pady=(0, 15), sticky="nsew")

        frame_order = ctk.CTkFrame(frame_mods, fg_color="transparent", border_width=0)
        frame_order.grid(row=1, column=3, padx=(0, 15))
        btn_up = ctk.CTkButton(frame_order, text="▲ Monter", width=70, command=self.move_up)
        btn_up.pack(pady=5)
        btn_down = ctk.CTkButton(frame_order, text="▼ Descendre", width=70, command=self.move_down)
        btn_down.pack(pady=5)

        # --- Main actions ---
        frame_actions = ctk.CTkFrame(self)
        frame_actions.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        frame_actions.grid_columnconfigure((0, 1), weight=1)
        btn_deploy = ctk.CTkButton(
            frame_actions,
            text="🚀 DÉPLOYER LES MODS",
            command=self.action_deploy,
            fg_color=theme.SUCCESS,
            hover_color=theme.SUCCESS_HOVER,
            height=48,
            font=theme.font(15, "bold"),
        )
        btn_deploy.grid(row=0, column=0, padx=15, pady=(15, 8), sticky="ew")
        btn_purge = ctk.CTkButton(
            frame_actions,
            text="🧹 PURGER (JEU D'ORIGINE)",
            command=self.action_purge,
            fg_color=theme.DANGER,
            hover_color=theme.DANGER_HOVER,
            height=48,
            font=theme.font(15, "bold"),
        )
        btn_purge.grid(row=0, column=1, padx=15, pady=(15, 8), sticky="ew")
        self.force_copy_check = ctk.CTkCheckBox(
            frame_actions,
            variable=self.force_copy_var,
            command=self.on_force_copy_toggled,
            text="Forcer la copie réelle des fichiers (au lieu des hard links)",
        )
        self.force_copy_check.grid(row=1, column=0, columnspan=2, padx=15, pady=(0, 12), sticky="w")
        self._action_widgets += [
            btn_enable,
            btn_remove,
            btn_up,
            btn_down,
            btn_deploy,
            btn_purge,
            self.force_copy_check,
        ]

        # --- Logs ---
        frame_logs = ctk.CTkFrame(self)
        frame_logs.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        frame_logs.grid_columnconfigure(0, weight=1)
        frame_logs.grid_rowconfigure(0, weight=1)
        self.log_textbox = ctk.CTkTextbox(frame_logs, state="disabled", **theme.console_options())
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # --- Status ---
        self.lbl_status = ctk.CTkLabel(self, text="", anchor="w", text_color=theme.CYAN)
        self.lbl_status.grid(row=4, column=0, padx=15, pady=(0, 5), sticky="ew")

    @staticmethod
    def _make_listbox(master) -> tk.Listbox:
        return tk.Listbox(master, **theme.listbox_options())

    # ------------------------------------------------------------ Data
    def _game(self) -> dict | None:
        return self.cfg.active_game()

    def _mods_dir(self) -> Path:
        game = self._game()
        assert game is not None, "No active game"
        return self.cfg.mods_dir(game["name"])

    def _scan(self):
        """Lightweight fingerprint of the disk state, used to detect changes."""
        game = self._game()
        if not game:
            return None
        mods_dir = self._mods_dir()
        mods = tuple(sorted(p.name for p in mods_dir.iterdir() if p.is_dir())) if mods_dir.exists() else ()
        return game["name"], mods, tuple(get_deployed_mods(Path(game["game_dir"])))

    def refresh(self):
        """Reload the games, the available mods and the deployment state."""
        if self.busy:
            return  # Refreshed automatically when the current task ends
        names = self.cfg.game_names()
        self.game_combo.configure(values=names or [NO_GAME])
        game = self._game()
        self.game_var.set(game["name"] if game else NO_GAME)

        self.force_copy_var.set(bool(game and game.get("force_copy")))
        self.force_copy_check.configure(state="normal" if game else "disabled")
        if game is None:
            self.load_order, self.available_mods = [], []
            self.update_listboxes()
            self.lbl_status.configure(text="Aucun jeu configuré : ajoutez-en un dans l'onglet Paramètres.")
            self._snapshot = None
            return

        mods_dir = self._mods_dir()
        mods_dir.mkdir(parents=True, exist_ok=True)
        all_mods = sorted(p.name for p in mods_dir.iterdir() if p.is_dir())

        previous_order = list(game["load_order"])
        self.load_order = [m for m in previous_order if m in all_mods]
        if self.load_order != previous_order:
            self.cfg.set_load_order(game["name"], self.load_order)
        self.available_mods = [m for m in all_mods if m not in self.load_order]

        self.update_listboxes()
        self._snapshot = self._scan()

    def _poll(self):
        try:
            if not self.busy and self._scan() != self._snapshot:
                self.refresh()
        except OSError:
            pass  # Folder temporarily unavailable: retry on the next tick
        finally:
            self.after(POLL_INTERVAL_MS, self._poll)

    def update_listboxes(self):
        deployed = []
        game = self._game()
        if game:
            deployed = get_deployed_mods(Path(game["game_dir"]))

        self.list_available.delete(0, tk.END)
        for mod in self.available_mods:
            self.list_available.insert(tk.END, mod)

        self.list_active.delete(0, tk.END)
        for mod in self.load_order:
            marker = "✔" if mod in deployed else "⏳"
            self.list_active.insert(tk.END, f"{marker}  {mod}")

        self._update_status(deployed)

    def _update_status(self, deployed: list[str]):
        game = self._game()
        if game is None:
            return
        if is_deploy_interrupted(Path(game["game_dir"])):
            text = "⚠ Le dernier déploiement a été interrompu ou son état est illisible : lancez une purge puis redéployez."
        elif not deployed:
            text = "Aucun mod déployé. ⏳ = en liste de déploiement, en attente de déploiement."
        elif deployed == self.load_order:
            text = f"✔ À jour : {len(deployed)} mod(s) déployé(s)."
        else:
            text = (
                f"⏳ Modifications en attente ({len(deployed)} mod(s) actuellement déployé(s)) : cliquez sur Déployer."
            )
        self.lbl_status.configure(text=text)

    def _save_order(self):
        game = self._game()
        if game:
            self.cfg.set_load_order(game["name"], self.load_order)
            self._snapshot = self._scan()

    # ------------------------------------------------------------ Actions
    def on_game_selected(self, name: str):
        self.cfg.set_active_game(name)
        self.refresh()

    def on_force_copy_toggled(self):
        game = self._game()
        if game:
            self.cfg.set_force_copy(game["name"], self.force_copy_var.get())

    def open_mods_folder(self):
        if self._game() is None:
            messagebox.showwarning("Erreur", "Aucun jeu sélectionné.")
            return
        mods_dir = self._mods_dir()
        mods_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(mods_dir)

    def activate_mod(self):
        selection = self.list_available.curselection()
        if selection:
            mod = self.available_mods.pop(selection[0])
            self.load_order.append(mod)
            self._save_order()
            self.update_listboxes()

    def deactivate_mod(self):
        selection = self.list_active.curselection()
        if selection:
            mod = self.load_order.pop(selection[0])
            self.available_mods.append(mod)
            self.available_mods.sort()
            self._save_order()
            self.update_listboxes()

    def move_up(self):
        selection = self.list_active.curselection()
        if selection and selection[0] > 0:
            idx = selection[0]
            self.load_order.insert(idx - 1, self.load_order.pop(idx))
            self._save_order()
            self.update_listboxes()
            self.list_active.select_set(idx - 1)

    def move_down(self):
        selection = self.list_active.curselection()
        if selection and selection[0] < len(self.load_order) - 1:
            idx = selection[0]
            self.load_order.insert(idx + 1, self.load_order.pop(idx))
            self._save_order()
            self.update_listboxes()
            self.list_active.select_set(idx + 1)

    # --------------------------------------------------------------- Logs
    def log(self, message: str = ""):
        """Can be called from any thread: messages go through a queue."""
        self._log_queue.put(str(message))

    def _write_log(self, message: str):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _drain_logs(self):
        """Display the pending messages (UI thread) and detect the end of the task."""
        done = False
        try:
            while True:
                message = self._log_queue.get_nowait()
                if message is _TASK_DONE:
                    done = True
                    break
                self._write_log(message)
        except queue.Empty:
            pass
        if done:
            self._end_task()
        else:
            self.after(LOG_INTERVAL_MS, self._drain_logs)

    def log_clear(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    # ------------------------------------------------- Deployment / Purge
    def _run_task(self, title: str, func):
        """Run func() in a thread so the UI does not freeze, while blocking the other actions."""
        self.busy = True
        for widget in self._action_widgets:
            widget.configure(state="disabled")
        self.lbl_status.configure(text=f"⏳ {title} en cours, veuillez patienter...")
        self.log_clear()

        def worker():
            try:
                func()
            except Exception as e:
                self.log(f"[ERREUR INATTENDUE] {e}")
            finally:
                self._log_queue.put(_TASK_DONE)

        threading.Thread(target=worker, name=title, daemon=False).start()
        self.after(LOG_INTERVAL_MS, self._drain_logs)

    def _end_task(self):
        self.busy = False
        for widget in self._action_widgets:
            widget.configure(state="readonly" if widget is self.game_combo else "normal")
        self.refresh()

    def action_deploy(self):
        if self.busy:
            return
        game = self._game()
        if game is None:
            messagebox.showwarning("Erreur", "Veuillez configurer et sélectionner un jeu (onglet Paramètres).")
            return
        if not self.load_order:
            messagebox.showwarning("Erreur", "Aucun mod n'est dans la liste de déploiement.")
            return
        game_dir = Path(game["game_dir"])
        if not game_dir.exists():
            messagebox.showerror("Erreur", "Le dossier du jeu spécifié n'existe pas.")
            return

        mods_dir, load_order = self._mods_dir(), list(self.load_order)
        force_copy = bool(game.get("force_copy"))

        def task():
            self.log("=== LANCEMENT DU DÉPLOIEMENT ===")
            self.log(f"Jeu cible : {game['name']} ({game_dir})")
            if force_copy:
                self.log("Mode : copie réelle des fichiers (hard links désactivés)")
            deploy_mods(game_dir, mods_dir, load_order, logger=self.log, force_copy=force_copy)

        self._run_task("Déploiement", task)

    def action_purge(self):
        if self.busy:
            return
        game = self._game()
        if game is None:
            return
        game_dir = Path(game["game_dir"])
        if not game_dir.exists():
            messagebox.showerror("Erreur", "Le dossier du jeu spécifié n'existe pas.")
            return
        if not messagebox.askyesno(
            "Confirmation de Purge",
            f"Voulez-vous vraiment retirer tous les mods de « {game['name']} » "
            "et restaurer le jeu à son état d'origine ?",
        ):
            return

        def task():
            self.log("=== LANCEMENT DE LA PURGE ===")
            purge_mods(game_dir, logger=self.log)

        self._run_task("Purge", task)
