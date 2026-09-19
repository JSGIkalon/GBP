# GBP — Simulador de proyección patrimonial

Herramienta interna de Ikalon que replica el modelo *Goals-Based Planning* de
J.P. Morgan: proyecciones de patrimonio por simulación Monte Carlo sobre un
portafolio multiactivo, con flujos, apalancamiento y comparación de estrategias.

Referencia: `HIP GBP 20260603.pdf` (presentación de J.P. Morgan a Hiptage
Investments Corp., jun 2026), que se usa como caso de control del motor.

---

## Estado

| Sesión | Alcance | Estado |
|---|---|---|
| 1 | Entorno, importador del LTCMA, modelo de dominio, motor Monte Carlo, apalancamiento, stress tests, librería de CMAs, tests | **Completa** |
| 2 | Interfaz PySide6: paneles de input, guardado/carga de casos, simulación en hilo | **Completa** |
| 3 | Gráficos (barras de rango, box plot), tablas de resumen, pestaña de estrés | **Completa** |
| 4 | Empaquetado a .exe portable con PyInstaller | **Completa** |
| 5+ | Series históricas, backtest, rolling returns y drawdowns; impuestos; exportación | Pendiente, sin decidir |

| 5 | Estrategias independientes, distribución con percentiles, marca y repaso visual | **Completa** |
| 6 | Supuestos de mercado bloqueados, arreglos de edición, progreso granular, informe PDF | **Completa** |

**La aplicación está terminada y funcionando.** 97 tests en verde y `dist\GBP.exe`
(81.3 MB) verificado con `tools/packaging_check.py` congelado: recursos
embebidos, persistencia en `%APPDATA%`, motor, interfaz e informe PDF.

## Cómo correrlo

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe run.py                       # abre la aplicación
.\.venv\Scripts\python.exe -m pytest tests\ -q          # 77 tests
.\tools\build_exe.ps1                                   # genera dist\GBP.exe

$env:PYTHONPATH="."; .\.venv\Scripts\python.exe tools\smoke_pdf_case.py
.\.venv\Scripts\python.exe tools\screenshot.py          # capturas para revisar maqueta
```

## Cómo se usa

1. **Escenario** — capital inicial, horizonte e inflación. Es lo común a toda la
   comparación.
2. **Estrategias** — cada una es un **caso completo**, con cuatro sub-pestañas:
   - **Pesos** — clases de activo por desplegable; deben sumar 100%.
   - **Flujos** — aportes y retiros propios de esa estrategia.
   - **Crédito** — apalancamiento propio de esa estrategia.
   - **Capital** — hereda el del escenario, o uno propio si se marca la casilla.
3. **Activos** y **Correlaciones** — supuestos de mercado, en solo lectura.
4. **Ajustes** — número de simulaciones (10.000 por defecto), semilla, años hito.
5. **Correr simulación** (o F5) y revisar las cuatro pestañas de resultado.
6. **Exportar PDF** (o Ctrl+E) para dejar el registro de la corrida y entregarlo.

Comparar dos planes distintos —uno apalancado contra uno sin deuda, o uno con
retiros tempranos contra otro que los aplaza— es crear dos estrategias y darle a
cada una sus flujos y su crédito. Se simulan con los mismos sorteos de mercado,
así que la diferencia que se ve es la del plan y no la del azar.

Archivo → Guardar caso produce un `.gbp.json` con el escenario. Los supuestos de
mercado nunca se guardan ahí: quedan en la librería global.

---

## Decisiones tomadas

- **Escritorio nativo** (PySide6), empaquetado final como **.exe portable** (sin instalador).
- **Motor multiactivo con correlaciones**, paso **anual**, valores nominales con vista en términos reales.
- **Sin buckets de metas**: una sola proyección de portafolio, con varias estrategias comparables.
- **Pre-tax** en v1. El motor no aplica impuestos; el hook queda para una sesión posterior.
- **10.000 simulaciones por defecto**, configurable desde la app.
- **Los supuestos de mercado no son input de la UI.** Ni las correlaciones ni el
  retorno, la volatilidad y el yield. Vienen del LTCMA y se muestran en modo
  lectura; se actualizan reimportando el documento. Son supuestos
  institucionales: si cada usuario los edita, dos personas con el mismo caso
  obtienen proyecciones distintas sin que nada lo deje ver.

## Arquitectura

```
run.py           punto de entrada
gbp/
  data/          correlations.json, ltcma_usd.json, brand/  (recursos embebidos)
  model/         assets, correlation, allocation, strategy, cashflows, leverage,
                 scenario, results
  engine/        montecarlo, summary, stress
  io/            library (CMAs + config global), caseio (casos de cliente),
                 report (informe PDF)
  ui/            main_window, worker (hilo), theme, brand, sample_case,
                 export_dialog
    panels/      scenario, strategies (con cashflow, leverage, capital dentro),
                 assets, correlation, settings, results
    charts/      canvas (con hover), box_chart, stress_chart, debt_chart
