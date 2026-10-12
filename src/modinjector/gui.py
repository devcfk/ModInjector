import sys
import os

import customtkinter as ctk

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
        self.geometry("900x720")
        self.minsize(850, 680)

        icon_path = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        self.cfg = ConfigManager()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self, command=self.on_tab_changed)
        self.tabview.grid(row=0, column=0, padx=15, pady=(10, 0), sticky="nsew")
        self.tab_mods = self.tabview.add(TAB_MODS)
        self.tab_settings = self.tabview.add(TAB_SETTINGS)
        for tab in (self.tab_mods, self.tab_settings):
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)

        self.mods_view = ModsTab(self.tab_mods, self.cfg)
        self.mods_view.grid(row=0, column=0, sticky="nsew")
        self.settings_view = SettingsTab(self.tab_settings, self.cfg, on_change=self.mods_view.refresh)
        self.settings_view.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(self, text=f"v{__version__}", text_color="gray", font=ctk.CTkFont(size=10)).grid(
            row=1, column=0, sticky="e", padx=20, pady=(0, 8))

        # Premier lancement : aucun jeu configuré -> on ouvre directement les paramètres
        if not self.cfg.jeux:
            self.tabview.set(TAB_SETTINGS)

    def on_tab_changed(self):
        if self.tabview.get() == TAB_SETTINGS:
            self.settings_view.refresh_info()
        else:
            self.mods_view.refresh()


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
