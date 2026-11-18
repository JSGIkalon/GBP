"""Textos de ayuda que se repiten en varios sitios de la interfaz.

Un solo lugar para que el tooltip, la tabla y la ventana de ayuda no puedan
contar la probabilidad de éxito de tres maneras distintas.
"""

SUCCESS_TOOLTIP = (
    "Probabilidad de éxito: fracción de los caminos simulados en que el patrimonio "
    "neto se mantiene por encima de cero en todos los años del horizonte. Es una "
    "estimación con los supuestos actuales, no una garantía."
)

SUCCESS_TITLE = "¿Qué es la probabilidad de éxito?"

SUCCESS_HTML = """
<p><b>Qué mide.</b> La fracción de los caminos simulados (10.000 por defecto, Monte
Carlo) en que el <b>patrimonio neto</b> —activos menos deuda— se mantiene por
encima de cero <b>en todos los años</b> del horizonte.</p>

<p><b>Cuándo un camino es un éxito.</b> Cuando nunca se agota. Un camino que llega
a cero en el año 12 y se recupera después por aportes cuenta como fallo. Un camino
que termina con 1 dólar cuenta igual que uno que termina con 50 millones: para eso
están la mediana, el CVaR y las metas.</p>

<p><b>Qué la mueve.</b></p>
<ul>
<li><b>Activos y pesos</b>: retorno compuesto, volatilidad y correlaciones del
LTCMA (y de los activos propios), con rebalanceo anual a los pesos objetivo.</li>
<li><b>Flujos</b>: aportes y retiros de la estrategia. Con retiros de monto fijo es
muy sensible; con solo retiros porcentuales sale cerca de 100%, porque el retiro
baja con el portafolio.</li>
<li><b>Inflación</b>: indexa los flujos marcados como indexados. No cambia el
criterio de éxito, que es en valores nominales.</li>
<li><b>Crédito</b>: si la deuda supera a los activos el camino fracasa, aunque
queden activos.</li>
<li><b>Capital inicial y horizonte</b> del escenario (o de la estrategia).</li>
<li><b>Monedas</b>: todo se proyecta en USD. Lo que está en COP (capital, activos
propios, flujos) se convierte con la tasa USD/COP y su devaluación esperada, un
camino fijo: <b>no hay riesgo cambiario</b> en la simulación. Ver los resultados en
COP no cambia la probabilidad.</li>
</ul>

<p><b>Qué no la mueve.</b> Las metas (tienen su propia probabilidad), la escala de
lectura y la moneda en que se miran los resultados.</p>

<p><b>Supuestos y límites.</b> Retornos lognormales e independientes año a año,
supuestos de mercado de largo plazo fijos durante todo el horizonte, correlaciones
constantes (no suben en las crisis, así que la cola mala es algo optimista), paso
anual, sin impuestos ni comisiones, sin riesgo cambiario y con la misma semilla en
cada corrida (por eso es reproducible). Con 10.000 caminos el error de muestreo es de alrededor de
±0,5 puntos porcentuales.</p>

<p><b>Es una estimación basada en los supuestos actuales, no una garantía de
resultados.</b> Si los supuestos cambian, la probabilidad cambia.</p>
"""