tools/           import_ltcma, extract_brand, smoke_pdf_case, packaging_check,
                 screenshot, build_exe.ps1
tests/           97 tests
```

### El modelo de estrategia

`Allocation` son **solo pesos** — es lo que consumen los supuestos resumen y el
stress test, que no saben nada de flujos. `Strategy` la envuelve y le agrega los
flujos, el crédito y un capital inicial opcional. Por eso el refactor a
estrategias independientes no tocó `engine/summary.py` ni `engine/stress.py`.

El sorteo de retornos es **único para toda la corrida**: se hace una vez sobre la
unión de clases de activo y lo comparten todas las estrategias. Es lo que hace
comparable el resultado, y hay un test que lo protege
(`test_estrategias_comparten_los_mismos_sorteos`).

### Estilo visual — Estilo Ikalon, Edición 2026

La interfaz sigue el manual de marca. Todo vive en `gbp/ui/theme.py`: la paleta,
la hoja de estilo Qt y los helpers de color. Decisiones que conviene no deshacer
sin pensarlo:

- **Paleta de datos cerrada a la gama azul** del manual, más gris, blanco y navy.
  Rojo, naranja, amarillo y verde están prohibidos en datos.
- **Sin marcos ni bordes de card.** El orden lo da el espacio y la jerarquía
  tipográfica, no las líneas. Las únicas líneas son el separador de filas de
  tabla y la rejilla horizontal, que sí codifican lectura.
- **Jost**, con Calibri como único sustituto autorizado.
- **Titulares descriptivos**: cada gráfico abre con una frase que dice la tesis,
  no con una etiqueta corta.
- **Semáforo**: el color de estado vive **solo dentro del círculo**; el texto va
  siempre en Ink. Es la única apertura de color fuera de la gama.
- **Azul de énfasis `#007ABA` solo en texto**, nunca como relleno.

**La tensión que esto genera, y cómo se resuelve.** Una paleta categórica normal
usa tonos distintos por serie; aquí las series son **pasos de intensidad de una
misma rampa azul**, que separan menos. Dos compensaciones:

1. **El orden de los pasos no es el de la rampa.** Es `navy → cyan → azul claro →
   azul medio`, elegido para que las primeras series sean las más separadas,
   porque casi todos los casos comparan dos o tres estrategias. Con el orden
   natural de la rampa, la primera y la tercera serie salían casi del mismo
   color — se detectó mirando una captura, no corriendo tests.
2. **La identidad nunca depende solo del color**: siempre hay leyenda, etiquetas
   directas en el último año hito y una tabla con los mismos números.

Otras reglas de los gráficos:

- **Percentiles 10 / 25 / 50 / 75 / 90**, no desviación estándar aritmética. El
  patrimonio es lognormal y asimétrico: una σ simétrica alrededor de la media da
  bandas inferiores sin sentido, a veces negativas. La media y la σ literal están
  en la tabla, para quien quiera el número crudo.
