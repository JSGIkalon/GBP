"""Paleta y estilo de la interfaz — Estilo Ikalon, Edición 2026.

La identidad manda: la paleta de datos está **cerrada a la gama azul del manual
de marca** más gris, blanco y navy. Rojo, naranja, amarillo y verde están
prohibidos en datos, con una sola apertura acotada: los círculos de estado del
semáforo.

Consecuencia para los gráficos
------------------------------
Las series no pueden ser tonos distintos; son **pasos de intensidad de una misma
rampa azul**. Eso separa menos que una paleta categórica de hues distintos, así
que la identidad de cada serie **nunca depende solo del color**: siempre hay
leyenda, etiquetas directas en el último año y una tabla con los mismos números.
El orden de los pasos alterna oscuro y claro para maximizar la separación entre
series vecinas.

El tope de series es el número de pasos de la rampa. Más allá no se inventan
tonos: la interfaz impide agregar más estrategias.
"""

from __future__ import annotations

# --- Paleta "Modern Financial Terminal" (rediseño 0.5) ----------------------
# Los nombres históricos se conservan como alias: el informe PDF y los paneles
# los importan, y así heredan la paleta nueva sin tocarse uno por uno.
NAVY = "#102D43"          # Azul petróleo: barra lateral, títulos, botón principal
PRIMARY = "#1D5B85"       # Azul financiero: énfasis, selección, mediana
CHART = "#55B8E8"         # Azul claro para bandas de gráficos
BG = "#F4F7FA"            # Fondo general de la aplicación
BORDER = "#E3E8EE"        # Bordes de tarjetas y campos
POSITIVE = "#16A085"      # Resultados positivos
NEGATIVE = "#B03A2E"      # Cifras negativas en tablas (sobrio, no alarmista)
EMPHASIS = PRIMARY
BLUE_MID = "#5E7A8F"      # Etiquetas de grupo y encabezados secundarios
TEAL_DARK = "#174A6C"
CYAN = CHART
BLUE_LIGHT = "#A8DBF3"
NEUTRAL = "#E6EBF0"       # Hairline
LEADER = "#A9BACA"
FILL_SOFT = "#CFE3EF"
PANEL = BG
INK = "#22384A"           # Texto cuerpo
INK_SOFT = "#6B7F8F"      # Información secundaria
WHITE = "#FFFFFF"
SERIES_FOURTH = "#2E6E99"

# --- Series de datos -------------------------------------------------------
# Pasos de una rampa azul, alternando oscuro y claro para separar vecinas.
SERIES = [NAVY, CHART, PRIMARY, BLUE_LIGHT]
# Texto legible encima de cada relleno.
SERIES_TEXT = [WHITE, INK, WHITE, INK]

MAX_SERIES = len(SERIES)

# --- Semáforo (única apertura de color, y solo dentro del círculo) ---------
STATUS_GOOD = "#2E9E4F"
STATUS_WARNING = "#E8A200"
STATUS_CRITICAL = "#C0392B"

# --- Chrome de los gráficos ------------------------------------------------
SURFACE = WHITE
GRIDLINE = "#EDF1F5"
BASELINE = LEADER

FONT_FAMILY = ["Inter", "Jost", "Calibri", "system-ui", "sans-serif"]
FONT_STACK = '"Inter", "Jost", "Calibri", system-ui, sans-serif'
_fonts_registered = False


def register_fonts() -> None:
    """Registra Inter (empaquetada en gbp/data/fonts) en Qt y en matplotlib.

    Sin ella instalada en el equipo, Qt y el PDF caerían en Calibri. Se llama
    al crear la ventana y al dibujar; es idempotente. Para Qt hace falta una
    QApplication viva, así que esa parte solo corre si existe.
    """
    global _fonts_registered
    from ..model.correlation import data_dir

    folder = data_dir() / "fonts"
    files = sorted(folder.glob("*.ttf")) if folder.exists() else []
    if not _fonts_registered:
        try:
            from matplotlib import font_manager

            for f in files:
                font_manager.fontManager.addfont(str(f))
        except Exception:  # noqa: BLE001 — sin la fuente el gráfico sale igual
            pass
    try:
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is not None and "Inter" not in QFontDatabase.families():
            for f in files:
                QFontDatabase.addApplicationFont(str(f))
    except Exception:  # noqa: BLE001
        pass
    _fonts_registered = True


def series_color(index: int) -> str:
    """Color de la serie `index`, en orden fijo de la rampa."""
    return SERIES[min(index, MAX_SERIES - 1)]


def series_text_color(index: int) -> str:
    """Color de texto legible sobre el relleno de la serie `index`."""
    return SERIES_TEXT[min(index, MAX_SERIES - 1)]


