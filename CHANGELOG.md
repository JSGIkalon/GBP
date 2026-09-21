# Log del proyecto

## Sesión 1 — 18 sep 2026

Arranque del proyecto. Se levantó el motor completo; la interfaz queda para la
sesión 2.

**Hecho**

- Entorno: `.venv` con numpy, pandas, PySide6, matplotlib, pytest, pyinstaller.
- `tools/import_ltcma.py`: importador real del LTCMA 2026 en PDF. Extrae la tabla
  de supuestos en USD (**59 clases de activo**) con la matriz de correlación
  completa y los retornos y volatilidades. Genera `gbp/data/correlations.json` y
  `gbp/data/ltcma_usd.json`.
- Modelo de dominio: clases de activo y conversión lognormal, matriz de
  correlación con reparación PSD, asignaciones, flujos, crédito y escenario.
- Motor Monte Carlo vectorizado, con números aleatorios comunes entre estrategias.
- Apalancamiento: amortización bullet / lineal / cuota fija, interés pagado o
  capitalizado, tasa fija o spread sobre caja, y margin call por LTV.
- Stress tests por shocks manuales, con cuatro escenarios precargados.
- Librería global de CMAs y configuración en `%APPDATA%/Ikalon/GBP/`, con
  escritura atómica y siembra automática desde el LTCMA.
- **60 tests**, todos en verde.

**Decisiones y hallazgos**

- La matriz de correlación **sale del LTCMA real**, no de una matriz provisional:
  el PDF resultó extraíble de forma limpia y verificable. Se descartó el generador
  por bloques que se había planteado como sustituto temporal.
- **Convención de indexación de flujos corregida contra la fuente.** El total de
  retiros del ejemplo daba 46.0MM contra los 47.2MM que publica J.P. Morgan:
  exactamente un año más de inflación. Sus montos están en moneda de hoy y se
  indexan desde el año 1. Con el cambio, el total coincide al decimal.
- **Bug de conversión lognormal.** `sigma_log` normalizaba por el retorno
  compuesto en vez de por la media aritmética, lo que hacía que la conversión no
  fuera reversible. Se resolvió por punto fijo; ahora ida y vuelta devuelve el
  valor original.
- **Bug en el Cholesky.** Con volatilidad cero la factorización caía al camino de
  reparación e inyectaba ruido numérico en activos que debían ser determinísticos.
  Ahora esas clases quedan con fila cero.
- **Bug de clasificación.** `Private Equity` caía en el grupo "equity" por contener
  esa palabra. Se reordenaron las palabras clave de más específicas a más generales.

**Validación**

El motor replica la lámina 9 del PDF de referencia con buena precisión: supuestos
resumen a menos de 0.15 puntos porcentuales y percentiles a distancia mínima. El
detalle y las dos causas conocidas de la diferencia residual —mapeo de clases de
activo y comisiones no modeladas— están en `PROJECT.md`.

**Empaquetado verificado por adelantado**

`tools/packaging_check.py` se congeló con PyInstaller y corrió como .exe real
(19 MB, `--onefile`). Confirma los dos riesgos que no se ven desde el código
fuente: los recursos del LTCMA viajan dentro del ejecutable y se resuelven vía
`sys._MEIPASS`, y la librería de CMAs se escribe en `%APPDATA%` y no junto al
.exe, donde se perdería al actualizar. El motor corre 10.000 simulaciones
congelado. Con esto, la sesión 4 es solo apuntar el empaquetado a la interfaz.

Comando de referencia:

```powershell
$data = (Resolve-Path "gbp\data").Path
.\.venv\Scripts\pyinstaller.exe --onefile --add-data "$data;gbp/data" --paths . <script>
```

La ruta de `--add-data` debe ser absoluta si se usa `--specpath`.

---

## Sesiones 2, 3 y 4 — 18 sep 2026

Interfaz, gráficos y ejecutable, de corrido. **La aplicación quedó terminada.**

**Hecho**

