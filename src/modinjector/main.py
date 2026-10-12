import gui

if __name__ == '__main__':
    # Lance l'interface graphique
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = gui.App()
    app.mainloop()