- **Etiquetas adaptativas.** La mediana y los bigotes se etiquetan siempre; los
  cuartiles se omiten cuando la caja es tan baja que chocarían con la mediana.
  Un número sobre cada marca satura el gráfico.
- **Un solo eje por gráfico.** Nunca un eje doble.
- El tope de estrategias comparables es el número de pasos de la rampa (4). Más
  allá no se inventan tonos: la interfaz lo impide.

### El informe PDF

`gbp/io/report.py` arma el PDF **con matplotlib**, no con una librería de
maquetación: no suma dependencias al ejecutable y reusa las mismas funciones de
`gbp/ui/charts/` que dibujan la pantalla, así que el informe no puede
desincronizarse de lo que el usuario vio. El adaptador `_FigureCanvas` finge ser
el lienzo de Qt (`clear`, `set_hover_probe`, `finish`) sobre una figura suelta.
El precio es paginar las tablas a mano, en `_table_pages`.

Dos reglas que conviene no deshacer:

- **Las páginas de gráfico no llevan titular propio.** Cada gráfico ya abre con
  su frase descriptiva, que es una regla del manual y vive dentro de la función
  que lo dibuja. Poner otro encima lo duplica palabra por palabra.
- **Nada de `●`, `→` ni símbolos fuera del latín básico.** Jost no trae esos
  glifos. En pantalla no se nota porque Qt hace fallback de fuente; en el PDF
  matplotlib los dibuja como cuadros vacíos. Las viñetas de color son
  rectángulos dibujados (`_swatch`), no texto.

### Dos trampas de Qt que ya costaron un bug cada una

**Recargar un editor desde su propia señal de cambio.** Cualquier cambio en
flujos, crédito o capital emitía `changed`; el panel de estrategias reconstruía
el desplegable; reconstruirlo movía el índice actual; mover el índice reemitía
`currentIndexChanged`; y eso recargaba el editor en mitad de la edición. Solo se
notaba fuera del índice 0, porque restaurar el índice 0 no emite señal — la
primera estrategia funcionaba y las demás no. Regla: `_on_child_changed` no
reconstruye la lista, solo refresca las marcas.



**Estilo de ítem contra color de modelo.** La hoja de estilo declara `QTableWidget::item`, y en cuanto existe una regla de
estilo para el ítem **Qt ignora el color de fondo que puso el modelo**. La matriz
de correlación salía toda blanca —sin rampa— y el 1.00 de la diagonal quedaba en
blanco sobre blanco. Se resolvió con `HeatmapDelegate` en
`gbp/ui/panels/correlation_panel.py`, que pinta el fondo él mismo. Si algún día
otra tabla necesita color de celda, hay que usar el mismo delegado.

### Dónde vive cada cosa

| Dato | Ubicación | Editable en la UI |
|---|---|---|
| Correlaciones | `gbp/data/correlations.json` (embebido) | No, solo lectura |
| Retorno / volatilidad / yield | `%APPDATA%/Ikalon/GBP/cma_library.json` | No, solo lectura |
| Nº de simulaciones, semilla, años hito | `%APPDATA%/Ikalon/GBP/settings.json` | Sí, en Ajustes |
| Portada del informe (autor, cliente) | `%APPDATA%/Ikalon/GBP/report_defaults.json` | Sí, al exportar |
| Caso del cliente (escenario + estrategias) | `.gbp.json` elegido por el usuario | Sí |
| Logos Ikalon | `gbp/data/brand/` (embebido) | No |

La librería de CMAs sigue viviendo en `%APPDATA%` y no dentro del ejecutable,
así que reemplazar el .exe no la pierde. Para cambiar un supuesto hay dos vías:
reimportar el LTCMA (`tools/import_ltcma.py`) o editar a mano ese JSON.