- Interfaz PySide6 con siete paneles de entrada (Escenario, Estrategias, Flujos,
  Apalancamiento, Activos, Correlaciones, Configuración) y cinco de resultado
  (Proyección, Distribución, Supuestos, Stress test, Deuda).
- Simulación en hilo aparte con barra de progreso: la ventana no se congela.
- Guardado y carga de casos en `.gbp.json`, con esquema versionado y errores
  legibles para archivos ajenos, rotos o de una versión futura.
- Gráficos: barras de rango p5–p95, box plot, stress test y evolución de deuda,
  todos con capa de hover.
- `tools/build_exe.ps1` → `dist\GBP.exe`, 79.5 MB, portable.
- `tools/screenshot.py` para revisar la maqueta sin abrir la app a mano.
- **77 tests** en verde (17 nuevos de interfaz y persistencia de casos).

**Hallazgos**

- **La maqueta estaba mal repartida y solo se vio al mirar una captura.** Los
  factores de estiramiento del splitter no bastan: Qt reparte según el ancho que
  pide cada panel, y las tablas de entrada piden mucho, así que los resultados
  quedaban en una columna estrecha con las etiquetas encabalgadas. Hubo que fijar
  los tamaños iniciales. Vale la pena mirar capturas, no solo correr tests.
- **Estaba poniendo un número sobre cada barra**, que es un antipatrón declarado
  de la guía de visualización. Ahora solo se etiqueta el último año hito; el resto
  se lee al pasar el mouse y está completo en la tabla de abajo.
- Las leyendas tapaban las barras más altas o más hondas; se movieron fuera del
  área de trazado.
- **PyInstaller escribe su log en stderr**, así que con `ErrorActionPreference =
  "Stop"` PowerShell aborta el script aunque el empaquetado haya ido bien.
- El chequeo de empaquetado, tal como se escribió primero, **escribía en la
  librería real del usuario**. Ahora se aísla en una carpeta temporal.

**Validación**

`tools/packaging_check.py`, congelado como ejecutable, confirma dentro del .exe:
59 clases del LTCMA embebidas, librería en `%APPDATA%`, 10.000 simulaciones y la
interfaz completa construida y dibujada.

Los stress tests dan −29.6% / −25.8% / −36.3% en la crisis financiera contra
−29% / −26% / −34% del PDF, pese a que los shocks se calibraron a ojo.

**Estilo Ikalon aplicado a la interfaz**

A pedido del usuario se aplicó el manual de marca (Edición 2026) a toda la app,
no solo a los gráficos:

- Paleta de datos cerrada a la gama azul + gris + blanco + navy. Se retiraron el
  naranja, el amarillo y el verde que traía la paleta anterior.
- Hoja de estilo Qt completa en `gbp/ui/theme.py`: sin marcos de card, sin bordes
  de caja, tipografía Jost con Calibri de respaldo, botón de simular en navy.
- Titulares descriptivos en todos los gráficos, en vez de etiquetas cortas.
- Semáforo conforme al manual: el color vive **solo dentro del círculo** de
  estado; el texto quedó en Ink. Antes la probabilidad de éxito y la suma de
  pesos se pintaban de verde o rojo, que el manual prohíbe expresamente.
- La matriz de correlación pasó de una rampa azul–rojo a una rampa dentro de la
  gama: navy para correlación positiva, cyan para negativa, gris en el cero.

**Un problema real que solo apareció al mirar la captura.** Al cerrar la paleta a
una sola familia, las series dejan de ser tonos distintos y pasan a ser pasos de
intensidad. Con el orden natural de la rampa, la primera y la tercera estrategia
salían prácticamente del mismo azul. Se reordenaron los pasos a
`navy → cyan → azul claro → azul medio`, de modo que las primeras series sean las
más separadas. Es una compensación, no una solución completa: por eso la
identidad de cada serie se apoya además en leyenda, etiquetas directas y tabla.

---

## Sesión 5 — 19 sep 2026

Siete cambios pedidos tras usar la aplicación. El de fondo: las estrategias dejan
de compartir los flujos y el crédito del escenario.

**Hecho**