def status_color(probability: float) -> str:
    """Color del círculo de estado según la probabilidad de éxito."""
    if probability >= 0.80:
        return STATUS_GOOD
    if probability >= 0.60:
        return STATUS_WARNING
    return STATUS_CRITICAL


def status_dot(color: str, text: str) -> str:
    """Círculo de estado seguido de texto en Ink.

    El color vive **solo dentro del círculo**: el texto nunca se colorea, que es
    lo que el semáforo del manual prohíbe expresamente.
    """
    return (
        f"<span style='color:{color}; font-size:16px;'>&#9679;</span> "
        f"<span style='color:{INK};'>{text}</span>"
    )


def apply_matplotlib_style() -> None:
    """Estilo base: fondo blanco, rejilla discreta, sin marcos."""
    import matplotlib as mpl

    register_fonts()
    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.sans-serif": FONT_FAMILY,
            "font.size": 9,
            "text.color": INK,
            "axes.labelcolor": INK_SOFT,
            "axes.edgecolor": NEUTRAL,
            "axes.linewidth": 0.8,
            "axes.titlecolor": INK,
            "axes.titlesize": 11.5,
            "axes.titleweight": "semibold",
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRIDLINE,
            "grid.linewidth": 0.6,
            "xtick.color": INK_SOFT,
            "ytick.color": INK_SOFT,
            "xtick.labelcolor": INK_SOFT,
            "ytick.labelcolor": INK_SOFT,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "figure.autolayout": False,
        }
    )


def clean_axes(ax) -> None:
    """Sin marco: solo la rejilla horizontal, que sí codifica lectura de valor."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.6)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)


def format_number(value: float) -> str:
    """Entero con punto de miles, a la colombiana: 25.000.000.

    Se arma a mano y no con `locale`: el locale del sistema cambia de un
    computador a otro y el informe tiene que salir igual en todos.
    """
    return f"{round(value):,.0f}".replace(",", ".")


def format_money(value: float) -> str:
    """Monto completo, sin decimales ni abreviaturas: 25.000.000.

    Antes se abreviaba a «25.0MM»; se pasó a la cifra entera a pedido de
    Ikalon, que quiere ver todos los dígitos en la app y en el informe.
    """
    if abs(value) < 0.5:
        return "0"  # sin «-0» para un redondeo de un negativo minúsculo
    return format_number(value)


# --- Escala de lectura de los resultados ------------------------------------
# Se elige en Ajustes. Aplica a lo que **se lee** —tablas, gráficos, tooltips e
# informe—, nunca a los campos donde se escriben montos del caso, que siguen en
# unidades completas: escribir en millones y leer en unidades es justo el error
# que el aviso del capital inicial ya ataja.
SCALES = {
    "normal": (1.0, ""),
    "miles": (1e3, "miles"),
    "millones": (1e6, "millones"),
    "miles_de_millones": (1e9, "miles de millones"),
}
SCALE_LABELS = {
    "normal": "Normal (cifra completa)",
    "miles": "Miles",
    "millones": "Millones",
    "miles_de_millones": "Miles de millones",
}
_display_scale = "normal"


def set_display_scale(key: str) -> None:
    global _display_scale
    _display_scale = key if key in SCALES else "normal"


def display_scale() -> str:
    return _display_scale


def format_display(value: float, scale: str | None = None) -> str:
    """Una cifra de resultado en la escala elegida en Ajustes (o en `scale`).

    En la escala normal es exactamente `format_money`. En miles o millones
    lleva un decimal —con coma, a la colombiana— para no perder la diferencia
    entre 1,1 y 1,2 millones: 1.154.785 en millones es «1,2».
    """
    divisor, _ = SCALES[scale or _display_scale]
    if divisor == 1.0:
        return format_money(value)
    scaled = value / divisor
    if abs(scaled) < 0.05:
        return "0"
    return f"{scaled:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


def larger_scales(start: str | None = None) -> list[str]:
    """La escala dada y las mayores, en orden: para los gráficos que buscan una
    donde sus etiquetas quepan horizontales."""
    keys = list(SCALES)
    return keys[keys.index(start or _display_scale):]


def amount_unit(currency: str = "", scale: str | None = None) -> str:
    """Rótulo de la unidad de las cifras: «millones de COP», «COP», «miles» o ""."""
    _, name = SCALES[scale or _display_scale]
    if name and currency:
        return f"{name} de {currency}"
    return name or currency


def use_thousands_dot(spinbox) -> None:
    """El campo muestra y acepta el punto de miles: 25.000.000.

    Solo para campos **enteros** (montos, número de simulaciones). En los de
    porcentaje el locale colombiano haría del punto un separador de miles, y
    escribir «2.5» en la inflación daría 25 %.
    """
    from PySide6.QtCore import QLocale

    spinbox.setLocale(QLocale(QLocale.Language.Spanish, QLocale.Country.Colombia))
    spinbox.setGroupSeparatorShown(True)


def money_axis(ax, axis: str = "y", scale: str | None = None) -> None:
    """Rótulos del eje en la escala de lectura (o en la que eligió el gráfico)."""
    from matplotlib.ticker import FuncFormatter

    def tick(v, _pos):
        # Las marcas del eje son números redondos: «500.000» y no «500.000,0».
        text = format_display(v, scale)
        return text[:-2] if text.endswith(",0") else text

    formatter = FuncFormatter(tick)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(formatter)


# Títulos de grupo dentro de los paneles: semibold en azul petróleo, con una
# línea fina arriba que separa el grupo del anterior.
SECTION_STYLE = (
    f"color: {NAVY}; font-weight: 600; font-size: 14px; "
    f"border-top: 1px solid {BORDER}; padding-top: 12px; margin-top: 4px;"
)
INLINE_LABEL_STYLE = f"color: {NAVY}; font-weight: 600;"
NOTE_STYLE = f"color: {INK_SOFT}; font-size: 12px;"

# --- Hoja de estilo de la interfaz ----------------------------------------
# "Modern Financial Terminal": fondo gris azulado, superficies blancas con
# borde de 1 px y radio corto, sin sombras ni gradientes. La barra lateral va
# en azul petróleo. Las pestañas marcan la selección con un subrayado.
STYLESHEET = f"""
QWidget {{
    background-color: {WHITE};
    color: {INK};
    font-family: {FONT_STACK};
    font-size: 13px;
}}