`GBP_DATA_DIR` sobrescribe la carpeta de datos del usuario; los tests la usan para aislarse.

---

## Modelo

Retornos **lognormales correlacionados** con paso anual. Trabajar en espacio
logarítmico evita pérdidas superiores al 100% en un año y reproduce el arrastre
de la volatilidad sobre el retorno compuesto.

Todas las estrategias comparadas se simulan con **los mismos números aleatorios**
(se sortean una sola vez sobre la unión de clases de activo del escenario), para
que las diferencias entre ellas vengan de la asignación y no del muestreo.

**Orden de operaciones de cada año:** desembolso del crédito → aportes → retorno
de mercado (rebalanceo anual a los pesos objetivo) → intereses y amortización →
retiros indexados a inflación → control de LTV y liquidación forzada.

### Convenciones que valen la pena recordar

- **Los flujos se ingresan en moneda de hoy** y se indexan desde el año 1, con factor
  `(1 + inflación)^año`. Esa es la convención de J.P. Morgan: reproduce exactamente
  el total de retiros de 47.2MM que reporta la lámina 9.
- **Un patrimonio agotado devenga a la tasa de caja**, no al retorno del portafolio:
  un saldo negativo es un descubierto, no una posición invertida.
- **La amortización se calcula sobre el principal original** con una tasa de referencia
  determinística, de modo que la cuota no cambie entre caminos. Cualquier saldo
  remanente al vencimiento —el caso típico con intereses capitalizados— se cancela
  íntegro en el último año.
- **Margin call**: vender activos para pagar deuda baja ambos lados por igual, así que
  el monto que devuelve el LTV al objetivo `t` sale de `d = (D - t·A) / (1 - t)`.
- **Probabilidad de éxito** = fracción de caminos en que el patrimonio neto nunca
  llega a cero o menos.

---

## Validación contra el PDF de J.P. Morgan

`tools/smoke_pdf_case.py` replica la lámina 9 (Lifestyle): 25.0MM iniciales,
retiro de 1.1MM al año por 29 años, inflación 2.5%.

**Supuestos resumen** — simulado vs. publicado:

| | Simulado | JPM |
|---|---|---|
| Retorno de largo plazo | 7.14% | 7.2% |
| Volatilidad | 9.85% | 9.7% |
| Retorno compuesto | 6.69% | 6.6% |
| Sharpe | 0.41 | 0.42 |

**Percentiles del patrimonio neto**, en millones:

| Año | p95 sim / JPM | p50 sim / JPM | p5 sim / JPM |
|---|---|---|---|
| 15 | 74 / 74 | 33 / 33 | 12 / 10 |
| 20 | 99 / 98 | 36 / 35 | 7 / 3 |
| 25 | 134 / 134 | 39 / 37 | −2 / −6 |
| 29 | 173 / 168 | 41 / 37 | −12 / −15 |

El total de retiros coincide exactamente (47.2MM). La probabilidad de éxito da
86.9% contra el 83.6% publicado.

**Stress tests** — los shocks por grupo, que se calibraron a ojo y no desde
series históricas, resultan sorprendentemente cerca de la lámina 11 del PDF:

| Escenario | Actual sim/JPM | Balanceado sim/JPM | Growth sim/JPM |
|---|---|---|---|
| Covid-19 | −17.4% / −16% | −15.1% / −14% | −22.1% / −20% |
| Crisis financiera | −29.6% / −29% | −25.8% / −26% | −36.3% / −34% |
| Puntocom | −17.1% / −16% | −11.5% / −11% | −29.0% / −28% |

Es una coincidencia razonable, no una validación: los shocks son estimaciones
editables, no retornos de índices. Sirve para confirmar que la ponderación por
clase de activo se comporta como debe.

**Por qué queda algo optimista.** El motor es levemente más benigno en la cola
baja. Dos causas conocidas, ninguna atribuible a un error de cálculo:

1. **Mapeo de clases de activo.** La presentación usa etiquetas que no existen en
   la tabla USD del LTCMA. En el script de control se mapearon
   "Developed World Equity" → `AC World Equity` y "Global Aggregate Bonds Hedged"
   → `World Government Bonds hedged`. No son equivalencias exactas.
2. **Comisiones.** El LTCMA es explícito en que sus supuestos son brutos de
   comisiones de gestión. J.P. Morgan probablemente descuenta algo en la
   proyección; el motor hoy no descuenta nada.

Conviene decidir con el usuario si se agrega un campo de comisión anual al
escenario, que cerraría buena parte de la diferencia.

---

## Pendientes y cabos sueltos

- **Yields en cero.** El LTCMA no publica yield por clase de activo, así que la
  librería se siembra con yield 0. El yield del resumen sale en 0.00% y no
  afecta la proyección (el motor usa el retorno total, no el yield por
  separado). Desde que los activos son de solo lectura, cargarlos exige editar
  `cma_library.json` o extender el importador; queda pendiente decidir cuál.
- **Comisión de gestión**: no modelada. Ver arriba.
- **Impuestos**: fuera de v1 por decisión explícita.
- **Stress tests**: hoy son shocks definidos a mano, con cuatro escenarios
  precargados (Covid, GFC, puntocom, shock de tasas 2022). Los shocks calculados
  desde series reales y el backtest de rolling returns y drawdowns dependen de
  incorporar datos históricos, que quedó para después.
- **Reparación PSD.** La matriz publicada no es exactamente semidefinida positiva
  (autovalor mínimo −0.016, normal por el redondeo a dos decimales). El JSON
  conserva los valores publicados y la reparación ocurre al cargar; el ajuste
  máximo es de 0.008, es decir cosmético.

## Empaquetado a .exe

```powershell
.\tools\build_exe.ps1     # -> dist\GBP.exe (81.3 MB, portable)
```

Es portable: se copia donde sea y se ejecuta, sin instalación. Guarda los
supuestos en `%APPDATA%\Ikalon\GBP`, así que reemplazar el .exe por una versión
nueva no pierde nada de lo que el usuario haya cargado.

`tools/packaging_check.py` es la verificación: se congela aparte como ejecutable
de consola y comprueba lo que no se ve desde el código fuente — que los recursos
del LTCMA viajen dentro del .exe, que la librería se escriba en `%APPDATA%` y no
junto al ejecutable, y que el motor y la interfaz completa funcionen congelados.

```powershell
$data = (Resolve-Path "gbp\data").Path
.\.venv\Scripts\python.exe -m PyInstaller --onefile --name gbp_packaging_check `
    --add-data "$data;gbp/data" --paths . --noconfirm tools\packaging_check.py
.\dist\gbp_packaging_check.exe
```

Tres trampas que ya costaron intentos fallidos:

- **La ruta de `--add-data` debe ser absoluta** si se usa `--specpath`, porque las
  rutas relativas se resuelven contra el directorio del `.spec`, no contra el proyecto.
- **PyInstaller escribe su log en stderr.** Con `$ErrorActionPreference = "Stop"`,
  PowerShell lo toma como error fatal aunque el empaquetado haya ido bien. El script
  lo baja a `Continue` y verifica el resultado por el archivo de salida.
- **La librería nunca debe quedar junto al ejecutable.** `app_data_dir()` la manda a
  `%APPDATA%` justamente para que sobreviva a las actualizaciones; el chequeo lo
  verifica con una aserción.

## Reimportar el LTCMA

Cuando salga la edición siguiente:

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe tools\import_ltcma.py "C:\ruta\ltcma-full-report.pdf"
```

El importador valida que cada fila traiga el número de correlaciones que le
corresponde y falla ruidosamente si la extracción se desalinea. Si J.P. Morgan
mueve la tabla de página, hay que ajustar `CANDIDATE_PAGES`.