- **Estrategias independientes.** `Strategy` envuelve a `Allocation` y le agrega
  flujos, crédito y capital inicial opcional. Ya se pueden comparar dos planes
  completos —uno apalancado contra uno sin deuda, o uno con retiros tempranos
  contra otro que los aplaza— en la misma corrida y sobre los mismos sorteos.
  `Allocation` quedó intacta, así que el motor de supuestos y el de estrés no se
  tocaron.
- **Persistencia esquema 2 con migración**: un caso guardado con la versión
  anterior abre igual; los flujos y el crédito del escenario se copian a cada
  estrategia, que es la semántica que tenían.
- **Fuera la pestaña Proyección.** Distribución hace el trabajo: box plot con
  percentiles 10/25/50/75/90, etiquetas numéricas y la tabla de cifras debajo,
  ahora con media y desviación estándar.
- **Años hito 5/10/15/20** por defecto, configurables. `milestones_within()` ya
  no agrega el horizonte por su cuenta.
- **Flujos y Apalancamiento dejan de ser pestañas de primer nivel** y pasan a ser
  sub-pestañas de la estrategia, junto con Pesos y Capital.
- **Clases de activo por desplegable** en cada fila de pesos, poblado con las que
  están a la vez en la librería y en la matriz del LTCMA.
- **Logos Ikalon**: símbolo y wordmark extraídos de la plantilla de
  presentaciones, visibles en la interfaz e integrados como ícono del ejecutable.
- **86 tests** en verde.

**El repaso visual encontró cosas que los tests no ven**

Lo primero fue arreglar la herramienta: `tools/screenshot.py` forzaba la
plataforma `offscreen` de Qt, que dibuja **todo el texto de widgets como cuadros
vacíos**. Las capturas de la ronda anterior eran inservibles justo para lo que se
necesitaban. Con la plataforma real aparecieron, en tres iteraciones:

- **Controles recortados** en el panel de estrategias (`regar cla`, `uitar clas`)
  y tablas cortadas a media columna. Causa: el panel de entrada era demasiado
  angosto y la lista lateral de estrategias se comía un cuarto del ancho. Se
  reemplazó por un selector desplegable arriba y se ensanchó el panel.
- **Las cinco pestañas de entrada no cabían** y Qt las escondía tras flechas de
  desplazamiento. Etiquetas más cortas.
- **Desplegables cortados** por altura de fila insuficiente, y el de "Tipo" en
  flujos porque `ResizeToContents` no mide los widgets de celda.
- **La matriz de correlación había perdido todo su color.** La hoja de estilo
  declara `QTableWidget::item`, y en cuanto existe esa regla Qt ignora el fondo
  que puso el modelo: la rampa desaparecía y el 1.00 de la diagonal quedaba en
  blanco sobre blanco. Se resolvió con un delegado que pinta el fondo él mismo.
- **La línea de la mediana cruzaba su propia etiqueta**, que parecía texto
  tachado.
- **El año 25 seguía apareciendo** pese al nuevo valor por defecto: la
  configuración persistida en `%APPDATA%` mandaba. Se agregó migración.

**Dos decisiones de criterio**

- **Percentiles y no desviación estándar aritmética.** El patrimonio simulado es
  lognormal y asimétrico; una σ simétrica alrededor de la media se va demasiado
  abajo —llega a dar negativa cuando casi ningún camino lo es— y se queda corta
  en la cola alta. La media y la σ literal quedaron en la tabla.
- **El ícono mezcla las dos piezas.** Un wordmark a 16×16 es una mancha
  ilegible, así que el `.ico` lleva el wordmark en los tamaños grandes y el
  símbolo en los pequeños. Hubo que escribir el archivo a mano: Pillow ignora
  `append_images` al guardar ICO y escribía un solo frame de 16×16.

**Otro fallo del script de empaquetado**: verificaba que `dist\GBP.exe` existiera,
no que fuera nuevo. Con el .exe anterior en ejecución PyInstaller no podía
sobrescribirlo y el script decía "Listo" sobre el archivo viejo. Ahora cierra las
instancias abiertas y compara la fecha.

**Pendiente de decisión del usuario**