QMainWindow, QWidget#appRoot, QWidget#workArea {{
    background-color: {BG};
}}

/* --- Barra lateral ------------------------------------------------------ */
QFrame#sidebar, QFrame#sidebar QWidget {{
    background-color: {NAVY};
    color: #C9D6E1;
}}
QFrame#sidebar QToolButton {{
    background-color: transparent;
    color: #C9D6E1;
    border: none;
    border-left: 3px solid transparent;
    padding: 10px 6px 10px 14px;
    font-size: 12px;
    text-align: left;
}}
QFrame#sidebar QToolButton:hover {{
    background-color: #183B55;
    color: {WHITE};
}}
QFrame#sidebar QToolButton:checked {{
    background-color: #1A4361;
    color: {WHITE};
    font-weight: 600;
    border-left: 3px solid {CHART};
}}
QFrame#sidebar QLabel#sidebarCaption {{
    color: #7F97AB;
    font-size: 10px;
    padding: 0 16px;
}}

/* --- Tarjetas ----------------------------------------------------------- */
QFrame#card {{
    background-color: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QLabel#cardTitle {{
    color: {NAVY};
    font-size: 15px;
    font-weight: 600;
    background-color: transparent;
}}
QLabel#cardEyebrow {{
    color: {INK_SOFT};
    font-size: 10px;
    font-weight: 600;
    background-color: transparent;
}}
QFrame#kpiCard {{
    background-color: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame#kpiCard[accent="true"] {{
    background-color: #EAF3FA;
    border: 1px solid #D3E5F3;
}}
QFrame#kpiCard QLabel {{
    background-color: transparent;
}}
QLabel#kpiTitle {{
    color: {INK_SOFT};
    font-size: 12px;
    font-weight: 500;
}}
QLabel#kpiValue {{
    color: {NAVY};
    font-size: 24px;
    font-weight: 600;
}}
QLabel#kpiUnit {{
    color: {INK_SOFT};
    font-size: 11px;
}}

/* --- Pestañas ----------------------------------------------------------- */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {BORDER};
    top: -1px;
    background-color: {WHITE};
}}
QTabBar {{
    background-color: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {INK_SOFT};
    padding: 9px 12px;
    margin-right: 0px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    color: {NAVY};
    font-weight: 600;
    border-bottom: 2px solid {PRIMARY};
}}
QTabBar::tab:hover:!selected {{
    color: {NAVY};
}}

QTabWidget#resultsTabs > QTabBar::tab {{
    padding: 9px 10px;
    font-size: 12px;
}}

