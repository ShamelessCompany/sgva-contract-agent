#!/usr/bin/env python3
"""
Patronix — Asistente de Etapa Productiva y Empleabilidad (Shameless Company).

Interfaz gráfica moderna con barra lateral (Sidebar), diseñada para máxima
simplicidad y cero confusión para cualquier aprendiz del SENA.
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

from config import APP_NAME, DATA_HOME, RESOURCE_DIR
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
from modules.navegadores import OPCIONES as NAVEGADORES
from modules.utils import CANCELAR, Cancelado, setup_logging

log = logging.getLogger("app")

# --------------------------------------------------------------------- Identidad visual moderna
COLOR_PRIMARIO = ("#1E5E8A", "#2B79B4")          # Azul corporativo sobrio y confiable
COLOR_PRIMARIO_HOVER = ("#164668", "#1E5E8A")
COLOR_SIDEBAR = ("#E9ECEF", "#1A1D20")           # Fondo lateral
COLOR_FONDO_CONTENIDO = ("#F8F9FA", "#121416")   # Fondo principal
COLOR_TARJETA = ("#FFFFFF", "#212529")           # Tarjetas limpias
COLOR_BORDE = ("#DEE2E6", "#2D3238")             # Líneas divisorias sutiles
COLOR_TEXTO_SUAVE = ("#6C757D", "#ADB5BD")       # Subtítulos y metadatos
COLOR_VERDE = ("#2B8A3E", "#40C057")             # Afinidad alta / éxito
COLOR_AMBAR = ("#D97706", "#F59F00")             # Afinidad media
COLOR_GRIS = ("#868E96", "#868E96")

AVISO_CORTO = "Iniciativa independiente de Shameless Company · No oficial del SENA"

DESCARGO = (
    "Patronix es una herramienta de automatización local desarrollada por el colectivo "
    "Shameless Company para facilitar la búsqueda de contratos de aprendizaje.\n\n"
    "NO es un software oficial del Servicio Nacional de Aprendizaje (SENA), ni está respaldado, "
    "patrocinado o certificado por el SENA ni por el portal Caprendizaje.\n\n"
    "•  El software se ejecuta 100% en tu propio computador.\n"
    "•  Tus credenciales se usan única y exclusivamente para consultar tus convocatorias autorizadas.\n"
    "•  Nunca compartas tu cuenta ni uses la herramienta de forma abusiva.\n\n"
    "El software se entrega «tal cual», bajo licencia MIT."
)


def abrir_ruta(ruta: Path | str) -> None:
    ruta = str(ruta)
    try:
        if sys.platform == "win32":
            os.startfile(ruta)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", ruta])
        else:
            subprocess.Popen(["xdg-open", ruta])
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror(APP_NAME, f"No se pudo abrir:\n{ruta}\n\n{exc}")


MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def fecha_legible(iso: str) -> str:
    try:
        a, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {MESES_CORTOS[m - 1]} {a}"
    except (ValueError, IndexError):
        return iso


class ColaLogHandler(logging.Handler):
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
    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.aceptado = False
        self.title("Bienvenido a Patronix")
        self.geometry("600x560")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        ctk.CTkLabel(self, text="Términos y Aviso Legal",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(padx=24, pady=(24, 6), anchor="w")
        caja = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(size=13))
        caja.pack(fill="both", expand=True, padx=24, pady=8)
        caja.insert("1.0", DESCARGO)
        caja.configure(state="disabled")

        self.var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Entiendo y acepto las condiciones de uso", variable=self.var,
                        command=self._toggle, fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER
                        ).pack(padx=24, pady=(10, 8), anchor="w")

        fila = ctk.CTkFrame(self, fg_color="transparent")
        fila.pack(fill="x", padx=24, pady=(6, 20))
        ctk.CTkButton(fila, text="Salir", width=100, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray85"), command=self.destroy).pack(side="right")
        self.boton = ctk.CTkButton(fila, text="Continuar a Patronix", width=160, state="disabled",
                                   fg_color=("gray70", "gray35"), hover_color=COLOR_PRIMARIO_HOVER,
                                   command=self._aceptar)
        self.boton.pack(side="right", padx=10)
        self.after(50, self._modal)

    def _modal(self) -> None:
        self.lift()
        self.focus_force()
        self.grab_set()

    def _toggle(self) -> None:
        activo = self.var.get()
        self.boton.configure(state="normal" if activo else "disabled",
                             fg_color=COLOR_PRIMARIO if activo else ("gray70", "gray35"))

    def _aceptar(self) -> None:
        self.aceptado = True
        self.destroy()


class DialogoProyecto(ctk.CTkToplevel):
    def __init__(self, master: Any, proyecto: dict | None, al_guardar: Callable[[dict], None]) -> None:
        super().__init__(master)
        self.title("Proyecto en tu Portafolio")
        self.geometry("540x520")
        self.al_guardar = al_guardar
        p = proyecto or {}
        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True, padx=24, pady=20)
        cuerpo.grid_columnconfigure(0, weight=1)

        def etiqueta(texto: str, fila: int, ayuda: str = "") -> None:
            ctk.CTkLabel(cuerpo, text=texto, font=ctk.CTkFont(weight="bold")).grid(
                row=fila, column=0, sticky="w", pady=(8, 2))
            if ayuda:
                ctk.CTkLabel(cuerpo, text=ayuda, text_color=COLOR_TEXTO_SUAVE, font=ctk.CTkFont(size=11)).grid(
                    row=fila, column=0, sticky="e", pady=(8, 2))

        etiqueta("Nombre del proyecto", 0)
        self.nombre = ctk.CTkEntry(cuerpo, placeholder_text="Ej: Sistema de Facturación o App de Inventario")
        self.nombre.grid(row=1, column=0, sticky="ew")
        self.nombre.insert(0, p.get("nombre", ""))

        etiqueta("¿De qué trata o qué problema resuelve?", 2)
        self.descripcion = ctk.CTkTextbox(cuerpo, height=70, wrap="word")
        self.descripcion.grid(row=3, column=0, sticky="ew")
        self.descripcion.insert("1.0", p.get("descripcion", ""))

        etiqueta("Tecnologías usadas", 4, "separadas por comas")
        self.tecnologias = ctk.CTkEntry(cuerpo, placeholder_text="Python, React, MySQL, Git")
        self.tecnologias.grid(row=5, column=0, sticky="ew")
        if p.get("tecnologias"):
            self.tecnologias.insert(0, ", ".join(p["tecnologias"]))

        etiqueta("Logros o tareas clave", 6, "uno por línea")
        self.logros = ctk.CTkTextbox(cuerpo, height=80, wrap="word")
        self.logros.grid(row=7, column=0, sticky="ew")
        self.logros.insert("1.0", "\n".join(p.get("logros", [])))

        etiqueta("Enlace (GitHub / Demo)", 8, "opcional")
        self.enlace = ctk.CTkEntry(cuerpo, placeholder_text="https://github.com/...")
        self.enlace.grid(row=9, column=0, sticky="ew")
        self.enlace.insert(0, p.get("enlace", ""))

        fila = ctk.CTkFrame(cuerpo, fg_color="transparent")
        fila.grid(row=10, column=0, sticky="e", pady=(18, 0))
        ctk.CTkButton(fila, text="Cancelar", width=100, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray85"), command=self.destroy).pack(side="right")
        ctk.CTkButton(fila, text="Guardar proyecto", fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                      command=self._guardar).pack(side="right", padx=8)
        self.after(50, lambda: (self.lift(), self.grab_set(), self.nombre.focus()))

    def _guardar(self) -> None:
        nombre = self.nombre.get().strip()
        if not nombre:
            messagebox.showwarning(APP_NAME, "Escribe un nombre para el proyecto.", parent=self)
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
    def __init__(self, master: Any, titulo: str, texto: str, boton: str | None,
                 al_continuar: Callable[[], None] | None = None,
                 al_cancelar: Callable[[], None] | None = None) -> None:
        super().__init__(master)
        self.title(titulo)
        x = max(10, self.winfo_screenwidth() - 560)
        y = max(10, self.winfo_screenheight() - 340)
        self.geometry(f"520x240+{x}+{y}")
        self.attributes("-topmost", True)
        self.al_cancelar = al_cancelar
        self.protocol("WM_DELETE_WINDOW", self._cancelar)

        ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(size=16, weight="bold")).pack(
            padx=20, pady=(18, 6), anchor="w")
        ctk.CTkLabel(self, text=texto, wraplength=480, justify="left").pack(padx=20, anchor="w")
        fila = ctk.CTkFrame(self, fg_color="transparent")
        fila.pack(side="bottom", fill="x", padx=20, pady=16)

        if al_cancelar:
            ctk.CTkButton(fila, text="Cancelar", width=90, fg_color="transparent", border_width=1,
                          text_color=("gray20", "gray85"), command=self._cancelar).pack(side="right")
        if boton and al_continuar:
            def continuar() -> None:
                al_continuar()
                self.destroy()
            ctk.CTkButton(fila, text=boton, fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                          command=continuar).pack(side="right", padx=8)
        else:
            ctk.CTkButton(fila, text="Entendido", width=100, command=self.destroy).pack(side="right", padx=8)

    def _cancelar(self) -> None:
        if self.al_cancelar:
            self.al_cancelar()
        self.destroy()


# =============================================================================
# Aplicación Principal con Barra Lateral (Sidebar Layout)
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

        self.title("Patronix — Asistente de Contratos de Aprendizaje")
        self.geometry("1160x780")
        self.minsize(980, 680)
        self._icono()

        # Diseño estructural: Columna 0 = Sidebar (fija), Columna 1 = Contenido dinámico
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.vista_actual = "buscar"
        self._crear_sidebar()
        self._crear_contenedor_principal()

        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.after(120, self._procesar_cola)
        self.after(300, self._inicio)

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

    # ------------------------------------------------------------------ Barra Lateral (Sidebar)
    def _crear_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # Encabezado Marca
        enc = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        enc.pack(fill="x", padx=18, pady=(20, 24))
        ctk.CTkLabel(enc, text="Patronix", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(enc, text="Shameless Company", text_color=COLOR_PRIMARIO,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")

        # Botones de Navegación
        self.botones_nav: dict[str, ctk.CTkButton] = {}
        items = (
            ("buscar", "🔍   Buscar Vacantes"),
            ("perfil", "👤   Mi Hoja de Vida"),
            ("ajustes", "⚙️   Ajustes y Cuenta"),
            ("acerca", "ℹ️   Acerca de"),
        )
        for clave, texto in items:
            btn = ctk.CTkButton(
                self.sidebar, text=texto, anchor="w", height=42, corner_radius=8,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="transparent", text_color=("gray15", "gray90"),
                hover_color=COLOR_BORDE,
                command=lambda c=clave: self.cambiar_vista(c)
            )
            btn.pack(fill="x", padx=12, pady=4)
            self.botones_nav[clave] = btn

        # Espaciador
        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(fill="both", expand=True)

        # Pie del Sidebar
        pie_sb = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        pie_sb.pack(fill="x", padx=16, pady=16)
        ctk.CTkLabel(pie_sb, text=f"Versión {__version__}", text_color=COLOR_TEXTO_SUAVE,
                     font=ctk.CTkFont(size=11)).pack(anchor="w")
        ctk.CTkLabel(pie_sb, text="Uso local seguro", text_color=COLOR_TEXTO_SUAVE,
                     font=ctk.CTkFont(size=10)).pack(anchor="w")

    def cambiar_vista(self, clave: str) -> None:
        self.vista_actual = clave
        for c, btn in self.botones_nav.items():
            if c == clave:
                btn.configure(fg_color=COLOR_PRIMARIO, text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color=("gray15", "gray90"))

        for vista in (self.vista_buscar, self.vista_perfil, self.vista_ajustes, self.vista_acerca):
            vista.grid_forget()

        if clave == "buscar":
            self._refrescar_tarjeta_cuenta()
            self.vista_buscar.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
        elif clave == "perfil":
            self.vista_perfil.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
        elif clave == "ajustes":
            self.vista_ajustes.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
        elif clave == "acerca":
            self.vista_acerca.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)

    # ------------------------------------------------------------------ Contenedor Principal
    def _crear_contenedor_principal(self) -> None:
        self.area_principal = ctk.CTkFrame(self, fg_color=COLOR_FONDO_CONTENIDO, corner_radius=0)
        self.area_principal.grid(row=0, column=1, sticky="nsew")
        self.area_principal.grid_columnconfigure(0, weight=1)
        self.area_principal.grid_rowconfigure(0, weight=1)

        # Construcción de vistas
        self.vista_buscar = ctk.CTkFrame(self.area_principal, fg_color="transparent")
        self.vista_perfil = ctk.CTkFrame(self.area_principal, fg_color="transparent")
        self.vista_ajustes = ctk.CTkFrame(self.area_principal, fg_color="transparent")
        self.vista_acerca = ctk.CTkFrame(self.area_principal, fg_color="transparent")

        self._construir_vista_buscar()
        self._construir_vista_perfil()
        self._construir_vista_ajustes()
        self._construir_vista_acerca()

        self.cambiar_vista("buscar")

    # =========================================================================
    # VISTA 1: BÚSQUEDA Y VACANTES (Panel Principal)
    # =========================================================================
    def _construir_vista_buscar(self) -> None:
        v = self.vista_buscar
        v.grid_columnconfigure(0, weight=1)
        v.grid_rowconfigure(2, weight=1)

        # 1. Tarjeta Superior: Control de Acceso y Botón de Búsqueda
        self.card_control = ctk.CTkFrame(v, fg_color=COLOR_TARJETA, corner_radius=12,
                                         border_width=1, border_color=COLOR_BORDE)
        self.card_control.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.card_control.grid_columnconfigure(1, weight=1)

        # 2. Barra de Estado y Progreso
        barra_estado = ctk.CTkFrame(v, fg_color="transparent")
        barra_estado.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        barra_estado.grid_columnconfigure(0, weight=1)

        self.lbl_estado = ctk.CTkLabel(barra_estado, text="Listo para buscar vacantes.",
                                       font=ctk.CTkFont(size=14), anchor="w")
        self.lbl_estado.grid(row=0, column=0, sticky="w", padx=4)

        self.btn_detener = ctk.CTkButton(barra_estado, text="Detener", width=90, height=28,
                                         state="disabled", fg_color="transparent", border_width=1,
                                         text_color=("gray20", "gray85"), command=self.detener)
        self.btn_detener.grid(row=0, column=1, sticky="e")

        self.barra = ctk.CTkProgressBar(barra_estado, progress_color=COLOR_PRIMARIO, height=6)
        self.barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        self.barra.set(0)

        # 3. Lista de Vacantes
        self.lista = ctk.CTkScrollableFrame(v, fg_color="transparent")
        self.lista.grid(row=2, column=0, sticky="nsew", pady=4)
        self.lista.grid_columnconfigure(0, weight=1)

        # 4. Registro opcional
        pie_b = ctk.CTkFrame(v, fg_color="transparent")
        pie_b.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.var_log = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(pie_b, text="Ver registro técnico en vivo", variable=self.var_log,
                      command=self._toggle_log, progress_color=COLOR_PRIMARIO).pack(side="left")
        ctk.CTkButton(pie_b, text="Abrir carpeta de resultados", fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray85"), height=26,
                      command=lambda: abrir_ruta(self.settings.output_dir)).pack(side="right")

        self.caja_log = ctk.CTkTextbox(v, height=120, font=ctk.CTkFont(family="Consolas", size=11))
        self.caja_log.configure(state="disabled")

        self._pintar_resultados()

    def _refrescar_tarjeta_cuenta(self) -> None:
        for w in self.card_control.winfo_children():
            w.destroy()

        a = self.ajustes
        tiene_credenciales = bool(a.sena_user and a.sena_password)

        if tiene_credenciales:
            # Vista simplificada cuando ya guardó credenciales
            col_info = ctk.CTkFrame(self.card_control, fg_color="transparent")
            col_info.grid(row=0, column=0, sticky="w", padx=20, pady=16)

            ctk.CTkLabel(col_info, text="Conectado como Aprendiz", font=ctk.CTkFont(size=12),
                         text_color=COLOR_TEXTO_SUAVE).pack(anchor="w")
            ctk.CTkLabel(col_info, text=f"Documento: {a.sena_user}",
                         font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w")
            prog_corto = a.programa_formacion[:45] + "..." if len(a.programa_formacion) > 45 else a.programa_formacion
            ctk.CTkLabel(col_info, text=f"Programa: {prog_corto}",
                         text_color=COLOR_PRIMARIO, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")

            col_btn = ctk.CTkFrame(self.card_control, fg_color="transparent")
            col_btn.grid(row=0, column=1, sticky="e", padx=20, pady=16)

            self.btn_buscar = ctk.CTkButton(
                col_btn, text="🔍  Buscar Convocatorias", height=44, width=220,
                corner_radius=8, font=ctk.CTkFont(size=15, weight="bold"),
                fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                command=self.buscar
            )
            self.btn_buscar.pack(side="left", padx=6)

            ctk.CTkButton(
                col_btn, text="🌐 Abrir Portal", height=44, width=120,
                corner_radius=8, fg_color="transparent", border_width=1,
                text_color=("gray20", "gray85"), hover_color=COLOR_BORDE,
                command=self.abrir_portal_manual
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                col_btn, text="Editar cuenta", height=44, width=100,
                corner_radius=8, fg_color="transparent",
                text_color=COLOR_TEXTO_SUAVE, command=lambda: self.cambiar_vista("ajustes")
            ).pack(side="left", padx=4)

        else:
            # Formulario directo para que el aprendiz no tenga que buscar dónde poner su clave
            ctk.CTkLabel(self.card_control, text="Paso 1: Conecta tu cuenta del SENA para empezar",
                         font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, columnspan=3,
                                                                        sticky="w", padx=20, pady=(16, 6))

            fila_inputs = ctk.CTkFrame(self.card_control, fg_color="transparent")
            fila_inputs.grid(row=1, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 16))

            ctk.CTkLabel(fila_inputs, text="Cédula / Documento:").pack(side="left", padx=(0, 6))
            self.ent_doc_rapido = ctk.CTkEntry(fila_inputs, width=140, placeholder_text="1095307496")
            if a.sena_user:
                self.ent_doc_rapido.insert(0, a.sena_user)
            self.ent_doc_rapido.pack(side="left", padx=(0, 14))

            ctk.CTkLabel(fila_inputs, text="Contraseña:").pack(side="left", padx=(0, 6))
            self.ent_pass_rapido = ctk.CTkEntry(fila_inputs, width=140, show="•", placeholder_text="Tu clave SGVA")
            self.ent_pass_rapido.pack(side="left", padx=(0, 14))

            self.btn_buscar = ctk.CTkButton(
                self.card_control, text="🚀  Iniciar Búsqueda", height=38, width=180,
                corner_radius=8, font=ctk.CTkFont(size=14, weight="bold"),
                fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                command=self._guardar_y_buscar_rapido
            )
            self.btn_buscar.grid(row=1, column=2, sticky="e", padx=20, pady=(0, 16))

    def _guardar_y_buscar_rapido(self) -> None:
        doc = self.ent_doc_rapido.get().strip()
        pwd = self.ent_pass_rapido.get()
        if not doc or not pwd:
            messagebox.showwarning(APP_NAME, "Ingresa tu número de documento y contraseña para continuar.")
            return
        self.ajustes.sena_user = doc
        self.ajustes.sena_password = pwd
        self.ajustes.guardar(almacen=self.almacen)
        self.settings = self.ajustes.a_settings()
        self._refrescar_tarjeta_cuenta()
        self.buscar()

    def _toggle_log(self) -> None:
        if self.var_log.get():
            self.caja_log.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        else:
            self.caja_log.grid_forget()

    def _pintar_resultados(self, ranking: list[dict] | None = None) -> None:
        from modules.pipeline import leer_ranking

        for w in self.lista.winfo_children():
            w.destroy()
        filas = ranking if ranking is not None else leer_ranking(self.settings, self.db)

        if not filas:
            vacio = ctk.CTkFrame(self.lista, fg_color=COLOR_TARJETA, corner_radius=12,
                                 border_width=1, border_color=COLOR_BORDE)
            vacio.grid(row=0, column=0, sticky="ew", padx=4, pady=12)

            ctk.CTkLabel(vacio, text="Aún no has realizado una búsqueda",
                         font=ctk.CTkFont(size=16, weight="bold")).pack(padx=24, pady=(24, 6), anchor="w")
            info = (
                "Para encontrar vacantes de contrato de aprendizaje:\n"
                "1. Ingresa tu número de documento y contraseña del SENA arriba.\n"
                "2. Pulsa el botón «Buscar Convocatorias».\n"
                "3. Patronix analizará las empresas y generará tu Hoja de Vida y correos listos."
            )
            ctk.CTkLabel(vacio, text=info, justify="left", text_color=COLOR_TEXTO_SUAVE,
                         font=ctk.CTkFont(size=13)).pack(padx=24, pady=(0, 24), anchor="w")
            return

        for i, r in enumerate(filas):
            self._tarjeta(i, r)

    def _tarjeta(self, fila: int, r: dict) -> None:
        card = ctk.CTkFrame(self.lista, fg_color=COLOR_TARJETA, corner_radius=12,
                            border_width=1, border_color=COLOR_BORDE)
        card.grid(row=fila, column=0, sticky="ew", padx=4, pady=6)
        card.grid_columnconfigure(1, weight=1)

        afinidad = float(r.get("afinidad", 0))
        color = COLOR_VERDE if afinidad >= 60 else COLOR_AMBAR if afinidad >= 30 else COLOR_GRIS

        # Badge afinidad
        caja_af = ctk.CTkFrame(card, fg_color="transparent")
        caja_af.grid(row=0, column=0, rowspan=3, padx=(18, 12), pady=14, sticky="n")
        ctk.CTkLabel(caja_af, text=f"{afinidad:.0f}%", width=68,
                     font=ctk.CTkFont(size=22, weight="bold"), text_color=color).pack()
        ctk.CTkLabel(caja_af, text="afinidad", text_color=COLOR_TEXTO_SUAVE,
                     font=ctk.CTkFont(size=11)).pack()

        # Título y datos de la empresa
        ctk.CTkLabel(card, text=r.get("empresa", "Empresa"), anchor="w",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=1, sticky="sw", pady=(14, 2))

        detalles = []
        if r.get("ciudad"):
            detalles.append(f"📍 {r['ciudad']}")
        if r.get("sector") and r["sector"] != "No determinado":
            detalles.append(f"🏢 {r['sector']}")
        if r.get("fecha_limite"):
            detalles.append(f"⏳ Cierre: {fecha_legible(r['fecha_limite'])}")

        ctk.CTkLabel(card, text="   ·   ".join(detalles), anchor="w",
                     text_color=COLOR_TEXTO_SUAVE, font=ctk.CTkFont(size=12)
                     ).grid(row=1, column=1, sticky="nw", pady=(0, 8))

        # Botones de Acción
        botones = ctk.CTkFrame(card, fg_color="transparent")
        botones.grid(row=2, column=1, sticky="w", pady=(0, 14))
        carpeta = Path(r.get("carpeta", ""))

        # Hoja de vida
        pdf_path = r.get("pdf")
        if pdf_path and Path(pdf_path).exists():
            ctk.CTkButton(botones, text="📄  Descargar Hoja de Vida (PDF)", height=32, corner_radius=6,
                          font=ctk.CTkFont(size=12, weight="bold"),
                          fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                          command=lambda p=pdf_path: abrir_ruta(p)).pack(side="left", padx=(0, 8))
        else:
            ctk.CTkButton(botones, text="📄  Hoja de Vida (Markdown)", height=32, corner_radius=6,
                          fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                          command=lambda c=carpeta: abrir_ruta(c / "hoja_de_vida.md")).pack(side="left", padx=(0, 8))

        # Correo
        ctk.CTkButton(botones, text="✉️  Copiar Correo", height=32, corner_radius=6,
                      fg_color="transparent", border_width=1, text_color=("gray15", "gray90"),
                      hover_color=COLOR_BORDE,
                      command=lambda c=carpeta: self._menu_correo(c)).pack(side="left", padx=(0, 8))

        # Enlace portal
        if r.get("enlace"):
            ctk.CTkButton(botones, text="🔗  Ver en SGVA", height=32, corner_radius=6,
                          fg_color="transparent", border_width=1, text_color=("gray15", "gray90"),
                          hover_color=COLOR_BORDE,
                          command=lambda u=r["enlace"]: webbrowser.open(u)).pack(side="left", padx=(0, 8))

        # Carpeta
        ctk.CTkButton(botones, text="📁", width=36, height=32, corner_radius=6,
                      fg_color="transparent", border_width=1, text_color=("gray15", "gray90"),
                      hover_color=COLOR_BORDE,
                      command=lambda c=carpeta: abrir_ruta(c)).pack(side="left")

    def _menu_correo(self, carpeta: Path) -> None:
        ruta = carpeta / "correos.json"
        if not ruta.exists():
            messagebox.showinfo(APP_NAME, "Esta vacante aún no tiene correos generados.")
            return
        datos = json.loads(ruta.read_text("utf-8"))
        ventana = ctk.CTkToplevel(self)
        ventana.title(f"Correo de Postulación — {datos.get('empresa', '')}")
        ventana.geometry("680x520")

        ctk.CTkLabel(ventana, text="Asunto sugerido:", font=ctk.CTkFont(weight="bold")).pack(padx=20, pady=(16, 2), anchor="w")
        asunto = ctk.CTkEntry(ventana)
        asunto.pack(fill="x", padx=20)
        asunto.insert(0, datos.get("asunto", ""))

        selector = ctk.CTkSegmentedButton(ventana, values=["Versión corta (<120 palabras)", "Versión formal"],
                                          selected_color=COLOR_PRIMARIO, selected_hover_color=COLOR_PRIMARIO_HOVER)
        selector.pack(padx=20, pady=(12, 6), anchor="w")

        cuerpo = ctk.CTkTextbox(ventana, wrap="word", font=ctk.CTkFont(size=13))
        cuerpo.pack(fill="both", expand=True, padx=20, pady=4)

        def mostrar(valor: str) -> None:
            cuerpo.delete("1.0", "end")
            cuerpo.insert("1.0", datos["version_corta" if "corta" in valor else "version_formal"])

        selector.configure(command=mostrar)
        selector.set("Versión corta (<120 palabras)")
        mostrar("corta")

        def copiar(texto: str, que: str) -> None:
            self.clipboard_clear()
            self.clipboard_append(texto)
            estado.configure(text=f"¡{que} copiado al portapapeles!")

        fila = ctk.CTkFrame(ventana, fg_color="transparent")
        fila.pack(fill="x", padx=20, pady=16)
        estado = ctk.CTkLabel(fila, text="Puedes personalizarlo antes de enviar.", text_color=COLOR_TEXTO_SUAVE)
        estado.pack(side="left")

        ctk.CTkButton(fila, text="Copiar Mensaje", fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                      command=lambda: copiar(cuerpo.get("1.0", "end").strip(), "Mensaje")).pack(side="right")
        ctk.CTkButton(fila, text="Copiar Asunto", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"),
                      command=lambda: copiar(asunto.get(), "Asunto")).pack(side="right", padx=8)

        ventana.after(50, ventana.lift)

    # =========================================================================
    # VISTA 2: MI HOJA DE VIDA (Perfil del Aprendiz)
    # =========================================================================
    def _construir_vista_perfil(self) -> None:
        v = self.vista_perfil
        v.grid_columnconfigure(0, weight=1)
        v.grid_rowconfigure(0, weight=1)

        marco = ctk.CTkScrollableFrame(v, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure((0, 1), weight=1, uniform="col")

        p = self.perfil
        self.campos_perfil: dict[str, Any] = {}
        fila = 0

        def seccion(titulo: str, sub: str = "") -> None:
            nonlocal fila
            ctk.CTkLabel(marco, text=titulo, font=ctk.CTkFont(size=17, weight="bold")).grid(
                row=fila, column=0, columnspan=2, sticky="w", padx=6, pady=(18 if fila else 4, 2))
            fila += 1
            if sub:
                ctk.CTkLabel(marco, text=sub, text_color=COLOR_TEXTO_SUAVE, font=ctk.CTkFont(size=12)).grid(
                    row=fila, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))
                fila += 1

        def entrada(clave: str, etiqueta: str, col: int, placeholder: str = "") -> None:
            caja = ctk.CTkFrame(marco, fg_color="transparent")
            caja.grid(row=fila, column=col, sticky="ew", padx=6, pady=4)
            ctk.CTkLabel(caja, text=etiqueta, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
            e = ctk.CTkEntry(caja, placeholder_text=placeholder)
            e.pack(fill="x", pady=2)
            if p.get(clave):
                e.insert(0, p[clave])
            self.campos_perfil[clave] = e

        def texto(clave: str, etiqueta: str, valor: str, alto: int = 70, ayuda: str = "") -> None:
            nonlocal fila
            caja = ctk.CTkFrame(marco, fg_color="transparent")
            caja.grid(row=fila, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
            enc = ctk.CTkFrame(caja, fg_color="transparent")
            enc.pack(fill="x")
            ctk.CTkLabel(enc, text=etiqueta, font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            if ayuda:
                ctk.CTkLabel(enc, text=ayuda, text_color=COLOR_TEXTO_SUAVE, font=ctk.CTkFont(size=11)).pack(side="right")
            t = ctk.CTkTextbox(caja, height=alto, wrap="word")
            t.pack(fill="x", pady=2)
            t.insert("1.0", valor)
            self.campos_perfil[clave] = t
            fila += 1

        seccion("1. Datos Personales", "Aparecerán en el encabezado de tu Hoja de Vida PDF.")
        entrada("nombre", "Nombre Completo", 0, "Ej: Juan Pérez")
        entrada("titulo", "Título Profesional", 1, "Aprendiz Tecnólogo en ADSO")
        fila += 1
        entrada("email", "Correo Electrónico", 0, "tu.correo@gmail.com")
        entrada("telefono", "Teléfono / WhatsApp", 1, "+57 300 000 0000")
        fila += 1
        entrada("ciudad", "Ciudad", 0, "Bucaramanga, Santander")
        entrada("programa_sena", "Programa SENA", 1, "Tecnólogo en Análisis y Desarrollo de Software")
        fila += 1
        entrada("linkedin", "LinkedIn (opcional)", 0, "linkedin.com/in/...")
        entrada("github", "GitHub / Portafolio (opcional)", 1, "github.com/...")
        fila += 1

        seccion("2. Perfil y Habilidades", "Ayuda a que el sistema empareje mejor con las empresas.")
        texto("resumen", "Breve Resumen Profesional (2-3 líneas)", p.get("resumen", ""), 60)
        hab = p.get("habilidades", {})
        texto("tecnicas", "Habilidades Técnicas", ", ".join(hab.get("tecnicas", [])), 50,
              "separadas por comas (ej: Python, SQL, React, Redes)")
        texto("blandas", "Habilidades Blandas", ", ".join(hab.get("blandas", [])), 44,
              "ej: Trabajo en equipo, puntualidad, aprendizaje rápido")

        seccion("3. Proyectos Destacados", "Los proyectos que demuestran lo que sabes hacer.")
        self.proyectos: list[dict] = list(p.get("proyectos", []))
        self.marco_proyectos = ctk.CTkFrame(marco, fg_color="transparent")
        self.marco_proyectos.grid(row=fila, column=0, columnspan=2, sticky="ew", padx=6)
        self.marco_proyectos.grid_columnconfigure(0, weight=1)
        fila += 1

        ctk.CTkButton(marco, text="+ Agregar Proyecto", width=160, height=32, corner_radius=6,
                      fg_color="transparent", border_width=1, text_color=("gray15", "gray90"),
                      command=lambda: self._editar_proyecto(None)).grid(row=fila, column=0, sticky="w", padx=6, pady=6)
        fila += 1
        self._pintar_proyectos()

        # Botón Guardar
        pie_p = ctk.CTkFrame(v, fg_color="transparent")
        pie_p.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.lbl_perfil_guardado = ctk.CTkLabel(pie_p, text="", text_color=COLOR_VERDE)
        self.lbl_perfil_guardado.pack(side="left", padx=8)

        ctk.CTkButton(pie_p, text="💾  Guardar Mi Hoja de Vida", width=200, height=40,
                      corner_radius=8, font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                      command=self.guardar_perfil_usuario).pack(side="right")

    def _pintar_proyectos(self) -> None:
        for w in self.marco_proyectos.winfo_children():
            w.destroy()
        if not self.proyectos:
            ctk.CTkLabel(self.marco_proyectos, text="Aún no has agregado proyectos.",
                         text_color=COLOR_TEXTO_SUAVE).grid(row=0, column=0, sticky="w", pady=4)
            return

        for i, pr in enumerate(self.proyectos):
            card = ctk.CTkFrame(self.marco_proyectos, fg_color=COLOR_TARJETA, corner_radius=8,
                                border_width=1, border_color=COLOR_BORDE)
            card.grid(row=i, column=0, sticky="ew", pady=4)
            card.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(card, text=pr.get("nombre", "Proyecto"), font=ctk.CTkFont(weight="bold"),
                         anchor="w").grid(row=0, column=0, sticky="w", padx=12, pady=(8, 2))
            ctk.CTkLabel(card, text=", ".join(pr.get("tecnologias", [])) or "Sin tecnologías especificadas",
                         text_color=COLOR_TEXTO_SUAVE, anchor="w", font=ctk.CTkFont(size=11)
                         ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

            ctk.CTkButton(card, text="Editar", width=60, height=24, fg_color="transparent", border_width=1,
                          text_color=("gray15", "gray90"), command=lambda idx=i: self._editar_proyecto(idx)
                          ).grid(row=0, column=1, rowspan=2, padx=4)
            ctk.CTkButton(card, text="Quitar", width=60, height=24, fg_color="transparent", border_width=1,
                          text_color=("gray15", "gray90"), command=lambda idx=i: self._quitar_proyecto(idx)
                          ).grid(row=0, column=2, rowspan=2, padx=(4, 12))

    def _editar_proyecto(self, indice: int | None) -> None:
        def al_guardar(nuevo: dict) -> None:
            if indice is None:
                self.proyectos.append(nuevo)
            else:
                self.proyectos[indice] = nuevo
            self._pintar_proyectos()

        DialogoProyecto(self, None if indice is None else self.proyectos[indice], al_guardar)

    def _quitar_proyecto(self, indice: int) -> None:
        if messagebox.askyesno(APP_NAME, "¿Deseas eliminar este proyecto?"):
            del self.proyectos[indice]
            self._pintar_proyectos()

    def guardar_perfil_usuario(self) -> None:
        def val(clave: str) -> str:
            w = self.campos_perfil.get(clave)
            if not w:
                return ""
            return (w.get("1.0", "end") if isinstance(w, ctk.CTkTextbox) else w.get()).strip()

        p = dict(self.perfil)
        for c in ("nombre", "titulo", "email", "telefono", "ciudad", "programa_sena", "linkedin", "github", "resumen"):
            p[c] = val(c)
        p["habilidades"] = {
            "tecnicas": lista_comas(val("tecnicas")),
            "blandas": lista_comas(val("blandas")),
        }
        p["proyectos"] = self.proyectos
        self.perfil = p
        guardar_perfil(self.perfil, self.settings.perfil_path)
        self.lbl_perfil_guardado.configure(text="✓ Información guardada correctamente")
        self.after(3000, lambda: self.lbl_perfil_guardado.configure(text=""))
        log.info("Perfil guardado.")

    # =========================================================================
    # VISTA 3: AJUSTES Y CUENTA
    # =========================================================================
    def _construir_vista_ajustes(self) -> None:
        v = self.vista_ajustes
        v.grid_columnconfigure(0, weight=1)
        v.grid_rowconfigure(0, weight=1)

        marco = ctk.CTkScrollableFrame(v, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(1, weight=1)

        a = self.ajustes
        fila = 0

        def seccion(titulo: str, sub: str = "") -> None:
            nonlocal fila
            ctk.CTkLabel(marco, text=titulo, font=ctk.CTkFont(size=17, weight="bold")).grid(
                row=fila, column=0, columnspan=3, sticky="w", padx=6, pady=(18 if fila else 4, 2))
            fila += 1
            if sub:
                ctk.CTkLabel(marco, text=sub, text_color=COLOR_TEXTO_SUAVE, font=ctk.CTkFont(size=12),
                             justify="left", wraplength=700).grid(row=fila, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))
                fila += 1

        seccion("Acceso al Portal Caprendizaje (SENA)",
                "Tus credenciales nunca viajan a ningún servidor ajeno; solo se usan para iniciar sesión en tu máquina.")

        ctk.CTkLabel(marco, text="Número de documento:").grid(row=fila, column=0, sticky="w", padx=6, pady=4)
        self.ent_user = ctk.CTkEntry(marco, width=280)
        self.ent_user.insert(0, a.sena_user)
        self.ent_user.grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1

        ctk.CTkLabel(marco, text="Contraseña:").grid(row=fila, column=0, sticky="w", padx=6, pady=4)
        self.ent_pass = ctk.CTkEntry(marco, width=280, show="•")
        self.ent_pass.insert(0, a.sena_password)
        self.ent_pass.grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1

        seccion("Programa de Formación")
        ctk.CTkLabel(marco, text="Tu programa:").grid(row=fila, column=0, sticky="w", padx=6, pady=4)
        self.cmb_programa = ctk.CTkComboBox(marco, values=PROGRAMAS_SENA, width=380)
        self.cmb_programa.set(a.programa_formacion)
        self.cmb_programa.grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1

        seccion("Navegador de Internet",
                "Puedes elegir qué navegador abre la aplicación para realizar la búsqueda.")
        ctk.CTkLabel(marco, text="Navegador a usar:").grid(row=fila, column=0, sticky="w", padx=6, pady=4)
        self.nav_dict = dict(NAVEGADORES)
        self.cmb_nav = ctk.CTkOptionMenu(marco, values=list(self.nav_dict), width=300,
                                         fg_color=COLOR_PRIMARIO, button_color=COLOR_PRIMARIO_HOVER)
        self.cmb_nav.set(next((k for k, v in self.nav_dict.items() if v == a.navegador), list(self.nav_dict)[0]))
        self.cmb_nav.grid(row=fila, column=1, sticky="w", pady=4)
        fila += 1

        self.var_mostrar_nav = ctk.BooleanVar(value=a.mostrar_navegador)
        ctk.CTkCheckBox(marco, text="Mostrar ventana del navegador mientras busca (recomendado)",
                        variable=self.var_mostrar_nav, fg_color=COLOR_PRIMARIO).grid(row=fila, column=1, sticky="w", pady=6)
        fila += 1

        seccion("Utilidades y Diagnóstico")
        fila_util = ctk.CTkFrame(marco, fg_color="transparent")
        fila_util.grid(row=fila, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        fila += 1

        ctk.CTkButton(fila_util, text="Abrir Carpeta de Datos", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"), command=lambda: abrir_ruta(DATA_HOME)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila_util, text="Diagnóstico del Sistema", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"), command=self.diagnostico).pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila_util, text="Cerrar Sesión Guardada", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"), command=self.borrar_sesion).pack(side="left")

        # Pie Guardar Ajustes
        pie_aj = ctk.CTkFrame(v, fg_color="transparent")
        pie_aj.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.lbl_ajustes_guardados = ctk.CTkLabel(pie_aj, text="", text_color=COLOR_VERDE)
        self.lbl_ajustes_guardados.pack(side="left", padx=8)

        ctk.CTkButton(pie_aj, text="💾  Guardar Ajustes", width=180, height=40,
                      corner_radius=8, font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=COLOR_PRIMARIO, hover_color=COLOR_PRIMARIO_HOVER,
                      command=self.guardar_ajustes_usuario).pack(side="right")

    def guardar_ajustes_usuario(self) -> None:
        a = self.ajustes
        a.sena_user = self.ent_user.get().strip()
        a.sena_password = self.ent_pass.get()
        a.programa_formacion = self.cmb_programa.get().strip()
        a.palabras_clave = palabras_sugeridas(a.programa_formacion)
        a.navegador = self.nav_dict.get(self.cmb_nav.get(), "auto")
        a.mostrar_navegador = self.var_mostrar_nav.get()
        a.guardar(almacen=self.almacen)
        self.settings = a.a_settings()
        self.lbl_ajustes_guardados.configure(text="✓ Ajustes guardados.")
        self.after(3000, lambda: self.lbl_ajustes_guardados.configure(text=""))
        self._refrescar_tarjeta_cuenta()

    def borrar_sesion(self) -> None:
        if self.settings.session_path.exists():
            self.settings.session_path.unlink()
            messagebox.showinfo(APP_NAME, "Sesión eliminada de este equipo.")
        else:
            messagebox.showinfo(APP_NAME, "No hay ninguna sesión guardada actualmente.")

    # =========================================================================
    # VISTA 4: ACERCA DE
    # =========================================================================
    def _construir_vista_acerca(self) -> None:
        v = self.vista_acerca
        v.grid_columnconfigure(0, weight=1)
        v.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(v, text=f"Patronix v{__version__} · Shameless Company",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w", pady=(4, 8))

        caja = ctk.CTkTextbox(v, wrap="word", font=ctk.CTkFont(size=13))
        caja.grid(row=1, column=0, sticky="nsew", pady=4)
        caja.insert("1.0", "AVISO LEGAL Y CONDICIONES DE USO\n\n" + DESCARGO)
        caja.configure(state="disabled")

        fila = ctk.CTkFrame(v, fg_color="transparent")
        fila.grid(row=2, column=0, sticky="w", pady=10)
        ctk.CTkButton(fila, text="Ir al portal oficial del SENA", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"),
                      command=lambda: webbrowser.open("https://www.sena.edu.co")).pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila, text="Ver archivo de registro (Log)", fg_color="transparent", border_width=1,
                      text_color=("gray15", "gray90"),
                      command=lambda: abrir_ruta(self.settings.logs_dir / "matchmaker.log")).pack(side="left")

    # =========================================================================
    # CICLO DE VIDA Y EJECUCIÓN
    # =========================================================================
    def _inicio(self) -> None:
        if self.ajustes.aviso_aceptado < VERSION_AVISO:
            d = DialogoDescargo(self)
            self.wait_window(d)
            if not d.aceptado:
                self.destroy()
                return
            self.ajustes.aviso_aceptado = VERSION_AVISO
            self.ajustes.guardar(almacen=self.almacen)

    def _cerrar(self) -> None:
        if self.trabajando and not messagebox.askyesno(APP_NAME, "Hay una búsqueda en curso. ¿Deseas detenerla y salir?"):
            return
        CANCELAR.set()
        if self._evento_espera:
            self._evento_espera.set()
        self.destroy()

    def _ocupado(self, si: bool) -> None:
        self.trabajando = si
        if hasattr(self, "btn_buscar"):
            self.btn_buscar.configure(state="disabled" if si else "normal")
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

    def abrir_portal_manual(self) -> None:
        """Abre el portal en el navegador elegido para que el usuario pueda verificar o loguear."""
        from modules.scraper import run_calibracion

        evento = threading.Event()
        self._evento_espera = evento

        def esperar() -> None:
            self.cola.put(("calibrar_espera", evento))
            evento.wait()

        self.lbl_estado.configure(text="Navegador abierto. Inicia sesión en el portal si hace falta.")
        self._en_hilo("calibrar", lambda: run_calibracion(self.settings, esperar, aviso=self._aviso_desde_hilo))

    def buscar(self) -> None:
        if not self.settings.sena_user or not self.settings.sena_password:
            self.cambiar_vista("ajustes")
            messagebox.showinfo(APP_NAME, "Ingresa tu número de documento y contraseña para iniciar.")
            return

        from modules.pipeline import busqueda_completa
        self.barra.set(0)
        self.lbl_estado.configure(text="Conectando con Caprendizaje...")

        self._en_hilo("buscar", lambda: busqueda_completa(
            self.settings, self.db, aviso=self._aviso_desde_hilo,
            progreso=lambda etapa, f: self.cola.put(("progreso", etapa, f))
        ))

    def diagnostico(self) -> None:
        from modules import diagnostico
        self.lbl_estado.configure(text="Ejecutando diagnóstico del equipo...")

        def correr() -> list:
            chequeos = diagnostico.ejecutar(self.settings)
            diagnostico.guardar_reporte(chequeos)
            return chequeos

        self._en_hilo("diagnostico", correr)

    def detener(self) -> None:
        CANCELAR.set()
        if self._evento_espera:
            self._evento_espera.set()
        self.lbl_estado.configure(text="Deteniendo proceso...")
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
                    DialogoEspera(self, titulo.capitalize() if cuerpo else "Aviso", cuerpo or titulo, None)
                elif tipo == "calibrar_espera":
                    ev: threading.Event = msg[1]
                    DialogoEspera(
                        self, "Navegador abierto",
                        "Inicia sesión en Caprendizaje en la ventana del navegador.\n\n"
                        "Cuando veas la tabla de convocatorias en pantalla, pulsa «Listo, ya estoy dentro».",
                        "Listo, ya estoy dentro", al_continuar=ev.set, al_cancelar=self.detener
                    )
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
        if self.trabajando:
            corto = texto.split("  ", 1)[-1]
            if len(corto) < 120 and not corto.startswith("["):
                self.lbl_estado.configure(text=corto)

    def _terminar(self, tipo: str, resultado: Any, error: str | None) -> None:
        self._ocupado(False)
        self._evento_espera = None

        if error == "cancelado":
            self.lbl_estado.configure(text="Proceso detenido por el usuario.")
            self.barra.set(0)
            self._pintar_resultados()
            return

        if error:
            self.lbl_estado.configure(text="Ocurrió un inconveniente. Revisa el registro.")
            self.var_log.set(True)
            self._toggle_log()
            # Mensaje amigable para timeout
            if "TargetClosedError" in error or "closed" in error.lower():
                msg = "Se cerró la ventana del navegador antes de completar la operación."
            elif "timed out" in error.lower() or "timeout" in error.lower():
                msg = (
                    "El portal del SENA tardó en responder.\n\n"
                    "Puedes pulsar «Abrir Portal» para acceder directamente en tu navegador y verificar."
                )
            else:
                msg = f"Detalle del error:\n\n{error[:400]}"
            messagebox.showerror(APP_NAME, msg)
            return

        if tipo == "buscar":
            ranking = resultado.get("ranking", [])
            self._pintar_resultados(ranking)
            total = resultado.get("encontradas", 0)
            self.lbl_estado.configure(text=f"¡Búsqueda lista! Se encontraron {total} vacantes ({len(ranking)} de tu programa).")
            self.barra.set(1.0)
        elif tipo == "calibrar":
            self.lbl_estado.configure(text="Página detectada y configurada.")
            messagebox.showinfo(APP_NAME, "¡Sesión y página detectadas con éxito!\n\nYa puedes pulsar «Buscar Convocatorias».")
        elif tipo == "diagnostico":
            todo_ok = all(c.ok for c in resultado if c.critico)
            self.lbl_estado.configure(text="Diagnóstico: Todo en orden." if todo_ok else "Diagnóstico: Hay alertas.")
            lineas_diag = [f"{'✔' if c.ok else '✘'}  {c.nombre}: {c.detalle}" for c in resultado]
            (messagebox.showinfo if todo_ok else messagebox.showwarning)(
                APP_NAME, "\n\n".join(lineas_diag))


def main() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