- Un campo de **comisión anual de gestión** en el escenario. El LTCMA es bruto de
  comisiones y el motor no descuenta nada, que es la causa más probable de que la
  cola baja quede algo optimista frente al PDF.
- Cargar los **yields** a mano. Hoy están en cero y solo afectan la tabla de
  supuestos, no la proyección.
- Series históricas para backtest, rolling returns y drawdowns.
- Impuestos y exportación a Excel o PPTX.

## Sesión 6 — 19 sep 2026

Supuestos de mercado bloqueados, dos bugs de edición de estrategias, progreso
granular e informe PDF.

**Hecho**

- **Activos en solo lectura.** Retorno, volatilidad y yield dejaron de ser input
  de la interfaz: se actualizan reimportando el LTCMA, igual que las
  correlaciones, que ya lo eran. Se quitaron los botones de agregar, eliminar y
  restaurar.
- **Corregido: el crédito no se podía activar** en ninguna estrategia que no
  fuera la primera de la lista. La casilla se desmarcaba sola al pulsarla.
- **Corregido: los botones de flujos estaban al fondo del panel**, a media
  pantalla de la tabla. Se movieron encima, como en Pesos.
- **Barra de progreso real.** El progreso se cuenta por año simulado en vez de
  por estrategia, y la barra muestra el porcentaje.
- **Exportar informe PDF** (`Ctrl+E`, botón junto a «Correr simulación»): ventana
  previa con título, cliente, fecha, autor, notas y qué secciones incluir.
- **97 tests**, todos en verde.

**Decisiones y hallazgos**

- **La causa de los dos bugs de edición era la misma y estaba escondida en una
  señal de Qt.** Cualquier cambio en flujos, crédito o capital emitía `changed`;
  el panel de estrategias reconstruía el desplegable; reconstruirlo movía el
  índice actual; mover el índice reemitía `currentIndexChanged`; y eso recargaba
  el editor **en mitad de la edición**, pisando lo que el usuario acababa de
  hacer. Solo se notaba fuera del índice 0, porque restaurar el índice 0 no
  emite señal — por eso la primera estrategia funcionaba y las demás no.
  El arreglo es no reconstruir la lista: ninguno de esos paneles cambia el
  nombre de una estrategia, así que la lista no tenía nada que actualizar.
- **La casilla de apalancamiento leía `loan.active`**, que es `principal > 0`.
  Al marcarla el monto todavía era 0, así que la casilla se desmarcaba antes de
  que se pudiera escribir nada. Ahora refleja si la estrategia tiene crédito, y
  un semáforo avisa mientras el monto siga en cero.
- **El PDF se arma con matplotlib**, no con una librería de maquetación: no suma
  dependencias al .exe y reusa las mismas funciones de dibujo que la pantalla,
  así que el informe no se puede desincronizar de lo que el usuario vio. El
  precio es paginar las tablas a mano.
- **Las páginas de gráfico no llevan titular propio.** Cada gráfico ya abre con
  su frase descriptiva —regla del manual de marca, y vive dentro de la función
  que lo dibuja—, así que el titular de página lo duplicaba palabra por palabra.
  Se detectó mirando el PDF renderizado, no corriendo tests.
- **Jost no trae los glifos `●` ni `→`.** En pantalla nunca se notó porque Qt
  hace fallback de fuente; en el PDF matplotlib los dibujaba como cuadros
  vacíos. Las viñetas de color del informe son rectángulos dibujados, no texto.
- El progreso por estrategia no servía de nada en el caso más común: con una
  sola estrategia la barra saltaba de 0 a 100 sin pasar por el medio.
- **`dist\GBP.exe` regenerado** (81.3 MB) y verificado con
  `tools/packaging_check.py` congelado. Se le agregó al chequeo la generación
  del informe PDF: `matplotlib.backends.backend_pdf` no se importa en ningún
  otro camino de la app, así que si PyInstaller no lo recogiera el fallo
  aparecería solo en el .exe y solo al pulsar «Exportar PDF».

## Sesión 7 — 19 sep 2026

