import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import theme
from core.config import ConfigManager
from core.deployer import deploy_mods, purge_mods, get_deployed_mods, is_deploy_interrupted

POLL_INTERVAL_MS = 2000
LOG_INTERVAL_MS = 100
AUCUN_JEU = "Aucun jeu"
_FIN_TACHE = object()  # marqueur de fin d'opération dans la file des logs


class ModsTab(ctk.CTkFrame):
    """Onglet principal : sélection du jeu, gestion du load order, déploiement."""

    def __init__(self, master, cfg: ConfigManager):
        super().__init__(master, fg_color="transparent", border_width=0)
        self.cfg = cfg
        self.game_var = ctk.StringVar(value=AUCUN_JEU)
        self.copie_var = ctk.BooleanVar(value=False)  # copie réelle au lieu de hard links (par jeu)
        self.load_order: list[str] = []
        self.available_mods: list[str] = []
        self._snapshot = None
        self.busy = False  # vrai pendant un déploiement / une purge (exécutés dans un thread)
        self._log_queue: queue.Queue = queue.Queue()
        self._action_widgets: list = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # zone des mods
        self.grid_rowconfigure(3, weight=1)  # logs

        self.build_ui()
        self.refresh()
        self.after(POLL_INTERVAL_MS, self._poll)

    # ------------------------------------------------------------------ UI
    def build_ui(self):
        # --- Barre du haut : jeu + rafraîchir + ouvrir dossier ---
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        theme.section_label(top, "Jeu :").grid(row=0, column=0, padx=10, pady=10)
        self.combo_jeu = ctk.CTkComboBox(top, variable=self.game_var, values=[AUCUN_JEU],
                                         state="readonly", command=self.on_game_selected)
        self.combo_jeu.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        btn_refresh = ctk.CTkButton(top, text="🔄 Rafraîchir", width=110, command=self.refresh,
                                    fg_color="transparent", border_width=1, border_color=theme.CYAN,
                                    hover_color=theme.PANEL_ALT)
        btn_refresh.grid(row=0, column=2, padx=5, pady=10)
        ctk.CTkButton(top, text="📂 Ouvrir Mods", width=110, command=self.open_mods_folder,
                      fg_color="transparent", border_width=1, border_color=theme.CYAN, hover_color=theme.PANEL_ALT).grid(row=0, column=3, padx=(5, 10), pady=10)
        self._action_widgets += [self.combo_jeu, btn_refresh]

        # --- Gestion du Load Order ---
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
        btn_activer = ctk.CTkButton(frame_transfer, text="Activer ►", width=90, command=self.activate_mod)
        btn_activer.pack(pady=5)
        btn_retirer = ctk.CTkButton(frame_transfer, text="◄ Retirer", width=90, command=self.deactivate_mod,
                                    fg_color=theme.DANGER_SOFT, hover_color=theme.DANGER_SOFT_HOVER)
        btn_retirer.pack(pady=5)

        theme.section_label(frame_mods, "Ordre de déploiement (plus bas = prioritaire)").grid(row=0, column=2, pady=(10, 5))
        self.list_active = self._make_listbox(frame_mods)
        self.list_active.grid(row=1, column=2, padx=5, pady=(0, 15), sticky="nsew")

        frame_order = ctk.CTkFrame(frame_mods, fg_color="transparent", border_width=0)
        frame_order.grid(row=1, column=3, padx=(0, 15))
        btn_monter = ctk.CTkButton(frame_order, text="▲ Monter", width=70, command=self.move_up)
        btn_monter.pack(pady=5)
        btn_descendre = ctk.CTkButton(frame_order, text="▼ Descendre", width=70, command=self.move_down)
        btn_descendre.pack(pady=5)

        # --- Actions principales ---
        frame_actions = ctk.CTkFrame(self)
        frame_actions.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        frame_actions.grid_columnconfigure((0, 1), weight=1)
        btn_deploy = ctk.CTkButton(frame_actions, text="🚀 DÉPLOYER LES MODS", command=self.action_deploy,
                                   fg_color=theme.SUCCESS, hover_color=theme.SUCCESS_HOVER, height=48,
                                   font=theme.font(15, "bold"))
        btn_deploy.grid(row=0, column=0, padx=15, pady=(15, 8), sticky="ew")
        btn_purge = ctk.CTkButton(frame_actions, text="🧹 PURGER (JEU D'ORIGINE)", command=self.action_purge,
                                  fg_color=theme.DANGER, hover_color=theme.DANGER_HOVER, height=48,
                                  font=theme.font(15, "bold"))
        btn_purge.grid(row=0, column=1, padx=15, pady=(15, 8), sticky="ew")
        self.chk_copie = ctk.CTkCheckBox(frame_actions, variable=self.copie_var, command=self.on_copie_toggled,
                                         text="Forcer la copie réelle des fichiers (au lieu des hard links)")
        self.chk_copie.grid(row=1, column=0, columnspan=2, padx=15, pady=(0, 12), sticky="w")
        self._action_widgets += [btn_activer, btn_retirer, btn_monter, btn_descendre, btn_deploy, btn_purge,
                                 self.chk_copie]

        # --- Logs ---
        frame_logs = ctk.CTkFrame(self)
        frame_logs.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        frame_logs.grid_columnconfigure(0, weight=1)
        frame_logs.grid_rowconfigure(0, weight=1)
        self.log_textbox = ctk.CTkTextbox(frame_logs, state="disabled", **theme.console_options())
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # --- Statut ---
        self.lbl_status = ctk.CTkLabel(self, text="", anchor="w", text_color=theme.CYAN)
        self.lbl_status.grid(row=4, column=0, padx=15, pady=(0, 5), sticky="ew")

    @staticmethod
    def _make_listbox(master) -> tk.Listbox:
        return tk.Listbox(master, **theme.listbox_options())

    # ------------------------------------------------------------ Données
    def _jeu(self) -> dict | None:
        return self.cfg.jeu_actif()

    def _mods_dir(self) -> Path:
        jeu = self._jeu()
        assert jeu is not None, "Aucun jeu actif"
        return self.cfg.mods_dir(jeu["nom"])

    def _scan(self):
        """Empreinte légère de l'état disque, utilisée pour détecter les changements."""
        jeu = self._jeu()
        if not jeu:
            return None
        mods_dir = self._mods_dir()
        mods = tuple(sorted(p.name for p in mods_dir.iterdir() if p.is_dir())) if mods_dir.exists() else ()
        return jeu["nom"], mods, tuple(get_deployed_mods(Path(jeu["dossier"])))

    def refresh(self):
        """Recharge jeux, mods disponibles et état de déploiement."""
        if self.busy:
            return  # Rafraîchi automatiquement à la fin de l'opération en cours
        noms = self.cfg.noms_jeux()
        self.combo_jeu.configure(values=noms or [AUCUN_JEU])
        jeu = self._jeu()
        self.game_var.set(jeu["nom"] if jeu else AUCUN_JEU)

        self.copie_var.set(bool(jeu and jeu.get("copie_forcee")))
        self.chk_copie.configure(state="normal" if jeu else "disabled")
        if jeu is None:
            self.load_order, self.available_mods = [], []
            self.update_listboxes()
            self.lbl_status.configure(text="Aucun jeu configuré : ajoutez-en un dans l'onglet Paramètres.")
            self._snapshot = None
            return

        mods_dir = self._mods_dir()
        mods_dir.mkdir(parents=True, exist_ok=True)
        tous = sorted(p.name for p in mods_dir.iterdir() if p.is_dir())

        ancien_ordre = list(jeu["load_order"])
        self.load_order = [m for m in ancien_ordre if m in tous]
        if self.load_order != ancien_ordre:
            self.cfg.set_load_order(jeu["nom"], self.load_order)
        self.available_mods = [m for m in tous if m not in self.load_order]

        self.update_listboxes()
        self._snapshot = self._scan()

    def _poll(self):
        try:
            if not self.busy and self._scan() != self._snapshot:
                self.refresh()
        except OSError:
            pass  # Dossier momentanément inaccessible : on réessaiera au prochain tour
        finally:
            self.after(POLL_INTERVAL_MS, self._poll)

    def update_listboxes(self):
        deployed = []
        jeu = self._jeu()
        if jeu:
            deployed = get_deployed_mods(Path(jeu["dossier"]))

        self.list_available.delete(0, tk.END)
        for mod in self.available_mods:
            self.list_available.insert(tk.END, mod)

        self.list_active.delete(0, tk.END)
        for mod in self.load_order:
            marqueur = "✔" if mod in deployed else "⏳"
            self.list_active.insert(tk.END, f"{marqueur}  {mod}")

        self._update_status(deployed)

    def _update_status(self, deployed: list[str]):
        jeu = self._jeu()
        if jeu is None:
            return
        if is_deploy_interrupted(Path(jeu["dossier"])):
            texte = "⚠ Le dernier déploiement a été interrompu ou son état est illisible : lancez une purge puis redéployez."
        elif not deployed:
            texte = "Aucun mod déployé. ⏳ = en liste de déploiement, en attente de déploiement."
        elif deployed == self.load_order:
            texte = f"✔ À jour : {len(deployed)} mod(s) déployé(s)."
        else:
            texte = f"⏳ Modifications en attente ({len(deployed)} mod(s) actuellement déployé(s)) : cliquez sur Déployer."
        self.lbl_status.configure(text=texte)

    def _save_order(self):
        jeu = self._jeu()
        if jeu:
            self.cfg.set_load_order(jeu["nom"], self.load_order)
            self._snapshot = self._scan()

    # ------------------------------------------------------------ Actions
    def on_game_selected(self, nom: str):
        self.cfg.set_jeu_actif(nom)
        self.refresh()

    def on_copie_toggled(self):
        jeu = self._jeu()
        if jeu:
            self.cfg.set_copie_forcee(jeu["nom"], self.copie_var.get())

    def open_mods_folder(self):
        if self._jeu() is None:
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
        """Peut être appelé depuis n'importe quel thread : les messages passent par une file."""
        self._log_queue.put(str(message))

    def _write_log(self, message: str):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _drain_logs(self):
        """Affiche les messages en attente (thread de l'UI) et détecte la fin de l'opération."""
        termine = False
        try:
            while True:
                message = self._log_queue.get_nowait()
                if message is _FIN_TACHE:
                    termine = True
                    break
                self._write_log(message)
        except queue.Empty:
            pass
        if termine:
            self._end_task()
        else:
            self.after(LOG_INTERVAL_MS, self._drain_logs)

    def log_clear(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    # ------------------------------------------------- Déploiement / Purge
    def _run_task(self, titre: str, fonction):
        """Exécute fonction() dans un thread pour ne pas figer l'interface, en bloquant les autres actions."""
        self.busy = True
        for widget in self._action_widgets:
            widget.configure(state="disabled")
        self.lbl_status.configure(text=f"⏳ {titre} en cours, veuillez patienter...")
        self.log_clear()

        def worker():
            try:
                fonction()
            except Exception as e:
                self.log(f"[ERREUR INATTENDUE] {e}")
            finally:
                self._log_queue.put(_FIN_TACHE)

        threading.Thread(target=worker, name=titre, daemon=False).start()
        self.after(LOG_INTERVAL_MS, self._drain_logs)

    def _end_task(self):
        self.busy = False
        for widget in self._action_widgets:
            widget.configure(state="readonly" if widget is self.combo_jeu else "normal")
        self.refresh()

    def action_deploy(self):
        if self.busy:
            return
        jeu = self._jeu()
        if jeu is None:
            messagebox.showwarning("Erreur", "Veuillez configurer et sélectionner un jeu (onglet Paramètres).")
            return
        if not self.load_order:
            messagebox.showwarning("Erreur", "Aucun mod n'est dans la liste de déploiement.")
            return
        dossier_jeu = Path(jeu["dossier"])
        if not dossier_jeu.exists():
            messagebox.showerror("Erreur", "Le dossier du jeu spécifié n'existe pas.")
            return

        mods_dir, load_order = self._mods_dir(), list(self.load_order)
        copie_forcee = bool(jeu.get("copie_forcee"))

        def tache():
            self.log("=== LANCEMENT DU DÉPLOIEMENT ===")
            self.log(f"Jeu cible : {jeu['nom']} ({dossier_jeu})")
            if copie_forcee:
                self.log("Mode : copie réelle des fichiers (hard links désactivés)")
            deploy_mods(dossier_jeu, mods_dir, load_order, logger=self.log, copie_forcee=copie_forcee)

        self._run_task("Déploiement", tache)

    def action_purge(self):
        if self.busy:
            return
        jeu = self._jeu()
        if jeu is None:
            return
        dossier_jeu = Path(jeu["dossier"])
        if not dossier_jeu.exists():
            messagebox.showerror("Erreur", "Le dossier du jeu spécifié n'existe pas.")
            return
        if not messagebox.askyesno("Confirmation de Purge",
                                   f"Voulez-vous vraiment retirer tous les mods de « {jeu['nom']} » "
                                   "et restaurer le jeu à son état d'origine ?"):
            return

        def tache():
            self.log("=== LANCEMENT DE LA PURGE ===")
            purge_mods(dossier_jeu, logger=self.log)

        self._run_task("Purge", tache)
