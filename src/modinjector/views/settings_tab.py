import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import theme
from core.config import ConfigManager
from core.deployer import get_deployed_mods, is_deploy_interrupted, is_same_drive
from i18n import t


class SettingsTab(ctk.CTkFrame):
    """Settings tab: manages the list of games and shows an info sheet for each game."""

    def __init__(self, master, cfg: ConfigManager, on_change, is_busy=lambda: False):
        super().__init__(master, fg_color="transparent", border_width=0)
        self.cfg = cfg
        self.on_change = on_change  # called after any change to the list of games
        self.is_busy = is_busy  # true during a deployment / purge: games must not change
        self.name_var = ctk.StringVar()
        self.game_dir_var = ctk.StringVar()
        self.selected: str | None = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_ui()
        self.reload_list()

    def build_ui(self):
        # --- List of games (left) ---
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, padx=10, pady=10, sticky="nsw")
        left.grid_rowconfigure(1, weight=1)
        theme.section_label(left, t("settings.games")).grid(row=0, column=0, padx=10, pady=(10, 5))
        self.listbox = tk.Listbox(left, width=26, **theme.listbox_options())
        self.listbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        ctk.CTkButton(left, text=t("settings.new_game"), command=self.new_game).grid(
            row=2, column=0, padx=10, pady=(0, 10), sticky="ew"
        )

        # --- Details (right) ---
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="nsew")
        right.grid_columnconfigure(1, weight=1)
        right.grid_rowconfigure(5, weight=1)

        theme.section_label(right, t("settings.details")).grid(
            row=0, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="w"
        )

        ctk.CTkLabel(right, text=t("settings.name")).grid(row=1, column=0, padx=10, pady=5, sticky="w")
        ctk.CTkEntry(right, textvariable=self.name_var, placeholder_text=t("settings.name_placeholder")).grid(
            row=1, column=1, columnspan=2, padx=10, pady=5, sticky="ew"
        )

        ctk.CTkLabel(right, text=t("settings.folder")).grid(row=2, column=0, padx=10, pady=5, sticky="w")
        ctk.CTkEntry(right, textvariable=self.game_dir_var, placeholder_text=t("settings.folder_placeholder")).grid(
            row=2, column=1, padx=10, pady=5, sticky="ew"
        )
        ctk.CTkButton(
            right,
            text=t("settings.browse"),
            width=90,
            command=self.browse,
            fg_color="transparent",
            border_width=1,
            border_color=theme.CYAN,
            hover_color=theme.PANEL_ALT,
        ).grid(row=2, column=2, padx=10, pady=5)

        btns = ctk.CTkFrame(right, fg_color="transparent", border_width=0)
        btns.grid(row=3, column=0, columnspan=3, padx=10, pady=10, sticky="w")
        self.btn_save = ctk.CTkButton(btns, text=t("settings.save"), command=self.save_game)
        self.btn_save.pack(side="left", padx=(0, 10))
        self.btn_delete = ctk.CTkButton(
            btns,
            text=t("settings.delete"),
            command=self.delete_game,
            fg_color=theme.DANGER,
            hover_color=theme.DANGER_HOVER,
        )
        self.btn_delete.pack(side="left")

        theme.section_label(right, t("settings.info")).grid(
            row=4, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="w"
        )
        self.info_box = ctk.CTkTextbox(right, state="disabled", **{**theme.console_options(), "text_color": theme.CYAN})
        self.info_box.grid(row=5, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="nsew")

    # ----------------------------------------------------------- List
    def reload_list(self, select: str | None = None):
        self.listbox.delete(0, tk.END)
        names = self.cfg.game_names()
        for name in names:
            self.listbox.insert(tk.END, name)
        if select in names:
            idx = names.index(select)
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
        self.name_var.set("")
        self.game_dir_var.set("")
        self.btn_delete.configure(state="disabled")
        self._set_info(t("settings.new_game_hint"))

    def show_game(self, name: str):
        game = self.cfg.get_game(name)
        if game is None:
            return
        self.selected = name
        self.name_var.set(game["name"])
        self.game_dir_var.set(game["game_dir"])
        self.btn_delete.configure(state="normal")
        self._set_info(self._build_info(game))

    def _build_info(self, game: dict) -> str:
        game_dir = Path(game["game_dir"])
        mods_dir = self.cfg.mods_dir(game["name"])
        mods = sorted(p.name for p in mods_dir.iterdir() if p.is_dir()) if mods_dir.exists() else []
        deployed = get_deployed_mods(game_dir) if game_dir.exists() else []
        force_copy = bool(game.get("force_copy"))

        # (label, value) rows; the labels are aligned on the longest one in the current language
        game_rows = [
            (t("info.game_dir"), t("info.found") if game_dir.exists() else t("info.not_found")),
            (t("info.injection_mode"), t("info.mode_copy") if force_copy else t("info.mode_links")),
        ]
        if game_dir.exists():
            if is_same_drive(game_dir, mods_dir):
                same_drive = t("info.same_drive_yes")
            elif force_copy:
                same_drive = t("info.same_drive_no_copy")
            else:
                same_drive = t("info.same_drive_no")
            game_rows.append((t("info.same_drive"), same_drive))
        game_rows.append(
            (
                t("info.mods_in_game"),
                t("info.deployed_count", count=len(deployed)) if deployed else t("info.none_original"),
            )
        )
        if game_dir.exists() and is_deploy_interrupted(game_dir):
            game_rows.append((t("info.deploy_state"), t("info.interrupted")))
        library_rows = [
            (t("info.folder"), str(mods_dir)),
            (t("info.available"), str(len(mods))),
            (t("info.in_order"), t("info.in_order_value", count=len(game["load_order"]))),
        ]
        width = max(len(label) for label, _ in game_rows + library_rows)

        def rows(items):
            return [f"{label:<{width}} : {value}" for label, value in items]

        lines = [t("info.game_header"), *rows(game_rows), "", t("info.library_header"), *rows(library_rows), ""]
        if mods:
            statuses = {
                "deployed": t("info.status_deployed"),
                "pending": t("info.status_pending"),
                "off": t("info.status_off"),
            }
            status_width = max(len(s) for s in statuses.values())
            lines.append(t("info.detail"))
            for m in mods:
                if m in deployed:
                    status = statuses["deployed"]
                elif m in game["load_order"]:
                    status = statuses["pending"]
                else:
                    status = statuses["off"]
                lines.append(f"  {status:<{status_width}} {m}")
        else:
            lines.append(t("info.no_mods"))
        return "\n".join(lines)

    def _set_info(self, text: str):
        self.info_box.configure(state="normal")
        self.info_box.delete("1.0", "end")
        self.info_box.insert("end", text)
        self.info_box.configure(state="disabled")

    # --------------------------------------------------------- Actions
    def browse(self):
        game_dir = filedialog.askdirectory(title=t("settings.browse_title"))
        if game_dir:
            self.game_dir_var.set(game_dir)
            if not self.name_var.get().strip():
                self.name_var.set(Path(game_dir).name)

    def _refuse_if_busy(self) -> bool:
        if self.is_busy():
            messagebox.showwarning(t("app.busy_title"), t("app.busy_settings"))
            return True
        return False

    def save_game(self):
        if self._refuse_if_busy():
            return
        name, game_dir = self.name_var.get(), self.game_dir_var.get().strip()
        if self.selected is None:
            error = self.cfg.add_game(name, game_dir)
        else:
            error = self.cfg.update_game(self.selected, name, game_dir)
        if error:
            messagebox.showerror(t("common.error"), error)
            return
        self.reload_list(select=name.strip())
        self.on_change()

    def delete_game(self):
        if self.selected is None or self._refuse_if_busy():
            return
        if not messagebox.askyesno(
            t("settings.delete_title"),
            t("settings.delete_confirm", name=self.selected),
        ):
            return
        self.cfg.remove_game(self.selected)
        self.reload_list(select=self.cfg.active_game_name)
        self.on_change()

    def refresh_info(self):
        """Refresh the info sheet of the selected game (called when the tab is opened)."""
        if self.selected:
            self.show_game(self.selected)
