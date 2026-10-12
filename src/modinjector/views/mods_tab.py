import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from core.config import ConfigManager
from core.deployer import deploy_mods, purge_mods, get_deployed_mods

POLL_INTERVAL_MS = 2000
AUCUN_JEU = "Aucun jeu"


class ModsTab(ctk.CTkFrame):
    """Onglet principal : sélection du jeu, gestion du load order, déploiement."""

    def __init__(self, master, cfg: ConfigManager):
        super().__init__(master, fg_color="transparent")
        self.cfg = cfg
        self.game_var = ctk.StringVar(value=AUCUN_JEU)
        self.load_order: list[str] = []
        self.available_mods: list[str] = []
        self._snapshot = None

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

        ctk.CTkLabel(top, text="Jeu :").grid(row=0, column=0, padx=10, pady=10)
        self.combo_jeu = ctk.CTkComboBox(top, variable=self.game_var, values=[AUCUN_JEU],
                                         state="readonly", command=self.on_game_selected)
        self.combo_jeu.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(top, text="🔄 Rafraîchir", width=110, command=self.refresh).grid(row=0, column=2, padx=5, pady=10)
        ctk.CTkButton(top, text="📂 Ouvrir Mods", width=110, command=self.open_mods_folder).grid(row=0, column=3, padx=(5, 10), pady=10)

        # --- Gestion du Load Order ---
        frame_mods = ctk.CTkFrame(self)
        frame_mods.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        frame_mods.grid_columnconfigure(0, weight=1)
        frame_mods.grid_columnconfigure(2, weight=1)
        frame_mods.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(frame_mods, text="Bibliothèque (hors liste de déploiement)", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, pady=(10, 5))
        self.list_available = self._make_listbox(frame_mods)
        self.list_available.grid(row=1, column=0, padx=(15, 5), pady=(0, 15), sticky="nsew")

        frame_transfer = ctk.CTkFrame(frame_mods, fg_color="transparent")
        frame_transfer.grid(row=1, column=1, padx=5)
        ctk.CTkButton(frame_transfer, text="Activer ►", width=90, command=self.activate_mod).pack(pady=5)
        ctk.CTkButton(frame_transfer, text="◄ Retirer", width=90, command=self.deactivate_mod,
                      fg_color="#7A3636", hover_color="#592525").pack(pady=5)

        ctk.CTkLabel(frame_mods, text="Ordre de Déploiement (Plus bas = Prioritaire)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, pady=(10, 5))
        self.list_active = self._make_listbox(frame_mods)
        self.list_active.grid(row=1, column=2, padx=5, pady=(0, 15), sticky="nsew")

        frame_order = ctk.CTkFrame(frame_mods, fg_color="transparent")
        frame_order.grid(row=1, column=3, padx=(0, 15))
        ctk.CTkButton(frame_order, text="▲ Monter", width=70, command=self.move_up).pack(pady=5)
        ctk.CTkButton(frame_order, text="▼ Descendre", width=70, command=self.move_down).pack(pady=5)

        # --- Actions principales ---
        frame_actions = ctk.CTkFrame(self)
        frame_actions.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        frame_actions.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(frame_actions, text="🚀 DÉPLOYER LES MODS", command=self.action_deploy,
                      fg_color="#2FA572", hover_color="#106A43", height=45,
                      font=ctk.CTkFont(weight="bold", size=14)).grid(row=0, column=0, padx=15, pady=15, sticky="ew")
        ctk.CTkButton(frame_actions, text="🧹 PURGER (JEU D'ORIGINE)", command=self.action_purge,
                      fg_color="#C22929", hover_color="#8F1515", height=45,
                      font=ctk.CTkFont(weight="bold", size=14)).grid(row=0, column=1, padx=15, pady=15, sticky="ew")

        # --- Logs ---
        frame_logs = ctk.CTkFrame(self)
        frame_logs.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        frame_logs.grid_columnconfigure(0, weight=1)
        frame_logs.grid_rowconfigure(0, weight=1)
        self.log_textbox = ctk.CTkTextbox(frame_logs, state="disabled", font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # --- Statut ---
        self.lbl_status = ctk.CTkLabel(self, text="", anchor="w")
        self.lbl_status.grid(row=4, column=0, padx=15, pady=(0, 5), sticky="ew")

    @staticmethod
    def _make_listbox(master) -> tk.Listbox:
        return tk.Listbox(master, bg="#2b2b2b", fg="white", selectbackground="#1f538d", borderwidth=0,
                          highlightthickness=1, font=("Arial", 11), exportselection=False)

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
        noms = self.cfg.noms_jeux()
        self.combo_jeu.configure(values=noms or [AUCUN_JEU])
        jeu = self._jeu()
        self.game_var.set(jeu["nom"] if jeu else AUCUN_JEU)

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
            if self._scan() != self._snapshot:
                self.refresh()
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
        if self._jeu() is None:
            return
        if not deployed:
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
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", str(message) + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")
        self.log_textbox.update()

    def log_clear(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    # ------------------------------------------------- Déploiement / Purge
    def action_deploy(self):
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

        self.log_clear()
        self.log("=== LANCEMENT DU DÉPLOIEMENT ===")
        self.log(f"Jeu cible : {jeu['nom']} ({dossier_jeu})")
        try:
            deploy_mods(dossier_jeu, self._mods_dir(), self.load_order, logger=self.log)
        except Exception as e:
            self.log(f"[ERREUR INATTENDUE] {e}")
        self.refresh()

    def action_purge(self):
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

        self.log_clear()
        self.log("=== LANCEMENT DE LA PURGE ===")
        try:
            purge_mods(dossier_jeu, logger=self.log)
        except Exception as e:
            self.log(f"[ERREUR INATTENDUE] {e}")
        self.refresh()
