import os
import sys
import webbrowser
from tkinter import messagebox

import customtkinter as ctk
import i18n
import theme
from core.config import ConfigManager
from i18n import t
from version import __version__
from views.mods_tab import ModsTab
from views.settings_tab import SettingsTab

DONATE_URL = "https://ko-fi.com/devcfk"


def resource_path(relative_path):
    """Return the absolute path of a resource, both from source and from the PyInstaller executable."""
    try:
        base_path = sys._MEIPASS  # type: ignore
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__) + "/../..")  # Go up to the project root

    return os.path.join(base_path, relative_path)


class App(ctk.CTk):
    def __init__(self, start_on_settings: bool = False):
        super().__init__()
        # Set when the language changes: run() then rebuilds the window in the new language
        self.restart_requested = False
        self.restart_on_settings = False

        self.title(f"ModInjector v{__version__}")
        self.geometry("920x760")
        self.minsize(850, 700)

        icon_path = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        self.cfg = ConfigManager()
        i18n.set_language(self.cfg.language)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Title banner ---
        header = ctk.CTkFrame(self, fg_color="transparent", border_width=0)
        header.grid(row=0, column=0, padx=20, pady=(10, 0), sticky="ew")
        title_bar = ctk.CTkFrame(header, fg_color="transparent", border_width=0)
        title_bar.pack(fill="x")
        ctk.CTkLabel(title_bar, text="⚡ MOD", text_color=theme.CYAN, font=theme.font(26, "bold")).pack(side="left")
        ctk.CTkLabel(title_bar, text="INJECTOR", text_color=theme.TEXT, font=theme.font(26, "bold")).pack(
            side="left", padx=(4, 0)
        )
        ctk.CTkLabel(title_bar, text=t("app.subtitle"), text_color=theme.TEXT_MUTED, font=theme.font(11)).pack(
            side="left", padx=(14, 0), pady=(10, 0)
        )
        self._build_language_menu(title_bar)
        ctk.CTkFrame(header, height=2, fg_color=theme.PRIMARY, border_width=0, corner_radius=0).pack(
            fill="x", pady=(4, 0)
        )

        self.tab_mods_name, self.tab_settings_name = t("tab.mods"), t("tab.settings")
        self.tabview = ctk.CTkTabview(
            self, command=self.on_tab_changed, border_width=1, segmented_button_fg_color=theme.PANEL
        )
        self.tabview._segmented_button.configure(font=theme.font(13, "bold"))
        self.tabview.grid(row=1, column=0, padx=15, pady=(6, 0), sticky="nsew")
        self.tab_mods = self.tabview.add(self.tab_mods_name)
        self.tab_settings = self.tabview.add(self.tab_settings_name)
        for tab in (self.tab_mods, self.tab_settings):
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)

        self.mods_view = ModsTab(self.tab_mods, self.cfg)
        self.mods_view.grid(row=0, column=0, sticky="nsew")
        self.settings_view = SettingsTab(
            self.tab_settings, self.cfg, on_change=self.mods_view.refresh, is_busy=lambda: self.mods_view.busy
        )
        self.settings_view.grid(row=0, column=0, sticky="nsew")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- Footer: donation link + version ---
        footer = ctk.CTkFrame(self, fg_color="transparent", border_width=0)
        footer.grid(row=2, column=0, sticky="ew", padx=15, pady=(2, 6))
        ctk.CTkButton(
            footer,
            text=t("app.support"),
            command=lambda: webbrowser.open(DONATE_URL),
            fg_color="transparent",
            hover_color=theme.PANEL_ALT,
            text_color=theme.CYAN,
            font=theme.font(11),
            width=0,
            height=24,
        ).pack(side="left")
        ctk.CTkLabel(footer, text=f"v{__version__}", text_color=theme.TEXT_MUTED, font=theme.font(10)).pack(
            side="right", padx=(0, 5)
        )

        # First launch: no game configured -> open the settings tab directly
        if start_on_settings or not self.cfg.games:
            self.tabview.set(self.tab_settings_name)

        if self.cfg.load_error:
            self.after(200, lambda: messagebox.showwarning(t("app.config_title"), self.cfg.load_error))

    def _build_language_menu(self, master):
        # Choice label -> language code ("auto" follows Windows)
        self._language_choices = {t("app.language_auto"): i18n.AUTO}
        self._language_choices.update({name: code for code, name in i18n.LANGUAGES.items()})
        self.language_var = ctk.StringVar(value=self._language_label(self.cfg.language))
        ctk.CTkOptionMenu(
            master,
            variable=self.language_var,
            values=list(self._language_choices),
            command=self.on_language_selected,
            width=150,
            fg_color=theme.PANEL,
            button_color=theme.PANEL_ALT,
            button_hover_color=theme.PRIMARY,
            dropdown_fg_color=theme.PANEL_ALT,
            dropdown_hover_color=theme.PRIMARY,
            font=theme.font(12),
        ).pack(side="right", pady=(6, 0))
        ctk.CTkLabel(master, text="🌐", font=theme.font(16)).pack(side="right", padx=(0, 6), pady=(6, 0))

    def _language_label(self, code: str) -> str:
        """Label of a language code in the selector (an unknown code shows as Auto)."""
        labels = {c: label for label, c in self._language_choices.items()}
        return labels.get(code, labels[i18n.AUTO])

    def on_language_selected(self, label: str):
        code = self._language_choices[label]
        if code == self.cfg.language:
            return
        if self.mods_view.busy:
            messagebox.showwarning(t("app.busy_title"), t("app.busy_settings"))
            self.language_var.set(self._language_label(self.cfg.language))
            return
        self.cfg.set_language(code)
        self.restart_requested = True
        self.restart_on_settings = self.tabview.get() == self.tab_settings_name
        # Cancel the pending timers (ours and customtkinter's): they would fire on destroyed widgets
        # (Tcl-level cancel: destroy() still unregisters their Python callbacks)
        for after_id in self.tk.splitlist(self.tk.call("after", "info")):
            self.tk.call("after", "cancel", after_id)
        self.destroy()

    def on_close(self):
        # Closing during a deployment would leave the game in an intermediate state
        if self.mods_view.busy:
            messagebox.showwarning(t("app.busy_title"), t("app.busy_close"))
            return
        self.destroy()

    def on_tab_changed(self):
        if self.tabview.get() == self.tab_settings_name:
            self.settings_view.refresh_info()
        else:
            self.mods_view.refresh()


def run():
    """Show the main window, rebuilding it when the language is changed."""
    theme.apply()
    start_on_settings = False
    while True:
        app = App(start_on_settings)
        app.mainloop()
        if not app.restart_requested:
            break
        start_on_settings = app.restart_on_settings


if __name__ == "__main__":
    run()