Un bug de fondo en el margin call, sesión persistente y lectura por clase de activo.

**Hecho**

- **Corregido: la llamada a margen creaba patrimonio de la nada.** El motor
  bajaba la deuda pero no los activos vendidos.
- **La sesión anterior se restaura al abrir.** Se acabó volver a ver el caso de
  ejemplo después de haber cargado uno real.
- **Botón «Borrar todas»** en Estrategias: vacía la comparación conservando
  capital, horizonte e inflación.
- **Vista por clase de activo** en Pesos y en el informe: renta variable, renta
  fija, alternativos y caja, derivada de los pesos por sub-clase.
- **123 tests**, todos en verde. `dist\GBP.exe` regenerado y verificado congelado.

**Decisiones y hallazgos**

- **El margin call estaba mal y ningún test lo veía.** `LoanSimulator.margin_call`
  devuelve el monto liquidado y ya lo resta del saldo de la deuda; el motor
  descartaba ese valor, así que los activos nunca bajaban. Consecuencias: el
  patrimonio neto **subía** al recibir una llamada a margen —vender para pagar
  deuda es neutro, no un ingreso— y los años siguientes capitalizaban sobre un
  portafolio que ya se había vendido. En una traza determinista con el
  portafolio cayendo 25% al año, el patrimonio neto pasaba de 5.7MM a 6.0MM
  entre el año 1 y el 2.
  Por qué no se detectó: los seis tests del margin call prueban
  `LoanSimulator` **en aislamiento**, donde la matemática es correcta, y el
  único test de integración solo comprobaba que hubiera liquidaciones
  (`forced_sales.max() > 0`), nunca que los activos bajaran. Salió al construir
  trazas deterministas para explicar el modelo, no corriendo la suite.
  La prueba nueva no mira el monto: afirma que **el patrimonio neto nunca sube
  en un escenario que solo pierde valor**, que es la propiedad que importa.
- **La sesión se guarda aparte del caso.** Guardar el `.gbp.json` sigue siendo
  explícito; `last_session.json` es una red, no un autoguardado que pise
  archivos del usuario. Una sesión corrupta cae al caso de ejemplo sin ruido:
  no poder abrir la app sería peor que perder la sesión.
- **Dos cortes de clases de activo conviven a propósito.** El de cuatro grupos
  (`model/groups.py`) responde "cómo se lee la asignación"; el de ocho
  (`engine/stress.py`) responde "qué se mueve junto en una crisis". Unificarlos
  obligaría a un corte que no sirve para ninguna de las dos.
- **La agregación es vista, nunca input.** Los pesos siguen cargándose por
  sub-clase, que es el único nivel al que existen retorno, volatilidad y
  correlación. Dejar escribir "renta variable 45%" exigiría una regla de reparto
  dentro del grupo, y esa regla sería un supuesto invisible más.

## Sesión 8 — 19 sep 2026

Salida de la restauración de sesión, autoguardado y un aviso de escala.

**Hecho**

- **Botón «Empezar de cero»** en el panel de Escenario: vacía capital,
  horizonte, inflación y todas las estrategias, y olvida la sesión guardada.
- **La sesión se guarda 1,5 s después del último cambio**, no solo al cerrar.
- **Aviso de escala en el capital inicial**: eco del monto formateado, y
  semáforo cuando el valor es menor que mil.
- **127 tests** en verde. `dist\GBP.exe` regenerado y verificado congelado.

**Decisiones y hallazgos**

- **Restaurar la sesión sin una salida es una trampa.** El reporte era «siempre
  que abro veo las mismas tres estrategias». La sesión funcionaba: el archivo
  guardaba capital 40 y horizonte 25, que eran ediciones reales del usuario y
  no los valores de fábrica. Lo que faltaba era poder vaciar el caso: el
  ejemplo se carga la primera vez y desde entonces la restauración lo devuelve
  fielmente, para siempre. Diagnosticarlo fue leer el JSON guardado, no releer
  el código — la hipótesis inicial (que la persistencia no escribía) era falsa
  y se descartó en dos comandos.
