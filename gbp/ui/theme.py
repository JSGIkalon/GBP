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

# --- Gama del manual de marca ---------------------------------------------
NAVY = "#002e45"          # Fondos institucionales, texto display, estructura
EMPHASIS = "#007ABA"      # ÚNICO texto de énfasis sobre blanco. Nunca como relleno.
BLUE_MID = "#194868"      # Estructura y etiquetas secundarias. No es énfasis.
CYAN = "#27b4ff"          # Rellenos y acento sobre navy. Nunca texto sobre blanco.
BLUE_LIGHT = "#76d4f3"    # Jerarquía de relleno terciario
NEUTRAL = "#E3E8EC"       # Segmentos neutros y filas de tabla de bajo contraste
LEADER = "#CDD2D5"        # Líder-lines únicamente
INK = "#1F2A30"           # Texto cuerpo
INK_SOFT = "#5C6770"      # Captions, etiquetas, fuente al pie
WHITE = "#FFFFFF"

# --- Series de datos -------------------------------------------------------
# El orden de los pasos NO es el de la rampa: está elegido para que las primeras
# series sean las más separadas entre sí, porque casi todos los casos comparan
# dos o tres estrategias. Navy (muy oscuro), cyan (brillante) y azul claro
# (pálido) se distinguen sin esfuerzo; el azul medio queda de cuarto porque es
# el que más se confunde con el navy. Probado mirando el gráfico: con el orden
# de la rampa, la primera y la tercera serie eran casi el mismo color.
SERIES = [NAVY, CYAN, BLUE_LIGHT, BLUE_MID]
# Texto legible encima de cada relleno.
SERIES_TEXT = [WHITE, INK, INK, WHITE]

MAX_SERIES = len(SERIES)

# --- Semáforo (única apertura de color, y solo dentro del círculo) ---------
STATUS_GOOD = "#2E9E4F"
STATUS_WARNING = "#E8A200"
STATUS_CRITICAL = "#C0392B"

# --- Chrome de los gráficos ------------------------------------------------
SURFACE = WHITE
GRIDLINE = NEUTRAL
BASELINE = LEADER

FONT_FAMILY = ["Jost", "Calibri", "system-ui", "sans-serif"]
FONT_STACK = '"Jost", "Calibri", system-ui, sans-serif'


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
            "axes.edgecolor": LEADER,
            "axes.linewidth": 0.8,
            "axes.titlecolor": INK,
            "axes.titlesize": 11.5,
            "axes.titleweight": "semibold",
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRIDLINE,
            "grid.linewidth": 0.8,
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
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)


def format_money(value: float, decimals: int = 1) -> str:
    """Formatea un monto en la escala más legible (MM, M o unidades)."""
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:,.{decimals}f}MM"
    if magnitude >= 1_000:
        return f"{value / 1_000:,.0f}M"
    return f"{value:,.0f}"


# --- Hoja de estilo de la interfaz ----------------------------------------
# Sin marcos de card ni bordes de caja: el orden lo da el espacio y la
# jerarquía tipográfica. Las tablas conservan separador de fila, que es uno de
# los usos de línea permitidos.
STYLESHEET = f"""
QWidget {{
    background-color: {WHITE};
    color: {INK};
    font-family: {FONT_STACK};
    font-size: 13px;
}}

QMainWindow, QTabWidget::pane, QSplitter {{
    background-color: {WHITE};
}}

QTabWidget::pane {{
    border: none;
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    color: {INK_SOFT};
    padding: 9px 16px;
    margin-right: 4px;
    border: none;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    color: {NAVY};
    font-weight: 600;
    border-bottom: 2px solid {EMPHASIS};
}}
QTabBar::tab:hover:!selected {{
    color: {NAVY};
}}

QLabel[role="lede"] {{
    font-size: 16px;
    font-weight: 600;
    color: {INK};
}}
QLabel[role="note"] {{
    color: {INK_SOFT};
    font-size: 12px;
}}
QLabel[role="eyebrow"] {{
    color: {BLUE_MID};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 2px;
}}

QGroupBox {{
    border: none;
    margin-top: 18px;
    font-weight: 600;
    color: {NAVY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 0px;
    padding: 0 0 6px 0;
}}

QTableWidget {{
    background-color: {WHITE};
    alternate-background-color: #F7F9FA;
    gridline-color: transparent;
    border: none;
    selection-background-color: {NEUTRAL};
    selection-color: {INK};
}}
QTableWidget::item {{
    border-bottom: 1px solid {NEUTRAL};
    padding: 5px 8px;
}}
QHeaderView::section {{
    background-color: {WHITE};
    color: {BLUE_MID};
    border: none;
    border-bottom: 2px solid {NEUTRAL};
    padding: 7px 8px;
    font-weight: 600;
}}

QListWidget {{
    border: none;
    background-color: {WHITE};
}}
QListWidget::item {{
    padding: 8px 6px;
    border-bottom: 1px solid {NEUTRAL};
}}
QListWidget::item:selected {{
    background-color: {NEUTRAL};
    color: {NAVY};
    font-weight: 600;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {WHITE};
    border: none;
    border-bottom: 1px solid {LEADER};
    padding: 6px 4px;
    color: {INK};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-bottom: 2px solid {EMPHASIS};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {LEADER};
}}

QPushButton {{
    background-color: {WHITE};
    color: {NAVY};
    border: none;
    border-bottom: 2px solid {NEUTRAL};
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    border-bottom: 2px solid {EMPHASIS};
    color: {EMPHASIS};
}}
QPushButton:disabled {{
    color: {LEADER};
}}

QPushButton#runButton {{
    background-color: {NAVY};
    color: {WHITE};
    border: none;
    padding: 10px 22px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#runButton:hover {{
    background-color: {BLUE_MID};
}}
QPushButton#runButton:disabled {{
    background-color: {LEADER};
    color: {WHITE};
}}

QProgressBar {{
    border: none;
    background-color: {NEUTRAL};
    text-align: center;
    color: {NAVY};
    font-size: 12px;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background-color: {CYAN};
}}

QCheckBox {{
    spacing: 8px;
}}

QMenuBar, QMenu {{
    background-color: {WHITE};
    color: {INK};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background-color: {NEUTRAL};
    color: {NAVY};
}}

QStatusBar {{
    background-color: {WHITE};
    color: {INK_SOFT};
    border-top: 1px solid {NEUTRAL};
}}

QSplitter::handle {{
    background-color: {NEUTRAL};
    width: 1px;
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background: {WHITE};
    border: none;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {LEADER};
    border-radius: 4px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
"""
