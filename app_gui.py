#!/usr/bin/env python3
"""
SGVA-Matchmaker — App de escritorio (Shameless Company).

Interfaz gráfica sobre el mismo pipeline de `main.py`: el aprendiz llena su perfil en
formularios, pulsa «Buscar vacantes» y obtiene, por cada convocatoria de su área, una hoja
de vida adaptada (PDF) y dos borradores de correo listos para copiar.

Software independiente de código abierto. NO es un producto oficial del SENA ni está
avalado, patrocinado o certificado por el Servicio Nacional de Aprendizaje.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from config import APP_NAME, DATA_HOME, RESOURCE_DIR, FROZEN
from modules import __version__
from modules.app_state import (
    PROGRAMAS_SENA,
    VERSION_AVISO,
    AjustesApp,
    AlmacenSecretos,
    cargar_perfil_o_vacio,
    format_educacion,
    format_experiencia,
    guardar_perfil,
    lineas,
    lista_comas,
    palabras_sugeridas,
    parse_educacion,
    parse_experiencia,
    problemas_perfil,
)
from modules.db import Database
from modules.utils import CANCELAR, Cancelado, setup_logging

log = logging.getLogger("app")

# --------------------------------------------------------------------- identidad visual
ACENTO = ("#C2185B", "#E0457B")
ACENTO_HOVER = ("#9C1449", "#C2185B")
SUAVE = ("gray40", "gray65")
TARJETA = ("gray96", "gray23")
VERDE, AMBAR, GRIS = ("#1B873F", "#3FB950"), ("#B7791F", "#E3B341"), ("gray50", "gray55")

AVISO_CORTO = "Software independiente de Shameless Company · NO es un producto oficial del SENA."

DESCARGO = (
    "Patronix es una iniciativa independiente de código abierto desarrollada por el "
    "colectivo Shameless Company.\n\n"
    "NO es un producto oficial del Servicio Nacional de Aprendizaje (SENA), ni está avalado, "
    "patrocinado, certificado ni respaldado de ninguna forma por el SENA, el SGVA o el portal "
    "Caprendizaje. «SENA», «SGVA» y «Caprendizaje» son marcas de su titular y se mencionan solo "
    "para describir con qué portal interactúa esta herramienta.\n\n"
    "Úsala de forma personal y responsable:\n"
    "•  Solo con TU propia cuenta, para consultar las convocatorias a las que ya tienes acceso.\n"
    "•  Respetando los términos de uso del portal Caprendizaje y la Ley 1581 de 2012.\n"
    "•  Sin compartir tu cuenta ni redistribuir los datos de las empresas.\n\n"
    "El SENA puede cambiar el portal o limitar el acceso automatizado. La información de las "
    "empresas proviene de fuentes públicas e inferencias automáticas que pueden ser incorrectas: "
    "verifica siempre en el portal oficial. Los correos y hojas de vida son borradores que "
    "debes revisar antes de enviar; la app nunca envía correos ni se postula por ti.\n\n"
    "Tu contraseña se guarda solo en este equipo (Administrador de credenciales de Windows) y "
    "únicamente se escribe en el formulario de inicio de sesión del portal del SENA.\n\n"
    "El software se entrega «tal cual», sin garantías, bajo licencia MIT."
)


def abrir_ruta(ruta: Path | str) -> None:
    """Abre un archivo o carpeta con la aplicación predeterminada del sistema."""
    ruta = str(ruta)
    try:
        if sys.platform == "win32":
            os.startfile(ruta)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", ruta])
        else:
            subprocess.Popen(["xdg-open", ruta])
    except OSError as exc:
        messagebox.showerror(APP_NAME, f"No se pudo abrir:\n{ruta}\n\n{exc}")


MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def fecha_legible(iso: str) -> str:
    """'2026-11-05' → '5 nov 2026' (si no es ISO, se devuelve tal cual)."""
    try:
        a, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {MESES_CORTOS[m - 1]} {a}"
    except (ValueError, IndexError):
        return iso


class ColaLogHandler(logging.Handler):
    """Envía los mensajes de log al hilo de la interfaz."""

    def __init__(self, cola: queue.Queue) -> None:
        super().__init__(logging.INFO)
        self.cola = cola
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("app", "modules", "main")) or record.levelno >= logging.WARNING:
            self.cola.put(("log", self.format(record), record.levelno))


# =============================================================================
# Ventanas auxiliares
# =============================================================================
class DialogoDescargo(ctk.CTkToplevel):
    """Aviso legal obligatorio en el primer uso."""

    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.aceptado = False
        self.title("Antes de empezar")
        self.geometry("640x620")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        ctk.CTkLabel(self, text="Descargo de responsabilidad institucional",
                     font=ctk.CTkFont(size=19, weight="bold")).pack(padx=24, pady=(22, 6), anchor="w")
        caja = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(size=13))
        caja.pack(fill="both", expand=True, padx=24, pady=6)
        caja.insert("1.0", DESCARGO)
        caja.configure(state="disabled")

        self.var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Leí y acepto estas condiciones de uso", variable=self.var,
                        command=self._toggle, fg_color=ACENTO, hover_color=ACENTO_HOVER
                        ).pack(padx=24, pady=(10, 4), anchor="w")
        fila = ctk.CTkFrame(self, fg_color="transparent")
        fila.pack(fill="x", padx=24, pady=(6, 20))
        ctk.CTkButton(fila, text="Salir", width=110, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray85"), command=self.destroy).pack(side="right")
        self.boton = ctk.CTkButton(fila, text="Continuar", width=140, state="disabled",
                                   fg_color=("gray70", "gray35"), hover_color=ACENTO_HOVER,
                                   command=self._aceptar)
        self.boton.pack(side="right", padx=8)
        self.after(50, self._modal)

    def _modal(self) -> None:
        self.lift()
        self.focus_force()
        self.grab_set()

    def _toggle(self) -> None:
        activo = self.var.get()
        self.boton.configure(state="normal" if activo else "disabled",
                             fg_color=ACENTO if activo else ("gray70", "gray35"))

    def _aceptar(self) -> None:
        self.aceptado = True
        self.destroy()


class DialogoProyecto(ctk.CTkToplevel):
    """Crear o editar un proyecto del portafolio."""

    def __init__(self, master: Any, proyecto: dict | None, al_guardar: Callable[[dict], None]) -> None:
        super().__init__(master)
        self.title("Proyecto")
        self.geometry("560x560")
        self.al_guardar = al_guardar
        p = proyecto or {}
        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True, padx=20, pady=16)
        cuerpo.grid_columnconfigure(0, weight=1)

        def etiqueta(texto: str, fila: int, ayuda: str = "") -> None:
            ctk.CTkLabel(cuerpo, text=texto, font=ctk.CTkFont(weight="bold")).grid(
                row=fila, column=0, sticky="w", pady=(8, 0))
            if ayuda:
                ctk.CTkLabel(cuerpo, text=ayuda, text_color=SUAVE, font=ctk.CTkFont(size=11)).grid(
                    row=fila, column=0, sticky="e", pady=(8, 0))

        etiqueta("Nombre del proyecto", 0)
        self.nombre = ctk.CTkEntry(cuerpo)
        self.nombre.grid(row=1, column=0, sticky="ew")
        self.nombre.insert(0, p.get("nombre", ""))
        etiqueta("¿Qué problema resuelve?", 2)
        self.descripcion = ctk.CTkTextbox(cuerpo, height=70, wrap="word")
        self.descripcion.grid(row=3, column=0, sticky="ew")
        self.descripcion.insert("1.0", p.get("descripcion", ""))
        etiqueta("Tecnologías", 4, "separadas por comas")
        self.tecnologias = ctk.CTkEntry(cuerpo, placeholder_text="Python, Django, PostgreSQL")
        self.tecnologias.grid(row=5, column=0, sticky="ew")
        if p.get("tecnologias"):
            self.tecnologias.insert(0, ", ".join(p["tecnologias"]))
        etiqueta("Logros medibles", 6, "uno por línea")
        self.logros = ctk.CTkTextbox(cuerpo, height=90, wrap="word")
        self.logros.grid(row=7, column=0, sticky="ew")
        self.logros.insert("1.0", "\n".join(p.get("logros", [])))
        etiqueta("Enlace (GitHub, demo…)", 8, "opcional")
        self.enlace = ctk.CTkEntry(cuerpo)
        self.enlace.grid(row=9, column=0, sticky="ew")
        self.enlace.insert(0, p.get("enlace", ""))

        fila = ctk.CTkFrame(cuerpo, fg_color="transparent")
        fila.grid(row=10, column=0, sticky="e", pady=(18, 0))
        ctk.CTkButton(fila, text="Cancelar", width=100, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray85"), command=self.destroy).pack(side="right")
        ctk.CTkButton(fila, text="Guardar proyecto", fg_color=ACENTO, hover_color=ACENTO_HOVER,
                      command=self._guardar).pack(side="right", padx=8)
        self.after(50, lambda: (self.lift(), self.grab_set(), self.nombre.focus()))

    def _guardar(self) -> None:
        nombre = self.nombre.get().strip()
        if not nombre:
            messagebox.showwarning(APP_NAME, "Ponle un nombre al proyecto.", parent=self)
            return
        self.al_guardar({
            "nombre": nombre,
            "descripcion": self.descripcion.get("1.0", "end").strip(),
            "tecnologias": lista_comas(self.tecnologias.get()),
            "logros": lineas(self.logros.get("1.0", "end")),
            "enlace": self.enlace.get().strip(),
        })
        self.destroy()


class DialogoEspera(ctk.CTkToplevel):
    """Ventana no bloqueante con instrucciones y un botón para continuar (calibración / login)."""

    def __init__(self, master: Any, titulo: str, texto: str, boton: str | None,
                 al_continuar: Callable[[], None] | None = None,
                 al_cancelar: Callable[[], None] | None = None) -> None:
        super().__init__(master)
        self.title(titulo)
        self.geometry("520x260")
        self.attributes("-topmost", True)
        self.al_cancelar = al_cancelar
        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(size=17, weight="bold")).pack(
            padx=22, pady=(20, 6), anchor="w")
        ctk.CTkLabel(self, text=texto, wraplength=470, justify="left").pack(padx=22, anchor="w")
        fila = ctk.CTkFrame(self, fg_color="transparent")
        fila.pack(side="bottom", fill="x", padx=22, pady=18)
        if al_cancelar:
            ctk.CTkButton(fila, text="Cancelar", width=100, fg_color="transparent", border_width=1,
                          text_color=("gray20", "gray85"), command=self._cancelar).pack(side="right")
        if boton and al_continuar:
            def continuar() -> None:
                al_continuar()
                self.destroy()
            ctk.CTkButton(fila, text=boton, fg_color=ACENTO, hover_color=ACENTO_HOVER,
                          command=continuar).pack(side="right", padx=8)
        else:
            ctk.CTkButton(fila, text="Entendido", width=110, command=self.destroy).pack(side="right", padx=8)

    def _cancelar(self) -> None:
        if self.al_cancelar:
            self.al_cancelar()
        self.destroy()


# =============================================================================
# Aplicación principal
# =============================================================================
class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.almacen = AlmacenSecretos()
        self.ajustes = AjustesApp.cargar(almacen=self.almacen)
        self.settings = self.ajustes.a_settings()
        setup_logging(self.settings.logs_dir)
        self.cola: queue.Queue = queue.Queue()
        logging.getLogger().addHandler(ColaLogHandler(self.cola))
        self.db = Database(self.settings.db_path)
        self.perfil = cargar_perfil_o_vacio(self.settings.perfil_path)
        self.trabajando = False
        self._evento_espera: threading.Event | None = None

        self.title(f"{APP_NAME} · Shameless Company")
        self.geometry("1120x780")
        self.minsize(940, 640)
        self._icono()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._encabezado()
        self.tabs = ctk.CTkTabview(self, segmented_button_selected_color=ACENTO,
                                   segmented_button_selected_hover_color=ACENTO_HOVER)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 6))
        self._tab_buscar(self.tabs.add("  Buscar vacantes  "))
        self._tab_perfil(self.tabs.add("  Mi perfil  "))
        self._tab_cuenta(self.tabs.add("  Cuenta y ajustes  "))
        self._tab_acerca(self.tabs.add("  Acerca de  "))
        self._pie()

        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.after(120, self._procesar_cola)
        self.after(300, self._inicio)

    # ------------------------------------------------------------------ estructura
    def ir_a(self, pestana: str) -> None:
        """Cambia de pestaña de forma segura. CTkTabview.set() oculta las demás pestañas con
        un after(100); si se llama dos veces seguidas, esa tarea puede ocultar la pestaña
        nueva. Re-seleccionarla un instante después lo corrige usando solo la API pública."""
        self.tabs.set(pestana)
        self.after(180, lambda: self.tabs.get() == pestana and self.tabs.set(pestana))

    def _icono(self) -> None:
        try:
            if sys.platform == "win32" and (RESOURCE_DIR / "assets" / "icon.ico").exists():
                self.iconbitmap(str(RESOURCE_DIR / "assets" / "icon.ico"))
            elif (RESOURCE_DIR / "assets" / "icon.png").exists():
                from tkinter import PhotoImage

                self._img_icono = PhotoImage(file=str(RESOURCE_DIR / "assets" / "icon.png"))
                self.iconphoto(True, self._img_icono)
        except Exception as exc:  # noqa: BLE001
            log.debug("Ícono no disponible: %s", exc)

    def _encabezado(self) -> None:
        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 4))
        ctk.CTkLabel(barra, text="Patronix", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        ctk.CTkLabel(barra, text="  by Shameless Company", text_color=ACENTO,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", pady=(6, 0))
        ctk.CTkLabel(barra, text="  NO OFICIAL DEL SENA  ", corner_radius=10, fg_color=("gray85", "gray25"),
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="right")

    def _pie(self) -> None:
        pie = ctk.CTkFrame(self, fg_color="transparent")
        pie.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        ctk.CTkLabel(pie, text=AVISO_CORTO, text_color=SUAVE, font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkLabel(pie, text=f"v{__version__}", text_color=SUAVE, font=ctk.CTkFont(size=11)).pack(side="right")

    # ------------------------------------------------------------------ pestaña Buscar
    def _tab_buscar(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        acciones = ctk.CTkFrame(tab, fg_color=TARJETA, corner_radius=12)
        acciones.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 10))
        acciones.grid_columnconfigure(1, weight=1)
        self.btn_buscar = ctk.CTkButton(
            acciones, text="Buscar vacantes", height=48, width=210, corner_radius=10,
            font=ctk.CTkFont(size=16, weight="bold"), fg_color=ACENTO, hover_color=ACENTO_HOVER,
            command=self.buscar)
        self.btn_buscar.grid(row=0, column=0, rowspan=2, padx=16, pady=16)
        self.lbl_estado = ctk.CTkLabel(acciones, text="Listo para buscar.", anchor="w",
                                       font=ctk.CTkFont(size=14))
        self.lbl_estado.grid(row=0, column=1, sticky="sew", padx=(0, 16), pady=(14, 2))
        self.barra = ctk.CTkProgressBar(acciones, progress_color=ACENTO)
        self.barra.grid(row=1, column=1, sticky="new", padx=(0, 16), pady=(4, 14))
        self.barra.set(0)
        self.btn_detener = ctk.CTkButton(acciones, text="Detener", width=100, state="disabled",
                                         fg_color="transparent", border_width=1,
                                         text_color=("gray20", "gray85"), command=self.detener)
        self.btn_detener.grid(row=0, column=2, rowspan=2, padx=(0, 16))

        cab = ctk.CTkFrame(tab, fg_color="transparent")
        cab.grid(row=1, column=0, sticky="ew", padx=6)
        self.lbl_resultados = ctk.CTkLabel(cab, text="Tus vacantes", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_resultados.pack(side="left")
        ctk.CTkButton(cab, text="Abrir carpeta de postulaciones", width=210, fg_color="transparent",
                      border_width=1, text_color=("gray20", "gray85"),
                      command=lambda: abrir_ruta(self.settings.output_dir)).pack(side="right")

        self.lista = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.lista.grid(row=2, column=0, sticky="nsew", padx=0, pady=(6, 6))
        self.lista.grid_columnconfigure(0, weight=1)

        self.var_log = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(tab, text="Ver registro detallado", variable=self.var_log,
                      command=self._toggle_log, progress_color=ACENTO).grid(row=3, column=0, sticky="w", padx=6)
        self.caja_log = ctk.CTkTextbox(tab, height=150, font=ctk.CTkFont(family="Consolas", size=12))
        self.caja_log.configure(state="disabled")
        self._pintar_resultados()

    def _toggle_log(self) -> None:
        if self.var_log.get():
            self.caja_log.grid(row=4, column=0, sticky="ew", padx=4, pady=(6, 0))
        else:
            self.caja_log.grid_forget()

    def _pintar_resultados(self, ranking: list[dict] | None = None) -> None:
        from modules.pipeline import leer_ranking

        for w in self.lista.winfo_children():
            w.destroy()
        filas = ranking if ranking is not None else leer_ranking(self.settings, self.db)
        self.lbl_resultados.configure(
            text=f"Tus vacantes ({len(filas)})" if filas else "Tus vacantes")
        if not filas:
            vacio = ctk.CTkFrame(self.lista, fg_color=TARJETA, corner_radius=12)
            vacio.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
            pasos = (
                "1.  Completa la pestaña «Mi perfil».\n"
                "2.  En «Cuenta y ajustes», escribe tu documento y contraseña de Caprendizaje.\n"
                "3.  Pulsa «Buscar vacantes». La primera vez puede abrirse el navegador para que "
                "completes el inicio de sesión."
            )
            ctk.CTkLabel(vacio, text="Aún no hay resultados", font=ctk.CTkFont(size=15, weight="bold")
                         ).pack(padx=20, pady=(18, 4), anchor="w")
            ctk.CTkLabel(vacio, text=pasos, justify="left", text_color=SUAVE).pack(padx=20, pady=(0, 18), anchor="w")
            return
        for i, r in enumerate(filas):
            self._tarjeta(i, r)

    def _tarjeta(self, fila: int, r: dict) -> None:
        card = ctk.CTkFrame(self.lista, fg_color=TARJETA, corner_radius=12)
        card.grid(row=fila, column=0, sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(1, weight=1)

        afinidad = float(r.get("afinidad", 0))
        color = VERDE if afinidad >= 60 else AMBAR if afinidad >= 30 else GRIS
        caja_af = ctk.CTkFrame(card, fg_color="transparent")
        caja_af.grid(row=0, column=0, rowspan=3, padx=(14, 8), pady=12, sticky="n")
        ctk.CTkLabel(caja_af, text=f"{afinidad:.0f}%", width=74, font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=color).pack()
        ctk.CTkLabel(caja_af, text="afinidad", text_color=SUAVE, font=ctk.CTkFont(size=11)).pack()

        ctk.CTkLabel(card, text=r.get("empresa", ""), anchor="w",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=1, sticky="sw", pady=(12, 0))
        detalle = "   ·   ".join(x for x in (
            r.get("ciudad"), r.get("sector") if r.get("sector") != "No determinado" else "",
            f"Cierra el {fecha_legible(r['fecha_limite'])}" if r.get("fecha_limite") else "") if x)
        if r.get("brechas"):
            detalle += f"\nPara reforzar: {', '.join(r['brechas'][:5])}"
        ctk.CTkLabel(card, text=detalle, anchor="w", justify="left", text_color=SUAVE
                     ).grid(row=1, column=1, sticky="nw", pady=(0, 6))

        botones = ctk.CTkFrame(card, fg_color="transparent")
        botones.grid(row=2, column=1, sticky="w", pady=(0, 12))
        carpeta = Path(r.get("carpeta", ""))

        def boton(texto: str, cmd: Callable[[], None], principal: bool = False) -> None:
            ctk.CTkButton(botones, text=texto, width=118, height=30, command=cmd,
                          fg_color=ACENTO if principal else "transparent",
                          hover_color=ACENTO_HOVER if principal else ("gray80", "gray30"),
                          border_width=0 if principal else 1,
                          text_color=None if principal else ("gray15", "gray90")).pack(side="left", padx=(0, 6))

        if r.get("pdf"):
            boton("Hoja de vida", lambda: abrir_ruta(r["pdf"]), principal=True)
        else:
            boton("Hoja de vida", lambda: abrir_ruta(carpeta / "hoja_de_vida.md"), principal=True)
        boton("Copiar correo", lambda: self._menu_correo(carpeta))
        if r.get("enlace"):
            boton("Ver vacante", lambda: webbrowser.open(r["enlace"]))
        boton("Carpeta", lambda: abrir_ruta(carpeta))

    def _menu_correo(self, carpeta: Path) -> None:
        ruta = carpeta / "correos.json"
        if not ruta.exists():
            messagebox.showinfo(APP_NAME, "Esta vacante aún no tiene correos generados.")
            return
        datos = json.loads(ruta.read_text("utf-8"))
        ventana = ctk.CTkToplevel(self)
        ventana.title(f"Correo para {datos.get('empresa', '')}")
        ventana.geometry("700x560")
        ctk.CTkLabel(ventana, text="Asunto", font=ctk.CTkFont(weight="bold")).pack(padx=18, pady=(16, 0), anchor="w")
        asunto = ctk.CTkEntry(ventana)
        asunto.pack(fill="x", padx=18)
        asunto.insert(0, datos.get("asunto", ""))
        selector = ctk.CTkSegmentedButton(ventana, values=["Versión corta", "Versión formal"],
                                          selected_color=ACENTO, selected_hover_color=ACENTO_HOVER)
        selector.pack(padx=18, pady=(12, 6), anchor="w")
        cuerpo = ctk.CTkTextbox(ventana, wrap="word", font=ctk.CTkFont(size=13))
        cuerpo.pack(fill="both", expand=True, padx=18)

        def mostrar(valor: str) -> None:
            cuerpo.delete("1.0", "end")
            cuerpo.insert("1.0", datos["version_corta" if valor == "Versión corta" else "version_formal"])

        selector.configure(command=mostrar)
        selector.set("Versión corta")
        mostrar("Versión corta")

        def copiar(texto: str, que: str) -> None:
            self.clipboard_clear()
            self.clipboard_append(texto)
            estado.configure(text=f"{que} copiado al portapapeles.")

        fila = ctk.CTkFrame(ventana, fg_color="transparent")
        fila.pack(fill="x", padx=18, pady=14)
        estado = ctk.CTkLabel(fila, text="Revísalo y ajústalo antes de enviarlo.", text_color=SUAVE)
        estado.pack(side="left")
        ctk.CTkButton(fila, text="Copiar texto", fg_color=ACENTO, hover_color=ACENTO_HOVER,
                      command=lambda: copiar(cuerpo.get("1.0", "end").strip(), "Texto")).pack(side="right")
        ctk.CTkButton(fila, text="Copiar asunto", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"),
                      command=lambda: copiar(asunto.get(), "Asunto")).pack(side="right", padx=8)
        ventana.after(50, ventana.lift)

    # ------------------------------------------------------------------ pestaña Perfil
    def _tab_perfil(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        marco = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure((0, 1), weight=1, uniform="col")
        self.campos: dict[str, Any] = {}
        p = self.perfil
        fila = 0

        def seccion(titulo: str, subtitulo: str = "") -> None:
            nonlocal fila
            ctk.CTkLabel(marco, text=titulo, font=ctk.CTkFont(size=16, weight="bold")).grid(
                row=fila, column=0, columnspan=2, sticky="w", padx=6, pady=(16 if fila else 4, 0))
            fila += 1
            if subtitulo:
                ctk.CTkLabel(marco, text=subtitulo, text_color=SUAVE, font=ctk.CTkFont(size=12)).grid(
                    row=fila, column=0, columnspan=2, sticky="w", padx=6)
                fila += 1

        def entrada(clave: str, etiqueta: str, col: int, placeholder: str = "") -> None:
            caja = ctk.CTkFrame(marco, fg_color="transparent")
            caja.grid(row=fila, column=col, sticky="ew", padx=6, pady=3)
            ctk.CTkLabel(caja, text=etiqueta, font=ctk.CTkFont(size=12)).pack(anchor="w")
            e = ctk.CTkEntry(caja, placeholder_text=placeholder)
            e.pack(fill="x")
            if p.get(clave):
                e.insert(0, p[clave])
            self.campos[clave] = e

        def texto(clave: str, etiqueta: str, valor: str, alto: int = 80, ayuda: str = "") -> None:
            nonlocal fila
            caja = ctk.CTkFrame(marco, fg_color="transparent")
            caja.grid(row=fila, column=0, columnspan=2, sticky="ew", padx=6, pady=3)
            enc = ctk.CTkFrame(caja, fg_color="transparent")
            enc.pack(fill="x")
            ctk.CTkLabel(enc, text=etiqueta, font=ctk.CTkFont(size=12)).pack(side="left")
            if ayuda:
                ctk.CTkLabel(enc, text=ayuda, text_color=SUAVE, font=ctk.CTkFont(size=11)).pack(side="right")
            t = ctk.CTkTextbox(caja, height=alto, wrap="word")
            t.pack(fill="x")
            t.insert("1.0", valor)
            self.campos[clave] = t
            fila += 1

        seccion("Datos personales", "Aparecen en el encabezado de tu hoja de vida.")
        entrada("nombre", "Nombre completo *", 0)
        entrada("titulo", "Título profesional", 1, "Aprendiz Tecnólogo en ADSO")
        fila += 1
        entrada("email", "Correo electrónico *", 0, "tu.correo@gmail.com")
        entrada("telefono", "Teléfono", 1, "+57 300 000 0000")
        fila += 1
        entrada("ciudad", "Ciudad", 0, "Bucaramanga, Santander")
        entrada("disponibilidad", "Disponibilidad", 1, "Inmediata")
        fila += 1
        entrada("linkedin", "LinkedIn", 0, "linkedin.com/in/…")
        entrada("github", "GitHub", 1, "github.com/…")
        fila += 1
        entrada("portafolio", "Portafolio / sitio web", 0, "https://…")
        entrada("programa_sena", "Programa SENA *", 1, "Tecnólogo en Análisis y Desarrollo de Software")
        fila += 1

        seccion("Perfil y habilidades")
        texto("resumen", "Resumen profesional (2–3 frases)", p.get("resumen", ""), 70)
        hab = p.get("habilidades", {})
        texto("tecnicas", "Habilidades técnicas *", ", ".join(hab.get("tecnicas", [])), 60,
              "separadas por comas · ej.: Python (Django), React, MySQL, Git")
        texto("blandas", "Habilidades blandas", ", ".join(hab.get("blandas", [])), 44, "separadas por comas")

        seccion("Proyectos", "La app los reordena según lo que pide cada vacante. Detalla bien sus tecnologías.")
        self.proyectos: list[dict] = list(p.get("proyectos", []))
        self.marco_proyectos = ctk.CTkFrame(marco, fg_color="transparent")
        self.marco_proyectos.grid(row=fila, column=0, columnspan=2, sticky="ew", padx=6)
        self.marco_proyectos.grid_columnconfigure(0, weight=1)
        fila += 1
        ctk.CTkButton(marco, text="+ Agregar proyecto", width=160, fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"), command=lambda: self._editar_proyecto(None)
                      ).grid(row=fila, column=0, sticky="w", padx=6, pady=6)
        fila += 1
        self._pintar_proyectos()

        seccion("Experiencia y formación")
        texto("experiencia", "Experiencia laboral", format_experiencia(p.get("experiencia", [])), 60,
              "una por línea: Cargo | Empresa | Periodo | logro 1; logro 2")
        texto("educacion", "Formación", format_educacion(p.get("educacion", [])), 60,
              "una por línea: Título | Institución | Periodo")
        texto("certificaciones", "Certificaciones", "\n".join(p.get("certificaciones", [])), 50, "una por línea")
        texto("idiomas", "Idiomas", "\n".join(p.get("idiomas", [])), 44, "uno por línea · ej.: Inglés (B1)")

        pie = ctk.CTkFrame(tab, fg_color="transparent")
        pie.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        self.lbl_perfil = ctk.CTkLabel(pie, text="", text_color=SUAVE)
        self.lbl_perfil.pack(side="left", padx=6)
        ctk.CTkButton(pie, text="Guardar perfil", width=160, fg_color=ACENTO, hover_color=ACENTO_HOVER,
                      command=self.guardar_perfil).pack(side="right", padx=6)
        ctk.CTkButton(pie, text="Ver ejemplo", width=110, fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"),
                      command=lambda: abrir_ruta(RESOURCE_DIR / "data" / "perfil_aprendiz.example.json")
                      ).pack(side="right")

    def _pintar_proyectos(self) -> None:
        for w in self.marco_proyectos.winfo_children():
            w.destroy()
        if not self.proyectos:
            ctk.CTkLabel(self.marco_proyectos, text="Sin proyectos todavía.", text_color=SUAVE).grid(
                row=0, column=0, sticky="w", pady=4)
        for i, pr in enumerate(self.proyectos):
            card = ctk.CTkFrame(self.marco_proyectos, fg_color=TARJETA, corner_radius=10)
            card.grid(row=i, column=0, sticky="ew", pady=3)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=pr.get("nombre", ""), font=ctk.CTkFont(weight="bold"), anchor="w").grid(
                row=0, column=0, sticky="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(card, text=", ".join(pr.get("tecnologias", [])) or "sin tecnologías",
                         text_color=SUAVE, anchor="w").grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))
            ctk.CTkButton(card, text="Editar", width=70, height=26, fg_color="transparent", border_width=1,
                          text_color=("gray15", "gray90"),
                          command=lambda i=i: self._editar_proyecto(i)).grid(row=0, column=1, rowspan=2, padx=4)
            ctk.CTkButton(card, text="Quitar", width=70, height=26, fg_color="transparent", border_width=1,
                          text_color=("gray15", "gray90"),
                          command=lambda i=i: self._quitar_proyecto(i)).grid(row=0, column=2, rowspan=2,
                                                                             padx=(4, 12))

    def _editar_proyecto(self, indice: int | None) -> None:
        def guardar(nuevo: dict) -> None:
            if indice is None:
                self.proyectos.append(nuevo)
            else:
                self.proyectos[indice] = nuevo
            self._pintar_proyectos()
            self.lbl_perfil.configure(text="Cambios sin guardar.")

        DialogoProyecto(self, None if indice is None else self.proyectos[indice], guardar)

    def _quitar_proyecto(self, indice: int) -> None:
        if messagebox.askyesno(APP_NAME, f"¿Quitar «{self.proyectos[indice].get('nombre')}»?"):
            del self.proyectos[indice]
            self._pintar_proyectos()
            self.lbl_perfil.configure(text="Cambios sin guardar.")

    def _leer_formulario_perfil(self) -> dict:
        def val(clave: str) -> str:
            w = self.campos[clave]
            return (w.get("1.0", "end") if isinstance(w, ctk.CTkTextbox) else w.get()).strip()

        perfil = dict(self.perfil)
        for clave in ("nombre", "titulo", "email", "telefono", "ciudad", "disponibilidad",
                      "linkedin", "github", "portafolio", "programa_sena", "resumen"):
            perfil[clave] = val(clave)
        perfil["habilidades"] = {"tecnicas": lista_comas(val("tecnicas")),
                                 "blandas": lista_comas(val("blandas"))}
        perfil["proyectos"] = self.proyectos
        perfil["experiencia"] = parse_experiencia(val("experiencia"))
        perfil["educacion"] = parse_educacion(val("educacion"))
        perfil["certificaciones"] = lineas(val("certificaciones"))
        perfil["idiomas"] = lineas(val("idiomas"))
        return perfil

    def guardar_perfil(self, silencioso: bool = False) -> bool:
        self.perfil = self._leer_formulario_perfil()
        guardar_perfil(self.perfil, self.settings.perfil_path)
        faltan = problemas_perfil(self.perfil)
        if faltan:
            self.lbl_perfil.configure(text=f"Guardado. Falta: {', '.join(faltan)}.")
        else:
            self.lbl_perfil.configure(text="Perfil guardado.")
        if not silencioso and not faltan:
            log.info("Perfil guardado.")
        return not faltan

    # ------------------------------------------------------------------ pestaña Cuenta
    def _tab_cuenta(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        marco = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(1, weight=1)
        a = self.ajustes
        self.w: dict[str, Any] = {}
        fila = 0

        def seccion(titulo: str, sub: str = "") -> None:
            nonlocal fila
            ctk.CTkLabel(marco, text=titulo, font=ctk.CTkFont(size=16, weight="bold")).grid(
                row=fila, column=0, columnspan=3, sticky="w", padx=6, pady=(16 if fila else 4, 0))
            fila += 1
            if sub:
                ctk.CTkLabel(marco, text=sub, text_color=SUAVE, font=ctk.CTkFont(size=12), justify="left",
                             wraplength=820).grid(row=fila, column=0, columnspan=3, sticky="w", padx=6)
                fila += 1

        def campo(clave: str, etiqueta: str, valor: str, secreto: bool = False, placeholder: str = "") -> Any:
            nonlocal fila
            ctk.CTkLabel(marco, text=etiqueta).grid(row=fila, column=0, sticky="w", padx=(6, 12), pady=4)
            e = ctk.CTkEntry(marco, show="•" if secreto else "", placeholder_text=placeholder)
            e.grid(row=fila, column=1, sticky="ew", pady=4)
            if valor:
                e.insert(0, valor)
            self.w[clave] = e
            if secreto:
                def alternar(e: ctk.CTkEntry = e) -> None:
                    e.configure(show="" if e.cget("show") else "•")
                ctk.CTkButton(marco, text="Ver", width=54, fg_color="transparent", border_width=1,
                              text_color=("gray15", "gray90"), command=alternar).grid(row=fila, column=2, padx=6)
            fila += 1
            return e

        seccion("Cuenta de Caprendizaje",
                "Tu contraseña se guarda solo en este equipo, en el Administrador de credenciales de "
                "Windows, y únicamente se escribe en el formulario de inicio de sesión del portal del "
                "SENA. Puedes dejarla vacía e iniciar sesión tú mismo en el navegador.")
        campo("sena_user", "Número de documento", a.sena_user)
        campo("sena_password", "Contraseña", a.sena_password, secreto=True)
        self.var_recordar = ctk.BooleanVar(value=a.recordar_secretos)
        ctk.CTkCheckBox(marco, text=f"Recordar contraseñas y claves en este equipo ({self.almacen.nombre})",
                        variable=self.var_recordar, fg_color=ACENTO, hover_color=ACENTO_HOVER
                        ).grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1

        seccion("Qué buscar")
        ctk.CTkLabel(marco, text="Programa de formación").grid(row=fila, column=0, sticky="w", padx=(6, 12), pady=4)
        self.w["programa"] = ctk.CTkComboBox(marco, values=PROGRAMAS_SENA, command=self._programa_cambiado)
        self.w["programa"].set(a.programa_formacion)
        self.w["programa"].grid(row=fila, column=1, sticky="ew", pady=4)
        fila += 1
        campo("palabras", "Palabras clave del área", a.palabras_clave, placeholder="software, desarrollo, …")
        campo("url", "Página de convocatorias", a.sgva_vacantes_url,
              placeholder="Se detecta con el asistente de abajo")
        fila_asistente = ctk.CTkFrame(marco, fg_color="transparent")
        fila_asistente.grid(row=fila, column=1, sticky="w", pady=(2, 4))
        self.btn_calibrar = ctk.CTkButton(fila_asistente, text="Detectar la página automáticamente",
                                          fg_color=ACENTO, hover_color=ACENTO_HOVER, command=self.calibrar)
        self.btn_calibrar.pack(side="left")
        ctk.CTkLabel(fila_asistente, text="  Recomendado la primera vez.", text_color=SUAVE).pack(side="left")
        fila += 1

        seccion("Navegador")
        ctk.CTkLabel(marco, text="Usar").grid(row=fila, column=0, sticky="w", padx=(6, 12), pady=4)
        self.nav_opciones = {"Microsoft Edge (recomendado)": "msedge", "Google Chrome": "chrome"}
        if not FROZEN:
            self.nav_opciones["Chromium de Playwright"] = ""
        self.w["navegador"] = ctk.CTkOptionMenu(marco, values=list(self.nav_opciones),
                                                fg_color=ACENTO, button_color=ACENTO_HOVER)
        self.w["navegador"].set(next((k for k, v in self.nav_opciones.items() if v == a.navegador),
                                     "Microsoft Edge (recomendado)"))
        self.w["navegador"].grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1
        self.var_mostrar = ctk.BooleanVar(value=a.mostrar_navegador)
        ctk.CTkCheckBox(marco, text="Mostrar el navegador mientras busca", variable=self.var_mostrar,
                        fg_color=ACENTO, hover_color=ACENTO_HOVER).grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1

        seccion("Redacción con IA (opcional)",
                "Sin clave, los correos se redactan con plantillas. Con una clave tuya de Gemini u OpenAI "
                "quedan más personalizados. A la IA solo se envía tu perfil profesional y datos públicos "
                "de la empresa, nunca tu contraseña.")
        ctk.CTkLabel(marco, text="Proveedor").grid(row=fila, column=0, sticky="w", padx=(6, 12), pady=4)
        self.ia_opciones = {"Ninguno (plantillas)": "ninguno", "Google Gemini": "gemini", "OpenAI": "openai"}
        self.w["ia"] = ctk.CTkOptionMenu(marco, values=list(self.ia_opciones),
                                         fg_color=ACENTO, button_color=ACENTO_HOVER)
        self.w["ia"].set(next((k for k, v in self.ia_opciones.items() if v == a.llm_provider),
                              "Ninguno (plantillas)"))
        self.w["ia"].grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1
        campo("gemini", "Clave de Gemini", a.gemini_api_key, secreto=True, placeholder="aistudio.google.com/apikey")
        campo("openai", "Clave de OpenAI", a.openai_api_key, secreto=True)

        seccion("Alertas por Telegram (opcional)",
                "Crea un bot con @BotFather, escríbele un mensaje y pega aquí su token y tu chat ID.")
        campo("tg_token", "Token del bot", a.telegram_token, secreto=True)
        campo("tg_chat", "Chat ID", a.telegram_chat_id)

        seccion("Tus datos en este equipo")
        info = (f"Datos privados (base de datos, sesión): {DATA_HOME}\n"
                f"Postulaciones generadas: {self.settings.output_dir}")
        ctk.CTkLabel(marco, text=info, justify="left", text_color=SUAVE).grid(
            row=fila, column=0, columnspan=3, sticky="w", padx=6)
        fila += 1
        fila_datos = ctk.CTkFrame(marco, fg_color="transparent")
        fila_datos.grid(row=fila, column=0, columnspan=3, sticky="w", padx=6, pady=6)
        for texto_b, cmd in (("Abrir carpeta de datos", lambda: abrir_ruta(DATA_HOME)),
                             ("Cerrar sesión del portal", self.borrar_sesion),
                             ("Selectores del portal (avanzado)", self.abrir_selectores)):
            ctk.CTkButton(fila_datos, text=texto_b, fg_color="transparent", border_width=1,
                          text_color=("gray15", "gray90"), command=cmd).pack(side="left", padx=(0, 8))

        pie = ctk.CTkFrame(tab, fg_color="transparent")
        pie.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        self.lbl_ajustes = ctk.CTkLabel(pie, text="", text_color=SUAVE)
        self.lbl_ajustes.pack(side="left", padx=6)
        ctk.CTkButton(pie, text="Guardar ajustes", width=160, fg_color=ACENTO, hover_color=ACENTO_HOVER,
                      command=self.guardar_ajustes).pack(side="right", padx=6)

    def _programa_cambiado(self, programa: str) -> None:
        self.w["palabras"].delete(0, "end")
        self.w["palabras"].insert(0, palabras_sugeridas(programa))

    def guardar_ajustes(self, silencioso: bool = False) -> None:
        a = self.ajustes
        a.sena_user = self.w["sena_user"].get().strip()
        a.sena_password = self.w["sena_password"].get()
        a.recordar_secretos = self.var_recordar.get()
        a.programa_formacion = self.w["programa"].get().strip()
        a.palabras_clave = self.w["palabras"].get().strip() or palabras_sugeridas(a.programa_formacion)
        a.sgva_vacantes_url = self.w["url"].get().strip()
        a.navegador = self.nav_opciones.get(self.w["navegador"].get(), "msedge")
        a.mostrar_navegador = self.var_mostrar.get()
        a.llm_provider = self.ia_opciones.get(self.w["ia"].get(), "ninguno")
        a.gemini_api_key = self.w["gemini"].get().strip()
        a.openai_api_key = self.w["openai"].get().strip()
        a.telegram_token = self.w["tg_token"].get().strip()
        a.telegram_chat_id = self.w["tg_chat"].get().strip()
        ok = a.guardar(almacen=self.almacen)
        self.settings = a.a_settings()
        if not ok and a.recordar_secretos:
            self.lbl_ajustes.configure(
                text="Guardado, pero las contraseñas solo se recordarán mientras la app esté abierta.")
        else:
            self.lbl_ajustes.configure(text="Ajustes guardados.")
        if not silencioso:
            log.info("Ajustes guardados.")

    def borrar_sesion(self) -> None:
        if self.settings.session_path.exists():
            self.settings.session_path.unlink()
            messagebox.showinfo(APP_NAME, "Sesión del portal eliminada de este equipo.")
        else:
            messagebox.showinfo(APP_NAME, "No hay ninguna sesión guardada.")

    def abrir_selectores(self) -> None:
        destino = self.settings.selectors_usuario_path
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(self.settings.selectors_path.read_text("utf-8"), "utf-8")
        messagebox.showinfo(APP_NAME, "Se abrirá el archivo de selectores. Solo modifícalo si el portal "
                                      "cambió y sabes lo que haces; los cambios aplican en la próxima búsqueda.")
        abrir_ruta(destino)

    # ------------------------------------------------------------------ pestaña Acerca de
    def _tab_acerca(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(tab, text=f"Patronix v{__version__} · Shameless Company",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 8))
        caja = ctk.CTkTextbox(tab, wrap="word", font=ctk.CTkFont(size=13))
        caja.grid(row=1, column=0, sticky="nsew", padx=4)
        caja.insert("1.0", "DESCARGO DE RESPONSABILIDAD INSTITUCIONAL\n\n" + DESCARGO)
        caja.configure(state="disabled")
        fila = ctk.CTkFrame(tab, fg_color="transparent")
        fila.grid(row=2, column=0, sticky="w", pady=8)
        ctk.CTkButton(fila, text="Portal oficial del SENA", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"),
                      command=lambda: webbrowser.open("https://www.sena.edu.co")).pack(side="left", padx=4)
        ctk.CTkButton(fila, text="Diagnóstico del equipo", fg_color=ACENTO, hover_color=ACENTO_HOVER,
                      command=self.diagnostico).pack(side="left", padx=4)
        ctk.CTkButton(fila, text="Ver registro (log)", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"),
                      command=lambda: abrir_ruta(self.settings.logs_dir / "matchmaker.log")).pack(side="left", padx=4)

    # ------------------------------------------------------------------ ciclo de vida
    def _inicio(self) -> None:
        if self.ajustes.aviso_aceptado < VERSION_AVISO:
            dialogo = DialogoDescargo(self)
            self.wait_window(dialogo)
            if not dialogo.aceptado:
                self.destroy()
                return
            self.ajustes.aviso_aceptado = VERSION_AVISO
            self.ajustes.guardar(almacen=self.almacen)
        if not self.perfil.get("nombre"):
            self.ir_a("  Mi perfil  ")
            self.lbl_perfil.configure(text="Empieza llenando tu perfil. Los campos con * son obligatorios.")

    def _cerrar(self) -> None:
        if self.trabajando and not messagebox.askyesno(
                APP_NAME, "Hay una búsqueda en curso. ¿Detenerla y salir?"):
            return
        CANCELAR.set()
        if self._evento_espera:
            self._evento_espera.set()
        self.destroy()

    # ------------------------------------------------------------------ trabajo en segundo plano
    def _ocupado(self, si: bool) -> None:
        self.trabajando = si
        self.btn_buscar.configure(state="disabled" if si else "normal")
        self.btn_calibrar.configure(state="disabled" if si else "normal")
        self.btn_detener.configure(state="normal" if si else "disabled")

    def _en_hilo(self, tipo: str, funcion: Callable[[], Any]) -> None:
        CANCELAR.clear()
        self._ocupado(True)

        def correr() -> None:
            try:
                self.cola.put(("fin", tipo, funcion(), None))
            except Cancelado:
                self.cola.put(("fin", tipo, None, "cancelado"))
            except Exception as exc:  # noqa: BLE001
                log.exception("Error en %s", tipo)
                self.cola.put(("fin", tipo, None, str(exc) or type(exc).__name__))

        threading.Thread(target=correr, daemon=True, name=tipo).start()

    def _aviso_desde_hilo(self, mensaje: str) -> None:
        self.cola.put(("aviso", mensaje))

    def buscar(self) -> None:
        self.guardar_ajustes(silencioso=True)
        completo = self.guardar_perfil(silencioso=True)
        if not completo:
            self.ir_a("  Mi perfil  ")
            messagebox.showwarning(APP_NAME, "Completa tu perfil antes de buscar.\n\n"
                                   + self.lbl_perfil.cget("text"))
            return
        if not self.settings.sena_user or not self.settings.sena_password:
            if not messagebox.askyesno(
                    APP_NAME, "No escribiste tu documento o contraseña de Caprendizaje.\n\n"
                              "Se abrirá el navegador para que inicies sesión tú mismo. ¿Continuar?"):
                return
        from modules.pipeline import busqueda_completa

        s, db = self.settings, self.db
        self.barra.set(0)
        self._en_hilo("buscar", lambda: busqueda_completa(
            s, db, aviso=self._aviso_desde_hilo,
            progreso=lambda etapa, f: self.cola.put(("progreso", etapa, f))))

    def calibrar(self) -> None:
        self.guardar_ajustes(silencioso=True)
        from modules.scraper import run_calibracion

        evento = threading.Event()
        self._evento_espera = evento

        def esperar() -> None:
            self.cola.put(("calibrar_espera", evento))
            evento.wait()

        s = self.settings
        self.lbl_estado.configure(text="Asistente: sigue las instrucciones de la ventana emergente.")
        self.ir_a("  Buscar vacantes  ")
        self._en_hilo("calibrar", lambda: run_calibracion(s, esperar, aviso=self._aviso_desde_hilo))

    def diagnostico(self) -> None:
        from modules import diagnostico

        self.guardar_ajustes(silencioso=True)
        s = self.settings
        self.lbl_estado.configure(text="Revisando el navegador, el PDF y la conexión…")

        def correr() -> list:
            chequeos = diagnostico.ejecutar(s)
            diagnostico.guardar_reporte(chequeos)
            return chequeos

        self._en_hilo("diagnostico", correr)

    def detener(self) -> None:
        CANCELAR.set()
        if self._evento_espera:
            self._evento_espera.set()
        self.lbl_estado.configure(text="Deteniendo… (termina el paso en curso)")
        self.btn_detener.configure(state="disabled")

    def _procesar_cola(self) -> None:
        try:
            while True:
                msg = self.cola.get_nowait()
                tipo = msg[0]
                if tipo == "log":
                    self._escribir_log(msg[1], msg[2])
                elif tipo == "progreso":
                    self.lbl_estado.configure(text=msg[1])
                    self.barra.set(max(0.0, min(1.0, msg[2])))
                elif tipo == "aviso":
                    titulo, _, cuerpo = msg[1].partition("\n")
                    DialogoEspera(self, titulo.capitalize() if cuerpo else "Acción requerida",
                                  cuerpo or titulo, None)
                elif tipo == "calibrar_espera":
                    evento: threading.Event = msg[1]
                    DialogoEspera(
                        self, "Asistente de configuración",
                        "Se abrió un navegador. Inicia sesión en Caprendizaje (si hace falta) y navega "
                        "hasta la página donde ves la TABLA de convocatorias de contrato de aprendizaje.\n\n"
                        "Cuando la tengas en pantalla, pulsa «Ya veo la tabla».",
                        "Ya veo la tabla", al_continuar=evento.set, al_cancelar=self.detener)
                elif tipo == "fin":
                    self._terminar(msg[1], msg[2], msg[3])
        except queue.Empty:
            pass
        self.after(120, self._procesar_cola)

    def _escribir_log(self, texto: str, nivel: int) -> None:
        self.caja_log.configure(state="normal")
        self.caja_log.insert("end", texto + "\n")
        self.caja_log.see("end")
        self.caja_log.configure(state="disabled")
        if self.trabajando:  # la última línea breve del log sirve de estado en vivo
            corto = texto.split("  ", 1)[-1]
            if len(corto) < 140 and not corto.startswith("["):
                self.lbl_estado.configure(text=corto)

    def _terminar(self, tipo: str, resultado: Any, error: str | None) -> None:
        self._ocupado(False)
        self._evento_espera = None
        if error == "cancelado":
            self.lbl_estado.configure(text="Proceso detenido.")
            self.barra.set(0)
            self._pintar_resultados()
            return
        if error:
            self.lbl_estado.configure(text="Ocurrió un error. Revisa el registro detallado.")
            self.var_log.set(True)
            self._toggle_log()
            messagebox.showerror(APP_NAME, f"No se pudo completar:\n\n{error[:600]}")
            return
        if tipo == "buscar":
            ranking = resultado["ranking"]
            self._pintar_resultados(ranking)
            texto = (f"Listo: {resultado['encontradas']} vacantes en el portal · "
                     f"{len(ranking)} de tu área con hoja de vida lista.")
            if resultado["alertadas"]:
                texto += f" · {resultado['alertadas']} alertas enviadas."
            self.lbl_estado.configure(text=texto)
            self.barra.set(1)
        elif tipo == "calibrar":
            self._resultado_calibracion(resultado)
        elif tipo == "diagnostico":
            lineas_diag = [f"{'✔' if c.ok else '✘'}  {c.nombre}: {c.detalle}" for c in resultado]
            todo_ok = all(c.ok for c in resultado if c.critico)
            self.lbl_estado.configure(text="Diagnóstico: todo en orden." if todo_ok
                                      else "Diagnóstico: hay problemas (ver detalle).")
            (messagebox.showinfo if todo_ok else messagebox.showwarning)(
                APP_NAME, "\n\n".join(lineas_diag) + f"\n\nReporte guardado en:\n{DATA_HOME / 'autoprueba.json'}")

    def _resultado_calibracion(self, r: dict) -> None:
        reconocida = next((c for c in r["columnas"].values() if "razon_social" in c), None)
        self.w["url"].delete(0, "end")
        self.w["url"].insert(0, r["url"])
        self.guardar_ajustes(silencioso=True)
        if reconocida:
            campos = ", ".join(k.replace("_", " ") for k in reconocida)
            self.lbl_estado.configure(text="Página de convocatorias detectada y guardada.")
            messagebox.showinfo(APP_NAME, f"¡Listo! Guardé la página de convocatorias:\n{r['url']}\n\n"
                                          f"Columnas reconocidas: {campos}.\n\nYa puedes pulsar «Buscar vacantes».")
        else:
            self.lbl_estado.configure(text="Guardé la página, pero no reconocí la tabla.")
            messagebox.showwarning(
                APP_NAME,
                f"Guardé la dirección:\n{r['url']}\n\npero no reconocí la tabla de convocatorias "
                f"({len(r['tablas'])} tablas en la página). Asegúrate de estar en la página con el listado "
                f"y repite el asistente.\n\nSi persiste, comparte con soporte este archivo:\n{r['resumen']}")


def autoprueba() -> int:
    """Modo sin ventana: `SGVA-Matchmaker.exe --autoprueba`. Escribe autoprueba.json."""
    from modules import diagnostico

    s = AjustesApp.cargar().a_settings()
    setup_logging(s.logs_dir)
    chequeos = diagnostico.ejecutar(s, red="--sin-red" not in sys.argv)
    ruta = diagnostico.guardar_reporte(chequeos)
    if sys.stdout:
        for c in chequeos:
            print(f"[{'OK ' if c.ok else 'ERR'}] {c.nombre}: {c.detalle}")
        print(f"Reporte: {ruta}")
    return 0 if all(c.ok for c in chequeos if c.critico) else 1


def main() -> None:
    if "--autoprueba" in sys.argv:
        sys.exit(autoprueba())
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