- **Empezar de cero borra también la sesión guardada.** Si solo vaciara el caso
  en memoria, un cierre inesperado antes del siguiente guardado resucitaría lo
  que se acaba de borrar.
- **Guardar solo al cerrar no alcanza** para "los cambios deben mantenerse": un
  cierre inesperado se lleva todo. Guardar en cada señal `changed` tampoco, que
  se emite por pulsación de tecla. El retardo de 1,5 s es el punto medio, y al
  cerrar se cancela el pendiente y se escribe ya.
- **El campo de capital está en unidades y eso no se veía.** En el caso real del
  usuario decía `40`: cuarenta dólares con retiros de 1.1MM al año, así que la
  proyección salía negativa desde el año 1 y el patrimonio mediano final daba
  −38MM. No se impide —un capital pequeño es legítimo— pero ahora el campo
  hace eco de la escala y avisa por debajo de mil.

## Sesión 9 — 19 sep 2026

Activos propios: la app deja de servir solo para patrimonios en EE.UU.

**Hecho**

- **Clases de activo propias** con retorno y volatilidad fijados a mano, para
  patrimonio que el LTCMA no cubre (renta fija colombiana, finca raíz local).
- El analista solo declara **la clase de activo**; la app deriva correlaciones,
  shock de estrés y grupo de la vista agrupada.
- Panel de Activos con columnas **Origen** y **Clase**, y diálogo de creación
  con vista previa en vivo de lo que se va a derivar.
- Los activos propios **viajan dentro del `.gbp.json`** y se fusionan al abrir.
- Página nueva en el informe PDF con los supuestos declarados.
- **167 tests**. `dist\GBP.exe` regenerado y verificado congelado.

**Decisiones y hallazgos**

- **El obstáculo no era el que parecía.** Retorno y volatilidad son campos
  sueltos; el problema son las correlaciones, porque el motor necesita una fila
  y una columna por activo y `montecarlo.py` reventaba con un `KeyError` para
  cualquier nombre fuera de la matriz publicada.
- **"El promedio de su clase" no es una aproximación tosca: es realizable.**
  Con `z = λ·p + sqrt(1 − λ²·var(p))·ε`, la matriz extendida es la correlación
  de un vector aleatorio explícito y por tanto PSD **por construcción**. No se
  repara con `nearest_psd` a propósito: hacerlo destruiría las correlaciones
  derivadas exactas para arreglar un problema inexistente.
- **La clase Caja tiene un solo miembro y eso rompía el diseño.** `var(p) = 1`
  para `U.S. Cash`, así que una caja colombiana salía como clon perfecto y la
  matriz exactamente singular. `cholesky_factor` lo habría sobrevivido por su
  empujón en la diagonal, pero apoyarse en esa red para un caso previsible es
  malo. Se cierra con `CORRELATION_CAP = 0.95`, que solo actúa donde hace falta.
  Salió midiendo `var(p)` de las cuatro clases antes de escribir una línea.
- **El promedio del bloque debe incluir la diagonal.** Es el error silencioso
  más probable de todo el cambio: excluir los términos `g == h` rompe la
  garantía de PSD sin que nada falle ni se note. Tiene test propio.
- **La app no convierte monedas, y es decisión, no pereza.** Meter un 10% en
  pesos con 2% de volatilidad sin descontar devaluación baja la volatilidad del
  portafolio al 6% y dispara la probabilidad de éxito al 100%: el informe sale
  espectacular y está mal. El diálogo lo advierte con el ejemplo numérico.
- **El caso manda sobre la librería en un conflicto de supuestos.** Un informe
  entregado a un cliente tiene que poder reproducirse tal cual; si la librería
  local se impusiera en silencio, el mismo archivo daría dos proyecciones en dos
  computadores — exactamente la falla que motivó bloquear el panel de Activos.
- **El resolvedor de clases va como campo de `StressScenario`, no como
  parámetro.** Así `impact()`, `breakdown()`, `run_stress_tests()` y el gráfico
  de estrés no cambian de firma: el resolvedor se pone una vez con
  `with_resolver()` y el resto del código no se entera.