/* Pestañas del panel de parámetros: segmentadas y compactas. */
QTabWidget#inputsTabs::pane {{
    border: none;
    top: 0px;
}}
QTabWidget#inputsTabs > QTabBar::tab {{
    background-color: {BG};
    color: {INK};
    border: 1px solid {BORDER};
    padding: 6px 12px;
    margin: 0px 0px 8px 0px;
    font-size: 12px;
}}
QTabWidget#inputsTabs > QTabBar::tab:first {{
    border-top-left-radius: 4px;
    border-bottom-left-radius: 4px;
}}
QTabWidget#inputsTabs > QTabBar::tab:last {{
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}}
QTabWidget#inputsTabs > QTabBar::tab:selected {{
    background-color: {NAVY};
    color: {WHITE};
    border: 1px solid {NAVY};
    font-weight: 600;
}}
QTabWidget#inputsTabs > QTabBar::tab:hover:!selected {{
    background-color: #E9EFF5;
}}

/* --- Tipografía por rol ------------------------------------------------- */
QLabel[role="lede"] {{
    font-size: 15px;
    font-weight: 600;
    color: {NAVY};
}}
QLabel[role="note"] {{
    color: {INK_SOFT};
    font-size: 11px;
}}
QLabel[role="eyebrow"] {{
    color: {NAVY};
    font-size: 13px;
    font-weight: 600;
}}

QGroupBox {{
    border: none;
    border-top: 1px solid {BORDER};
    margin-top: 22px;
    padding-top: 8px;
    font-weight: 600;
    color: {NAVY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 0px;
    padding: 0 0 6px 0;
}}

/* --- Tablas ------------------------------------------------------------- */
QTableWidget, QTableView {{
    background-color: {WHITE};
    alternate-background-color: #FAFBFD;
    gridline-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 4px;
    selection-background-color: #E3EFF8;
    selection-color: {NAVY};
}}
QTableWidget::item {{
    border-bottom: 1px solid #EEF2F6;
    padding: 4px 10px;
}}
QHeaderView {{
    background-color: {BG};
}}
QHeaderView::section {{
    background-color: {BG};
    color: {NAVY};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 10px;
    font-weight: 600;
    font-size: 12px;
}}
QTableCornerButton::section {{
    background-color: {BG};
    border: none;
}}

/* --- Campos ------------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {WHITE};
    border: 1px solid #D5DDE5;
    border-radius: 4px;
    padding: 5px 8px;
    color: {INK};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border: 1px solid {LEADER};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {PRIMARY};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {LEADER};
    background-color: {BG};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER};
    selection-background-color: #E3EFF8;
    selection-color: {NAVY};
}}

/* --- Botones ------------------------------------------------------------ */
QPushButton {{
    background-color: {WHITE};
    color: {NAVY};
    border: 1px solid #D0D9E2;
    border-radius: 4px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    border: 1px solid {PRIMARY};
    color: {PRIMARY};
    background-color: #F5F9FC;
}}
QPushButton:disabled {{
    color: {LEADER};
    border: 1px solid {NEUTRAL};
}}
QPushButton#runButton {{
    background-color: {NAVY};
    color: {WHITE};
    border: 1px solid {NAVY};
    padding: 10px 22px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#runButton:hover {{
    background-color: {PRIMARY};
    border: 1px solid {PRIMARY};
}}
QPushButton#runButton:disabled {{
    background-color: {LEADER};
    border: 1px solid {LEADER};
    color: {WHITE};
}}
QPushButton#exportButton {{
    padding: 10px 18px;
    font-size: 14px;
}}
QToolButton#collapseButton {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {INK_SOFT};
    padding: 2px 6px;
}}
QToolButton#collapseButton:hover {{
    color: {PRIMARY};
    border: 1px solid {PRIMARY};
}}

QLabel#statusLabel {{
    color: {INK_SOFT};
    background-color: transparent;
}}
QLabel#currencyBanner {{
    background-color: #EAF3FA;
    color: {NAVY};
    border: 1px solid #D3E5F3;
    border-radius: 4px;
    font-weight: 600;
    padding: 6px 12px;
}}

QProgressBar {{
    border: none;
    border-radius: 3px;
    background-color: {NEUTRAL};
    text-align: center;
    color: {NAVY};
    font-size: 11px;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background-color: {CHART};
    border-radius: 3px;
}}

QCheckBox {{
    spacing: 8px;
    background-color: transparent;
}}

QMenuBar {{
    background-color: {WHITE};
    color: {INK};
    border-bottom: 1px solid {BORDER};
}}
QMenu {{
    background-color: {WHITE};
    color: {INK};
    border: 1px solid {BORDER};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background-color: #E3EFF8;
    color: {NAVY};
}}

QStatusBar {{
    background-color: {WHITE};
    color: {INK_SOFT};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}

QSplitter, QSplitter::handle {{
    background-color: {BG};
}}

QScrollArea {{
    border: none;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border: none;
    width: 10px;
    height: 10px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #C8D3DD;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QToolTip {{
    background-color: {NAVY};
    color: {WHITE};
    border: none;
    padding: 5px 8px;
}}
"""
