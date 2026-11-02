import sys
import os
from tkinter import messagebox

import customtkinter as ctk

import theme
from core.config import ConfigManager
from version import __version__
from views.mods_tab import ModsTab
from views.settings_tab import SettingsTab

TAB_MODS = "Mods"
TAB_SETTINGS = "Paramètres"


def resource_path(relative_path):
    """ Récupère le chemin absolu, que ce soit en mode dev ou exécutable PyInstaller """
    try:
        base_path = sys._MEIPASS # type: ignore
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__) + "/../..") # Remonte à la racine du projet

    return os.path.join(base_path, relative_path)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"ModInjector v{__version__}")
        self.geometry("920x760")
        self.minsize(850, 700)

        icon_path = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        self.cfg = ConfigManager()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Bandeau titre ---
        header = ctk.CTkFrame(self, fg_color="transparent", border_width=0)
        header.grid(row=0, column=0, padx=20, pady=(10, 0), sticky="ew")
        titre = ctk.CTkFrame(header, fg_color="transparent", border_width=0)
        titre.pack(fill="x")
        ctk.CTkLabel(titre, text="⚡ MOD", text_color=theme.CYAN, font=theme.font(26, "bold")).pack(side="left")
        ctk.CTkLabel(titre, text="INJECTOR", text_color=theme.TEXT, font=theme.font(26, "bold")).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(titre, text="// GESTIONNAIRE DE MODS", text_color=theme.TEXT_MUTED,
                     font=theme.font(11)).pack(side="left", padx=(14, 0), pady=(10, 0))
        ctk.CTkFrame(header, height=2, fg_color=theme.PRIMARY, border_width=0, corner_radius=0).pack(fill="x", pady=(4, 0))

        self.tabview = ctk.CTkTabview(self, command=self.on_tab_changed, border_width=1,
                                      segmented_button_fg_color=theme.PANEL)
        self.tabview._segmented_button.configure(font=theme.font(13, "bold"))
        self.tabview.grid(row=1, column=0, padx=15, pady=(6, 0), sticky="nsew")
        self.tab_mods = self.tabview.add(TAB_MODS)
        self.tab_settings = self.tabview.add(TAB_SETTINGS)
        for tab in (self.tab_mods, self.tab_settings):
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)

        self.mods_view = ModsTab(self.tab_mods, self.cfg)
        self.mods_view.grid(row=0, column=0, sticky="nsew")
        self.settings_view = SettingsTab(self.tab_settings, self.cfg, on_change=self.mods_view.refresh,
                                         is_busy=lambda: self.mods_view.busy)
        self.settings_view.grid(row=0, column=0, sticky="nsew")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        ctk.CTkLabel(self, text=f"v{__version__}", text_color=theme.TEXT_MUTED, font=theme.font(10)).grid(
            row=2, column=0, sticky="e", padx=20, pady=(0, 8))

        # Premier lancement : aucun jeu configuré -> on ouvre directement les paramètres
        if not self.cfg.jeux:
            self.tabview.set(TAB_SETTINGS)

        if self.cfg.erreur_chargement:
            self.after(200, lambda: messagebox.showwarning("Configuration", self.cfg.erreur_chargement))

    def on_close(self):
        # Fermer pendant un déploiement laisserait le jeu dans un état intermédiaire
        if self.mods_view.busy:
            messagebox.showwarning("Opération en cours",
                                   "Un déploiement ou une purge est en cours.\nAttendez la fin avant de fermer ModInjector.")
            return
        self.destroy()

    def on_tab_changed(self):
        if self.tabview.get() == TAB_SETTINGS:
            self.settings_view.refresh_info()
        else:
            self.mods_view.refresh()


if __name__ == "__main__":
    theme.apply()
    app = App()
    app.mainloop()
