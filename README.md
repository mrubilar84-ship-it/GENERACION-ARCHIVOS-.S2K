# Generación de modelos SAP2000 (.s2k) desde IFC

Lee vigas y columnas de un IFC (exportado desde Revit u otro software), construye el modelo estructural
y escribe un archivo de texto `.s2k` de SAP2000 junto con un reporte de revisiones.

## Uso

```bash
pip install -r requirements.txt
python -m s2k modelo.ifc -o salida/modelo.s2k --report salida/modelo.report.md
```

Opciones principales:

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--angle` | automático | Rotación de la grilla en grados (la automática usa la moda de las piezas horizontales). |
| `--offset X Y` | mínimo de la estructura | Origen en ejes rotados, en metros. |
| `--z0` | mínimo de la estructura | Cota mundo que pasa a Z = 0. |
| `--snap` | 0,01 m | Tolerancia para fusionar nudos. |
| `--snap-frame` | 0,02 m | Distancia para llevar un nudo al eje de otra barra. |
| `--join` | 0,15 m | Alcance para conectar un extremo libre (más la semialtura de la pieza receptora). |
| `--near` | 0,10 m | Distancia para avisar nudos cercanos sin fusionar. |
| `--grid-step` | 0,10 m | Paso para detectar la grilla en planta (solo informativa). `0` no la detecta. |
| `--apply-grid` | desactivado | Lleva los extremos de piezas primarias a la grilla. Por defecto la geometría queda como en el IFC. |
| `--z-step` | 0,05 m | Paso de los niveles Z. |
| `--grid-tol` | 0,10 m | Distancia máxima para ajustar un extremo a una línea de grilla (planta). |
| `--z-tol` | 0,10 m | Distancia máxima para ajustar un extremo a un nivel. |

El comando devuelve código 1 si hay errores de conectividad.

## Qué hace

1. **Lectura IFC** (`s2k/ifc/reader.py`): extremos del eje de cada viga (curva `Axis` del IFC) y perfil.
   Para columnas sin eje declarado usa la envolvente del sólido (aproximado, se reporta).
2. **Secciones** (`s2k/sections.py`):
   - Perfiles I desde el IFC, o ajustados desde el contorno cuando la familia es HN, IN o IE.
   - Ángulos L por geometría. Una XL se representa con una sola barra L80×80×5 (el reporte advierte que
     su peso es la mitad de la designación XL).
   - Resto como `General`.
   - Cada sección se compara con el peso de su designación (±1 %).
3. **Grilla** (`s2k/grid.py`): las líneas X, Y y niveles Z se detectan agrupando los extremos de las piezas
   primarias (HN, IN, IE; los arriostramientos no definen ejes) y se muestran en el reporte. Por defecto **no se
   aplican**: la geometría del `.s2k` es la del IFC, con sus cotas y pendientes reales. Con `--apply-grid` los
   extremos de piezas primarias se llevan a la línea regular (cada espaciamiento redondeado al paso), lo que
   puede aplanar pendientes, como ocurrió con la cubierta del pipe rack a 7,90 m.
4. **Nudos** (`s2k/model.py`):
   - Fusión de nudos a menos de la tolerancia.
   - Extremos libres llevados al eje de otra barra no paralela.
   - Nudos a 2 cm del eje de otra barra movidos sobre ese eje.
   - Barras divididas en nudos interiores (p. ej. viga que pasa por una columna).
   - Barras duplicadas eliminadas.
5. **Revisiones** (reporte): nudos desconectados, componentes separadas, barras que se cruzan sin nudo, nudos cercanos sin fusionar, barras duplicadas y de longitud cero, apoyos inválidos.
6. **Escritura** (`s2k/writer.py`): CRLF, tablas con el formato verificado en archivos exportados por SAP2000 v23.3.1.

## Resultado con el IFC de referencia (CMZ-5746)

- 94 miembros (80 vigas, 14 columnas): 80 con eje IFC, 14 columnas por envolvente.
- Grilla regular detectada:
  - X cada 3,00 m (0 a 18 m).
  - Y en 0,00 y 5,10 m (la distancia medida de 5,105 m se cierra a 5,10).
  - Niveles Z en 0,00; 5,60; 5,75 y 7,90 m.
  - Diferencias respecto de la medición: menos de 1 mm en X, hasta 25 mm en Y y hasta 18 mm en Z.
- 190 barras, 118 nudos y 5 secciones (HN30x92.2, HN25x42.4, L10x8.96, XL16x11.92, IN20x16.8).
- Pesos calculados contra designación: todos dentro de ±1 %.
- Revisiones:
  - 1 viga sin ningún elemento conectado (error).
  - 2 cruces de barras sin nudo común (advertencia).
  - 9 pares de nudos a 3–9 cm sin fusionar, en su mayoría excentricidades de unión (advertencia).

## Pruebas

```bash
python -m unittest discover -s tests -t .                       # pruebas unitarias
S2K_TEST_IFC=/ruta/archivo.ifc python -m unittest discover -s tests -t .   # incluye el IFC
```

## Limitaciones conocidas (no verificadas en SAP2000)

- **Columnas**: sin eje en el IFC de referencia; se usa la envolvente del sólido. El extremo puede quedar
  afectado por placas de base y de cabeza.
- **Ángulos L**: el espesor sale del área del contorno (5,87 mm frente a 6 mm nominal por redondeo de esquinas).
- **XL**: se usa una sola L, así que el peso y la rigidez son la mitad de la XL real (5,95 frente a 11,92 kg/m).
  Si necesitas la pareja completa, hay que decidir entre duplicar el área de la L o usar una sección
  de dos ángulos en SAP; eso no se ha implementado.
- **Secciones `General`**: propiedades aproximadas (torsión por pared delgada, ejes principales sin rotación
  respecto a los locales). Validar antes de usar en diseño.
- **Materiales**: todo se asigna a A36, aunque el IFC trae `Metal - Steel 43-275`.
- **Apoyos**: no se asignan; el reporte lista los nudos de cota mínima como candidatos.
- **Cargas**: no se generan todavía.
- **Coordenadas**: se rota la grilla por la moda de las vigas horizontales; conviene confirmar el origen y la rotación.
- **Grilla**: se deduce de la estructura, no de un plano. Confirma los espaciamientos contra las cotas del plano;
  el origen queda en la primera línea detectada (aquí Y = 0,02 m pasa a 0,00 m).
- **Niveles Z**: con paso de 5 cm, algunas cotas de piso se redondean a 2–2,5 cm de su medida. Usa `--z-step 0.01`
  si necesitas las cotas casi exactas.
