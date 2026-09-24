# El modelo de proyección de GBP

Cómo GBP proyecta el patrimonio de un cliente, qué supone y qué no.

Este documento describe el **modelo**, no el código. Cuando hace falta señalar
dónde vive una regla, se cita el archivo; pero se puede leer entero sin abrir el
proyecto. Para la arquitectura y las decisiones de ingeniería, ver `PROJECT.md`.

---

## Índice

1. [La pregunta que responde](#1-la-pregunta-que-responde)
2. [Los supuestos de mercado](#2-los-supuestos-de-mercado)
3. [Por qué lognormal](#3-por-qué-lognormal)
4. [El sorteo: de dónde salen los retornos](#4-el-sorteo-de-dónde-salen-los-retornos)
5. [Por qué importa la correlación](#5-por-qué-importa-la-correlación)
6. [El año, paso a paso](#6-el-año-paso-a-paso)
7. [Flujos](#7-flujos)
8. [Apalancamiento](#8-apalancamiento)
9. [De los caminos a los números](#9-de-los-caminos-a-los-números)
10. [Los supuestos resumen](#10-los-supuestos-resumen)
11. [Activos fuera del LTCMA](#11-activos-fuera-del-ltcma)
12. [Qué no hace el modelo](#12-qué-no-hace-el-modelo)
13. [Validación contra la fuente](#13-validación-contra-la-fuente)

---

## 1. La pregunta que responde

GBP responde una sola pregunta, y conviene enunciarla con precisión:

> Dado un capital inicial, una mezcla de activos, unos aportes y retiros, y
> eventualmente un crédito, **¿cómo se distribuye el patrimonio del cliente a lo
> largo del horizonte, y con qué probabilidad el plan se sostiene?**

No es un pronóstico. El resultado no es "el patrimonio será X en el año 20",
sino una **distribución** de miles de trayectorias posibles, todas consistentes
con los mismos supuestos de mercado de largo plazo.

El modelo replica la metodología *Goals-Based Planning* de J.P. Morgan, usando
como caso de control la lámina 9 del documento de referencia.

### Lo que el modelo compara

La unidad de comparación es la **estrategia**, y una estrategia es un *plan
completo*: su mezcla de activos, sus propios aportes y retiros, su propio
crédito y, si se quiere, su propio capital inicial. Eso permite comparar cosas
que de otro modo no serían comparables —un plan apalancado contra uno sin deuda,
o uno con retiros tempranos contra otro que los aplaza— y no solo dos
asignaciones de activos.

Lo común a toda la corrida es el **escenario**: capital inicial, horizonte e
inflación.

---

## 2. Los supuestos de mercado

Cada clase de activo se describe con tres números:

| Supuesto | Qué es |
|---|---|
| **Retorno compuesto** | El retorno geométrico esperado de largo plazo |
| **Volatilidad** | La desviación estándar anual del retorno |
| **Yield** | La porción del retorno que llega como flujo, no como apreciación |

Más la **matriz de correlación** entre todas las clases.

### De dónde vienen

Del **LTCMA 2026 de J.P. Morgan**, tabla de supuestos en USD: 59 clases de
activo con su retorno compuesto, volatilidad y matriz de correlación completa.
Viajan embebidos en la aplicación.

**No son input de la interfaz.** Se muestran en modo lectura y se actualizan
reimportando el documento. La razón no es técnica sino de gobierno: son
supuestos institucionales, y si cada usuario los edita, dos personas con el mismo
caso obtienen proyecciones distintas sin que nada lo deje ver.

> **Nota sobre el yield.** El LTCMA no publica yield por clase de activo, así que
> la librería se siembra con yield 0. Aparece como 0.00% en los supuestos resumen
> y **no afecta la proyección**: el motor usa el retorno total, no el yield por
> separado. Es un dato informativo pendiente de cargar.

---

## 3. Por qué lognormal

El motor no trabaja con el retorno directamente sino con su **logaritmo**. Dos
razones, y las dos son sustantivas.

**Ningún activo puede perder más del 100% en un año.** Con retornos normales sí
podría: un activo con 8% esperado y 20% de volatilidad tiene, bajo una normal,
probabilidad no nula de caer 150%. Saldrían patrimonios negativos por razones
puramente aritméticas. En espacio logarítmico el retorno bruto es `exp(algo)`,
que nunca es negativo.

**Reproduce el arrastre de la volatilidad.** Un activo con 8% de retorno
esperado y 15% de volatilidad **no compone al 8%**: compone a menos, y la brecha
crece con la volatilidad. Es lo que hace que dos estrategias con el mismo retorno
esperado y distinta volatilidad no terminen en el mismo sitio.

### La conversión

J.P. Morgan publica el retorno **compuesto** y la volatilidad **aritmética**. La
conversión al espacio logarítmico es:

```
mu_log = ln(1 + retorno_compuesto)
```

La volatilidad es más delicada. Para una lognormal, la volatilidad aritmética
reportada se relaciona con la **media aritmética** `m = E[1+R]`, no con el
retorno compuesto:

```
sigma² = m² · (exp(sigma_log²) − 1)     donde  m = (1 + compuesto) · exp(sigma_log²/2)
```

Como `m` depende a su vez de `sigma_log`, no hay forma cerrada: se resuelve por
**punto fijo** ([assets.py:95-119](gbp/model/assets.py#L95-L119)). Converge en
pocas iteraciones.

> **Por qué importa que sea reversible.** Con la conversión correcta, aplicar
> `arithmetic_return` y volver al compuesto devuelve el valor original. Eso es lo
> que permite comparar los supuestos resumen con los publicados por J.P. Morgan y
> verificar que el motor parte de donde debe. Una versión temprana normalizaba por
> el retorno compuesto en vez de por la media aritmética y la ida y vuelta no
> cerraba; era un error silencioso que solo se vio al contrastar contra la fuente.

---

## 4. El sorteo: de dónde salen los retornos

El paso es **anual**. Por defecto se sortean **10.000 caminos** con semilla fija
(42), ambos configurables.

El sorteo se hace **una sola vez para toda la corrida**, sobre la unión de clases
de activo que usan todas las estrategias. El resultado es un bloque de

```
(caminos × años × clases de activo)
```

Con 10.000 caminos, 20 años y 8 clases son 1,6 millones de retornos.

### Números aleatorios comunes

Ese bloque lo comparten **todas las estrategias**. Es una decisión deliberada y
es lo que hace honesta la comparación: si cada estrategia sorteara su propio
azar, una podría verse mejor solo por haber tenido suerte en su muestra. Con los
mismos sorteos, la diferencia que se observa entre dos estrategias **es la
estrategia**.

Hay un test dedicado a proteger esa propiedad
(`test_estrategias_comparten_los_mismos_sorteos`).

### La caja siempre entra al sorteo

Aunque ninguna estrategia la use. De ella dependen dos cosas: la tasa del crédito
cuando se define como spread sobre caja, y el devengo de un patrimonio agotado.

---

## 5. Por qué importa la correlación

Este es el núcleo conceptual del modelo.

### El mecanismo

Se sortean shocks normales **independientes** y se multiplican por el factor de
Cholesky de la matriz de covarianza ([montecarlo.py:79-84](gbp/engine/montecarlo.py#L79-L84)):

```python
cov_log = covariance(sigma_log, corr)
factor  = cholesky_factor(cov_log)
shocks  = rng.standard_normal((n_paths, horizon, n_activos))
log_returns = mu_log + shocks @ factor.T
```

Esa multiplicación es lo único que convierte ruido independiente en **un mundo
coherente**. Sin ella, en un mismo camino-año la renta variable desarrollada
podría caer 30% mientras la emergente sube 20%, porque nada las ata.

### La razón de fondo: el portafolio se agrega *después* del sorteo

El retorno del portafolio no se simula directamente. Se calcula activo por activo
y luego se pondera:

```
retorno_portafolio = retornos_por_activo · pesos
```

Esto significa que **el motor nunca recibe la volatilidad del portafolio como
input: la produce**, a partir de las volatilidades individuales y la matriz.

Por eso la correlación no es un refinamiento opcional. Es lo que define el riesgo
agregado.

### Qué pasaría sin ella

Si los activos fueran independientes, la diversificación sería perfecta y los
riesgos se cancelarían entre sí. El efecto sería sistemático, no menor:

- La **volatilidad del portafolio saldría muy subestimada**
- Los **percentiles bajos** se verían mucho mejores de lo que son
- El **CVaR** quedaría artificialmente contenido
- La **probabilidad de éxito** saldría inflada

Es decir: precisamente los números sobre los que se toma la decisión del plan.

### Donde más se nota: el apalancamiento

Con crédito el efecto se amplifica. El LTV se evalúa cada año contra el valor del
portafolio, y una llamada a margen fuerza vender en el peor momento. La
probabilidad de que eso ocurra depende enteramente de con qué frecuencia el
portafolio **entero** cae a la vez —que es justo lo que codifica la correlación.
Con activos independientes las llamadas a margen casi desaparecerían, y sería un
artefacto del modelo, no un hallazgo.

### La matriz publicada no es del todo consistente

Viene redondeada a dos decimales y estimada sobre ventanas distintas, así que
**no es exactamente semidefinida positiva**: su autovalor mínimo es del orden de
−0.016. Una matriz así describe un mundo imposible —alguna combinación de activos
tendría varianza negativa— y no admite factorización de Cholesky.

La aplicación la proyecta a la PSD más cercana al cargarla, truncando autovalores
negativos y renormalizando la diagonal a 1. El JSON conserva los valores
originales tal como los publica J.P. Morgan, y se guarda cuánto hubo que
corregir: el ajuste máximo es de **0.008**, cosmético pero auditable.

---

## 6. El año, paso a paso

Para cada camino y cada año, en este orden
([montecarlo.py:138-167](gbp/engine/montecarlo.py#L138-L167)):

| # | Paso |
|---|---|
| 1 | **Desembolso del crédito**, si corresponde a ese año |
| 2 | **Aportes** |
| 3 | **Retorno de mercado**, con rebalanceo anual a los pesos objetivo |
| 4 | **Intereses y amortización** del crédito |
| 5 | **Retiros**, indexados a la inflación |
| 6 | **Control de LTV** y liquidación forzada si aplica |

**El orden no es cosmético.** Que los retiros vayan después del retorno significa
que se gasta sobre el patrimonio ya crecido; al revés daría otro número. Que la
llamada a margen vaya al final significa que se evalúa contra el patrimonio
después de todos los movimientos del año.

### Dos reglas que conviene conocer

**El rebalanceo está implícito en la aritmética.** El retorno del portafolio se
calcula ponderando con los pesos *objetivo* cada año, lo que equivale a volver a
la mezcla objetivo al cierre de cada año. El modelo **no** deja derivar la
composición con el tiempo.

**Un patrimonio agotado es un descubierto, no una posición invertida.** Si los
retiros consumen el portafolio, el saldo queda negativo y a partir de ahí devenga
a la **tasa de caja**, no al retorno del portafolio
([montecarlo.py:146](gbp/engine/montecarlo.py#L146)). Sin esa regla, una deuda de
50.000 millones "capitalizaría" al 7% anual como si fuera un portafolio
invertido, lo cual es absurdo y haría ver mejor de lo que son los caminos que ya
fracasaron.

---

## 7. Flujos

Un flujo es un aporte o un retiro recurrente entre un año inicial y uno final,
ambos inclusive. El año 1 es el primer año proyectado.

### La convención de indexación

El monto ingresado es **el que se paga el año 1**, y se indexa desde el año 2
con factor `(1 + tasa)^(año − 1)`
([cashflows.py](gbp/model/cashflows.py)). Un retiro de 1.000 con inflación de 5%
vale 1.000 el año 1, 1.050 el año 2 y 1.102,5 el año 3. Un flujo que empieza más
tarde también se expresa en pesos del año 1.

**Esto se aparta de J.P. Morgan a propósito.** J.P. Morgan indexa desde el año 1,
con factor `(1 + tasa)^año`, y con esa convención el total de retiros del
ejemplo de referencia coincidía al decimal con sus 47,2MM. Ikalon decidió que el
monto que se ingresa es el del primer año, tal cual; con eso el mismo ejemplo da
46,0MM, un año menos de inflación.

### Dos fuentes de crecimiento, acumulables

- **Indexación a inflación**: el flujo sigue la inflación del escenario. Es lo
  típico de un gasto de estilo de vida.
- **Crecimiento real**: un crecimiento adicional por encima de la inflación.

Si se activan los dos, se componen: `(1 + inflación) · (1 + crecimiento) − 1`.

---

## 8. Apalancamiento

El crédito se simula **camino a camino**, porque dos cosas dependen del
escenario: la tasa, cuando se define como spread sobre la tasa de caja, y las
llamadas a margen, que dependen del valor del portafolio en ese camino.

### Parámetros

| Parámetro | Opciones |
|---|---|
| **Tasa** | Fija, o spread sobre la tasa de caja |
| **Intereses** | Pagados (salen del portafolio) o capitalizados (se suman al saldo) |
| **Amortización** | Bullet, lineal o cuota fija (francesa) |
| **LTV** | Máximo y objetivo tras la llamada a margen |

### El cronograma de amortización

Se expresa como fracciones del **principal original** y se calcula **una sola
vez**, con una tasa de referencia determinística. Eso mantiene la cuota estable
aunque la tasa realizada varíe entre caminos, que es como funciona un crédito en
la práctica.

Cualquier saldo remanente al vencimiento —el caso típico cuando los intereses se
capitalizan— se paga íntegro en el último año.

### La llamada a margen

Si el saldo de la deuda supera el LTV máximo del valor del portafolio, se
liquidan activos hasta volver al LTV objetivo.

El monto se deduce de que **vender activos para pagar deuda reduce ambos lados
por igual**. Si `D` es la deuda, `A` los activos y `t` el LTV objetivo, el monto
`d` a liquidar sale de:

```
(D − d) / (A − d) = t       →       d = (D − t·A) / (1 − t)
```

Nunca se vende más de lo que hay ni más de lo que se debe.

> **Un error que costó un bug.** Como la venta baja activos y deuda por igual, el
> **patrimonio neto no cambia** en ese instante. Una versión temprana descontaba
> la deuda pero no los activos: el patrimonio neto *subía* al recibir una llamada
> a margen —imposible— y los años siguientes capitalizaban sobre un portafolio
> que ya se había vendido.

---

## 9. De los caminos a los números

**Nada se supone sobre la forma de la distribución.** Todos los indicadores salen
de contar los caminos simulados.

| Indicador | Cómo se calcula |
|---|---|
| **Percentiles** | p10 / p25 / mediana / p75 / p90, directo sobre los caminos |
| **Probabilidad de éxito** | Fracción de caminos en que el patrimonio **nunca** toca cero |
| **CVaR 5%** | Promedio del peor 5% de los caminos |
| **Patrimonio mediano final** | Mediana del último año |

### Por qué percentiles y no bandas de desviación estándar

El patrimonio simulado es lognormal y **asimétrico a la derecha**. Una banda
simétrica alrededor de la media se va demasiado abajo —llega a dar negativa
cuando casi ningún camino lo es— y se queda corta en la cola alta. Los
percentiles salen directo de los caminos y no fingen una simetría que no existe.

### La probabilidad de éxito es más estricta de lo que parece

Un camino "falla" si **en algún año** el patrimonio neto llega a cero o menos
([results.py:91-97](gbp/model/results.py#L91-L97)). No es "termina positivo": un
camino que se agota en el año 12 y se recupera contablemente después **sigue
contando como fallo**. Es la definición correcta para un plan de gasto, donde
quedarse sin patrimonio a mitad de camino no se deshace.

### El CVaR no es el percentil 5

Es el **promedio de todo lo que hay detrás** de ese corte. Responde «si las cosas
salen mal, ¿qué tan mal en promedio?», que es distinto de «¿cuál es el corte del
peor 5%?».

### Valores nominales y reales

Por defecto todo se reporta en **valores nominales**. La aplicación puede
mostrarlo en **moneda de hoy**, dividiendo por el factor de inflación acumulado
de cada año. Es una vista, no un recálculo: la simulación es la misma.

---

## 10. Los supuestos resumen

Además de la simulación, se calcula para cada estrategia una tabla de
estadísticas **por fórmula cerrada** ([summary.py](gbp/engine/summary.py)):

| Indicador | Cómo |
|---|---|
| **Retorno de largo plazo** | Promedio ponderado de los retornos aritméticos |
| **Volatilidad** | `√(wᵀ Σ w)` — usa la matriz de correlación |
| **Retorno compuesto** | El aritmético menos el arrastre de la volatilidad |
| **Yield** | Promedio ponderado de los yields |
| **Sharpe** | `(retorno − tasa libre de riesgo) / volatilidad` |

La tasa libre de riesgo es el retorno compuesto de la clase de caja.

**Estos números no son una predicción**: explican con qué se construyó la
proyección. Y son un contraste útil, porque la volatilidad calculada por fórmula
cerrada debería coincidir con la que arroja la simulación. Es el mismo insumo
—las correlaciones— usado de otra forma.

---

## 11. Activos fuera del LTCMA

El LTCMA cubre 59 clases en USD. Un cliente colombiano tiene TES, CDT y finca
raíz en Bogotá, y nada de eso está ahí.

### La asimetría del problema

El retorno y la volatilidad son un número cada uno: el analista los puede
estimar. **Las correlaciones son 59 números nuevos por activo**, y nadie los va a
escribir a mano ni con criterio. Pero el motor necesita la fila completa, porque
factoriza la matriz entera.

### El principio

> Un activo propio se comporta como **el promedio de su clase de activo**, más su
> propio riesgo idiosincrático, con el retorno y la volatilidad que el analista
> fija.

El analista declara una clase —renta variable, renta fija, alternativos o caja— y
de ese único dato sale todo. Si `p` es el portafolio equiponderado de las clases
LTCMA de esa clase, en retornos estandarizados, el activo se construye como:

```
z = λ·p + √(1 − λ²·var(p))·ε        con ε independiente de todo lo demás
```

de donde `corr(z, X) = λ · promedio de corr(g, X)`.

**La matriz extendida es semidefinida positiva por construcción**, porque es la
correlación de un vector aleatorio que existe de verdad. No hace falta repararla,
y de hecho no se debe: pasarla por la reparación PSD destruiría correlaciones
derivadas exactas para arreglar un problema que no existe.

### El caso degenerado, que es real

`var(p) ≤ 1` siempre, con igualdad solo si la clase tiene **un solo miembro**. La
clase "Caja" del LTCMA tiene exactamente uno (`U.S. Cash`), así que con λ = 1 una
caja colombiana saldría correlacionada **1.00** contra el T-bill: un clon sin
riesgo propio, y la matriz exactamente singular.

De ahí un tope de cuánta varianza puede explicar la clase (`λ = min(1, √(cap/var(p)))`,
con cap = 0.95). Para las clases pobladas λ = 1 y no cambia nada. Es honesto
además de conveniente: **un CDT en pesos no es un T-bill**.

### Límites de esta derivación

**La granularidad de la clase manda.** Dos activos propios de la misma clase
quedan correlacionados a `λ²·var(p)` —muy parecidos entre sí. Si TES y CDT se
declaran en la misma clase, el modelo los tratará casi como el mismo activo.

**La moneda no está modelada.** El riesgo idiosincrático `ε` es un cajón donde
cae todo lo que la clase no explica: país, emisor y moneda juntos. Pero la
exposición cambiaria de varios activos locales contra una matriz denominada en
dólares es **común a todos ellos**, no idiosincrática. El modelo la trata como
independiente entre activos, lo cual **subestima la correlación entre activos
locales** en un escenario de devaluación. Es el límite que más pesa si el caso
tiene varios activos locales con peso significativo.

**El tope de 0.95 es un parámetro elegido**, no sale de ningún dato. Resuelve la
singularidad y es razonable, pero para un activo local que sí sigue de cerca a su
clase podría quedar bajo.

---

## 12. Qué no hace el modelo

Enunciar los límites es parte del modelo. Estos son deliberados y conocidos.

### Correlaciones constantes

Las correlaciones del LTCMA son supuestos de **largo plazo, constantes en el
tiempo y a lo largo de toda la distribución**. El modelo no captura que las
correlaciones entre activos de riesgo **tienden a subir hacia 1 justo en las
caídas fuertes**, que es cuando la diversificación más se necesita.

**Consecuencia directa: los percentiles extremos de la cola izquierda son, por
construcción, algo optimistas.** Conviene tenerlo presente al leer el CVaR.

### Sin impuestos

El modelo es **pre-tax** por decisión explícita. No aplica impuestos a los
retornos, a los retiros ni a las ventas forzadas.

### Sin comisiones de gestión

No están modeladas. Es una de las dos causas conocidas de la diferencia residual
contra los números publicados por J.P. Morgan.

### Paso anual

No hay estacionalidad, ni rebalanceo intra-anual, ni secuencia de retornos dentro
del año. Un año es la unidad mínima.

### Sin buckets de metas

Una sola proyección de portafolio, con varias estrategias comparables. No se
modelan metas separadas con horizontes y prioridades distintas.

### Sin datos históricos

No hay backtest, ni rolling returns, ni drawdowns históricos. Todo sale de los
supuestos prospectivos del LTCMA.

### Yield informativo

Como el LTCMA no lo publica, está en cero y no afecta la proyección. El motor usa
el retorno total.

---

## 13. Validación contra la fuente

El motor se contrasta contra la lámina 9 del documento de referencia de
J.P. Morgan: USD 25,0MM iniciales, retiro de USD 1,1MM al año durante 29 años,
inflación 2,5%.

**Patrimonio neto en millones (simulado / publicado):**

| Año | p95 | p50 | p5 |
|---|---|---|---|
| 15 | 74 / 74 | 33 / 33 | 12 / 10 |
| 20 | 99 / 98 | 36 / 35 | 7 / 3 |
| 25 | 134 / 134 | 39 / 37 | −2 / −6 |
| 29 | 173 / 168 | 41 / 37 | −12 / −15 |

El total de retiros coincide exactamente (47,2MM). La probabilidad de éxito da
86,9% contra el 83,6% publicado.

**Las dos causas conocidas de la diferencia residual** son el mapeo de clases de
activo —J.P. Morgan usa su propia asignación subyacente, que no se publica en
detalle— y las comisiones de gestión, que no se modelan. La coincidencia en los
percentiles centrales y en el total de retiros indica que el motor parte de donde
debe.

El script de control es `tools/smoke_pdf_case.py`.

---

## Resumen en una página

- **Lognormales correlacionadas, paso anual**, 10.000 caminos por defecto.
- **Los supuestos vienen del LTCMA 2026** y no se editan desde la interfaz.
- **La correlación es lo que define el riesgo del portafolio**, porque el
  portafolio se agrega después del sorteo. Sin ella, la volatilidad y toda la
  cola izquierda saldrían subestimadas.
- **Todas las estrategias comparten los mismos sorteos**, así que las diferencias
  entre ellas son de la estrategia y no del azar.
- **Nada se supone sobre la forma de la distribución**: percentiles, probabilidad
  de éxito y CVaR salen de contar los caminos.
- **La probabilidad de éxito es estricta**: un camino falla si el patrimonio toca
  cero en cualquier año, no solo al final.
- **Pre-tax, sin comisiones, con correlaciones constantes.** Las colas extremas
  son algo optimistas por construcción.
