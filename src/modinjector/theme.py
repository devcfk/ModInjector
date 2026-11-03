"""ModInjector "gaming" theme: dark background, neon purple / cyan / magenta accents."""

import customtkinter as ctk

# --- Palette ---
BG = "#0B0D17"  # window background
PANEL = "#141829"  # frames
PANEL_ALT = "#1B2036"  # nested frames / hover
INPUT = "#0F1220"  # inputs, lists, consoles
BORDER = "#2A2F4A"
TEXT = "#E6E9FF"
TEXT_MUTED = "#7A80A8"

PRIMARY = "#7C3AED"  # electric purple
PRIMARY_HOVER = "#5B21B6"
CYAN = "#00E5FF"
CYAN_HOVER = "#00A8C0"
SUCCESS = "#00C46A"  # neon green (deploy)
SUCCESS_HOVER = "#00894A"
DANGER = "#E0115F"  # magenta (purge / delete)
DANGER_HOVER = "#A00C44"
DANGER_SOFT = "#8B1E4F"  # secondary destructive actions (remove)
DANGER_SOFT_HOVER = "#5E1435"
CONSOLE_TEXT = "#39FF14"  # terminal green

FONT_FAMILY = "Bahnschrift"  # "tech"-style Windows font (automatic fallback if missing)
MONO_FAMILY = "Consolas"


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def mono_font(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO_FAMILY, size=size)


def section_label(master, text: str) -> ctk.CTkLabel:
    """Upper-case section title in neon color."""
    return ctk.CTkLabel(master, text=text.upper(), text_color=CYAN, font=font(13, "bold"))


def listbox_options() -> dict:
    """Common tk.Listbox options (not handled by the customtkinter theme)."""
    return dict(
        bg=INPUT,
        fg=TEXT,
        selectbackground=PRIMARY,
        selectforeground="white",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=CYAN,
        borderwidth=0,
        activestyle="none",
        font=(FONT_FAMILY, 11),
        exportselection=False,
    )


def console_options() -> dict:
    """Terminal-like style for the log areas."""
    return dict(fg_color=INPUT, text_color=CONSOLE_TEXT, border_width=1, border_color=BORDER, font=mono_font())


def apply():
    """Apply the theme. Must be called before the first window is created."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    t = ctk.ThemeManager.theme

    t["CTk"]["fg_color"] = [BG, BG]
    t["CTkToplevel"]["fg_color"] = [BG, BG]
    t["CTkFrame"].update(
        corner_radius=4,
        border_width=1,
        fg_color=[PANEL, PANEL],
        top_fg_color=[PANEL_ALT, PANEL_ALT],
        border_color=[BORDER, BORDER],
    )
    t["CTkButton"].update(
        corner_radius=4,
        border_width=0,
        fg_color=[PRIMARY, PRIMARY],
        hover_color=[PRIMARY_HOVER, PRIMARY_HOVER],
        text_color=["white", "white"],
        text_color_disabled=[TEXT_MUTED, TEXT_MUTED],
    )
    t["CTkLabel"]["text_color"] = [TEXT, TEXT]
    t["CTkEntry"].update(
        corner_radius=4,
        border_width=1,
        fg_color=[INPUT, INPUT],
        border_color=[BORDER, BORDER],
        text_color=[TEXT, TEXT],
        placeholder_text_color=[TEXT_MUTED, TEXT_MUTED],
    )
    t["CTkComboBox"].update(
        corner_radius=4,
        border_width=1,
        fg_color=[INPUT, INPUT],
        border_color=[PRIMARY, PRIMARY],
        button_color=[PRIMARY, PRIMARY],
        button_hover_color=[PRIMARY_HOVER, PRIMARY_HOVER],
        text_color=[TEXT, TEXT],
        text_color_disabled=[TEXT_MUTED, TEXT_MUTED],
    )
    t["DropdownMenu"].update(fg_color=[PANEL_ALT, PANEL_ALT], hover_color=[PRIMARY, PRIMARY], text_color=[TEXT, TEXT])
    t["CTkSegmentedButton"].update(
        corner_radius=4,
        fg_color=[PANEL, PANEL],
        selected_color=[PRIMARY, PRIMARY],
        selected_hover_color=[PRIMARY_HOVER, PRIMARY_HOVER],
        unselected_color=[PANEL, PANEL],
        unselected_hover_color=[PANEL_ALT, PANEL_ALT],
        text_color=["white", "white"],
    )
    t["CTkTextbox"].update(
        corner_radius=4,
        fg_color=[INPUT, INPUT],
        text_color=[TEXT, TEXT],
        scrollbar_button_color=[BORDER, BORDER],
        scrollbar_button_hover_color=[PRIMARY, PRIMARY],
    )
    t["CTkCheckBox"].update(
        corner_radius=4,
        border_width=2,
        fg_color=[PRIMARY, PRIMARY],
        hover_color=[PRIMARY_HOVER, PRIMARY_HOVER],
        border_color=[CYAN, CYAN],
        checkmark_color=["white", "white"],
        text_color=[TEXT, TEXT],
        text_color_disabled=[TEXT_MUTED, TEXT_MUTED],
    )
    t["CTkScrollbar"].update(button_color=[BORDER, BORDER], button_hover_color=[PRIMARY, PRIMARY])
    t["CTkFont"].update(family=FONT_FAMILY, size=13)