- **`from_dict` no pasó a devolver una tupla.** Habría roto a todos sus
  llamadores, entre ellos la restauración de sesión. Los activos propios se leen
  con una función hermana, `custom_assets_from_dict`.
- **`reset_cmas_to_ltcma()` ya no borra los activos propios.** No vienen del
  LTCMA, así que reimportarlo no puede ser motivo para perderlos — y hacerlo
  dejaría casos guardados imposibles de abrir.
- **Una captura destapó un hueco que los tests no veían**: el panel de Activos
  no se refrescaba cuando la librería cambiaba por fuera, que es justo lo que
  pasa al abrir un caso con activos propios nuevos.
- Límite conocido: el promedio de "Alternativos" mezcla oro, private equity,
  hedge funds e inmobiliario. Es defendible, y si hiciera falta precisión el
  camino es dejar elegir un activo de referencia concreto — la regla está
  aislada en `extend_correlations`, así que no obliga a rehacer nada.

## Sesión 10 — 21 sep 2026

Reestructuración del informe PDF y retiro del stress test.

**Hecho**

- **Las tablas de datos se mueven a un anexo numerado al final.** Cada gráfica
  cita la suya ("Detalle en el Anexo · Tabla 2"). La de supuestos resumen se
  queda en el cuerpo: es narrativa, no dato de consulta.
- **Nueva lámina de asignación de activos** (`ui/charts/allocation_chart.py`),
  en dos paneles: barra apilada por clase de activo arriba, barras agrupadas por
  sub-clase abajo. También es pestaña en la interfaz, en el sitio que dejó el
  stress test. No depende de la simulación: se ve mientras se arma el caso.
- **Nuevo orden del documento**: portada, supuestos del caso, asignación,
  distribución, supuestos resumen, deuda, anexo. Los supuestos del caso pasan a
  ser la primera página después de la portada.
- **El stress test se retira del proyecto**: se borran `engine/stress.py` y
  `ui/charts/stress_chart.py`, su pestaña, su sección del informe y sus tests.
- `ChartCanvas.panels()` y su gemelo en el adaptador del PDF: varios ejes
  apilados para los gráficos que responden dos preguntas a la vez.
- **157 tests**, todos en verde.

**Decisiones y hallazgos**

- **La gráfica de asignación no colorea las sub-clases por intensidad de su
  clase.** Se probó: con siete sub-clases los pasos de intensidad de una clase
  chocan con los de la vecina —el segundo tono de renta variable sale igual al
  primero de renta fija— y el color deja de decir a qué clase pertenece cada
  tramo. La paleta tiene cuatro pasos y no se inventan tonos, así que se separan
  las dos preguntas en dos paneles y en el de detalle el color codifica la
  **estrategia**, no la clase.
- **Mezclar hacia blanco desatura.** El primer intento de rampa de intensidad
  volvía gris el navy; subir la luminosidad en HLS dejando tono y saturación
  intactos mantiene el azul. Queda anotado aunque la rampa no se use.
- **El solapamiento del pie de página venía de `box_chart`**, que escribía su
  nota con `annotate(xy=(0, -0.16), xycoords="axes fraction")`. Colgando por
  debajo del eje, en la geometría de página del informe aterrizaba encima del
  título y la fecha. Ahora va como `set_xlabel`, que el eje sí reserva, y la
  nota de página bajó para dejarle sitio.
- **Los números del anexo se reservan antes de escribir la primera página.** Las
  gráficas del cuerpo los citan y el PDF se escribe de una sola pasada con
  `PdfPages`; sin reservarlos primero harían falta dos.
- La lámina de asignación usa un margen izquierdo mucho más ancho que las demás
  —los nombres de sub-clase son largos— así que su titular recibe un
  desplazamiento explícito para no quedar sangrado media página.
- **La auditoría visual encontró cinco defectos que ningún test ve**: las dos
  notas al pie pegadas, el orden de estrategias invertido entre los dos paneles,
  la leyenda del gráfico de deuda encima de la línea, el titular sangrado y los
  años rotulados como 2.5 / 5.0.

