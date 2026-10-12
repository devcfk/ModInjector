from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

import customtkinter as ctk

from core.config import ConfigManager
from core.deployer import is_same_drive, get_deployed_mods


class SettingsTab(ctk.CTkFrame):
    """Onglet Paramètres : gestion de la liste des jeux et fiche d'information par jeu."""

    def __init__(self, master, cfg: ConfigManager, on_change):
        super().__init__(master, fg_color="transparent")
        self.cfg = cfg
        self.on_change = on_change  # appelé après toute modification de la liste des jeux
        self.nom_var = ctk.StringVar()
        self.dossier_var = ctk.StringVar()
        self.selected: str | None = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_ui()
        self.reload_list()

    def build_ui(self):
        # --- Liste des jeux (gauche) ---
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, padx=10, pady=10, sticky="nsw")
        left.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(left, text="Jeux configurés", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=(10, 5))
        self.listbox = tk.Listbox(left, bg="#2b2b2b", fg="white", selectbackground="#1f538d", borderwidth=0,
                                  highlightthickness=1, font=("Arial", 11), width=26, exportselection=False)
        self.listbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        ctk.CTkButton(left, text="➕ Nouveau jeu", command=self.new_game).grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")

        # --- Détails (droite) ---
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="nsew")
        right.grid_columnconfigure(1, weight=1)
        right.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(right, text="Détails du jeu", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="w")

        ctk.CTkLabel(right, text="Nom :").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        ctk.CTkEntry(right, textvariable=self.nom_var, placeholder_text="Ex: eFootball 2027").grid(row=1, column=1, columnspan=2, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(right, text="Dossier :").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        ctk.CTkEntry(right, textvariable=self.dossier_var, placeholder_text="Ex: C:/Jeux/MonJeu").grid(row=2, column=1, padx=10, pady=5, sticky="ew")
        ctk.CTkButton(right, text="Parcourir", width=90, command=self.browse).grid(row=2, column=2, padx=10, pady=5)

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.grid(row=3, column=0, columnspan=3, padx=10, pady=10, sticky="w")
        self.btn_save = ctk.CTkButton(btns, text="💾 Enregistrer", command=self.save_game)
        self.btn_save.pack(side="left", padx=(0, 10))
        self.btn_delete = ctk.CTkButton(btns, text="🗑 Supprimer", command=self.delete_game,
                                        fg_color="#C22929", hover_color="#8F1515")
        self.btn_delete.pack(side="left")

        ctk.CTkLabel(right, text="Informations", font=ctk.CTkFont(weight="bold")).grid(row=4, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="w")
        self.info_box = ctk.CTkTextbox(right, state="disabled", font=ctk.CTkFont(family="Consolas", size=12))
        self.info_box.grid(row=5, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="nsew")

    # ----------------------------------------------------------- Liste
    def reload_list(self, select: str | None = None):
        self.listbox.delete(0, tk.END)
        noms = self.cfg.noms_jeux()
        for nom in noms:
            self.listbox.insert(tk.END, nom)
        if select in noms:
            idx = noms.index(select)
            self.listbox.selection_set(idx)
            self.show_game(select)
        else:
            self.new_game()

    def on_select(self, _event=None):
        selection = self.listbox.curselection()
        if selection:
            self.show_game(self.listbox.get(selection[0]))

    def new_game(self):
        self.selected = None
        self.listbox.selection_clear(0, tk.END)
        self.nom_var.set("")
        self.dossier_var.set("")
        self.btn_delete.configure(state="disabled")
        self._set_info("Renseignez un nom et un dossier, puis cliquez sur Enregistrer pour ajouter le jeu.")

    def show_game(self, nom: str):
        jeu = self.cfg.get_jeu(nom)
        if jeu is None:
            return
        self.selected = nom
        self.nom_var.set(jeu["nom"])
        self.dossier_var.set(jeu["dossier"])
        self.btn_delete.configure(state="normal")
        self._set_info(self._build_info(jeu))

    def _build_info(self, jeu: dict) -> str:
        dossier = Path(jeu["dossier"])
        mods_dir = self.cfg.mods_dir(jeu["nom"])
        mods = sorted(p.name for p in mods_dir.iterdir() if p.is_dir()) if mods_dir.exists() else []
        deployed = get_deployed_mods(dossier) if dossier.exists() else []

        lignes = ["── JEU ──"]
        lignes.append(f"Dossier du jeu               : {'✔ trouvé' if dossier.exists() else '✘ INTROUVABLE'}")
        if dossier.exists():
            meme = is_same_drive(dossier, mods_dir)
            lignes.append(f"Même disque                  : {'✔ oui (hard links possibles)' if meme else '✘ NON — déplacez ModInjector sur le disque du jeu'}")
        lignes.append(f"Mods dans le jeu             : {len(deployed)} déployé(s)" if deployed else "Mods dans le jeu             : aucun (jeu d'origine)")

        lignes += [
            "",
            "── BIBLIOTHÈQUE DE MODS (pas encore dans le jeu) ──",
            f"Dossier                      : {mods_dir}",
            f"Mods disponibles             : {len(mods)}",
            f"Mods en liste de déploiement : {len(jeu['load_order'])} (seront injectés au prochain déploiement)",
            "",
        ]
        if mods:
            lignes.append("Détail :")
            for m in mods:
                if m in deployed:
                    etat = "✔ déployé dans le jeu"
                elif m in jeu["load_order"]:
                    etat = "⏳ en liste, à déployer"
                else:
                    etat = "· hors liste"
                lignes.append(f"  {etat:<24} {m}")
        else:
            lignes.append("Aucun mod : déposez vos mods dans le dossier ci-dessus.")
        return "\n".join(lignes)

    def _set_info(self, texte: str):
        self.info_box.configure(state="normal")
        self.info_box.delete("1.0", "end")
        self.info_box.insert("end", texte)
        self.info_box.configure(state="disabled")

    # --------------------------------------------------------- Actions
    def browse(self):
        dossier = filedialog.askdirectory(title="Sélectionner le dossier racine du jeu")
        if dossier:
            self.dossier_var.set(dossier)
            if not self.nom_var.get().strip():
                self.nom_var.set(Path(dossier).name)

    def save_game(self):
        nom, dossier = self.nom_var.get(), self.dossier_var.get().strip()
        if self.selected is None:
            erreur = self.cfg.ajouter_jeu(nom, dossier)
            cible = nom.strip()
        else:
            erreur = self.cfg.modifier_jeu(self.selected, nom, dossier)
            cible = nom.strip()
        if erreur:
            messagebox.showerror("Erreur", erreur)
            return
        self.reload_list(select=cible)
        self.on_change()

    def delete_game(self):
        if self.selected is None:
            return
        if not messagebox.askyesno(
            "Supprimer le jeu",
            f"Retirer « {self.selected} » de ModInjector ?\n\n"
            "Les fichiers du jeu et les mods dans le dossier Mods ne sont pas supprimés.\n"
            "Pensez à purger le jeu avant si des mods y sont encore déployés."):
            return
        self.cfg.supprimer_jeu(self.selected)
        self.reload_list(select=self.cfg.jeu_actif_nom)
        self.on_change()

    def refresh_info(self):
        """Rafraîchit la fiche du jeu sélectionné (appelé à l'ouverture de l'onglet)."""
        if self.selected:
            self.show_game(self.selected)
