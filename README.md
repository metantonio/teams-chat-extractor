# Teams Chat Extractor & Analyzer (`team-reverse`)

Herramienta en Python para extraer, deserializar y organizar el historial de conversaciones y canales de **Microsoft Teams** (versión moderna basada en WebView2 / MSIX) directamente desde la base de datos y caché local en disco (**IndexedDB / LevelDB**), sin necesidad de permisos de administrador ni de credenciales en Azure / Microsoft Graph API.

---

## Características

- 🔍 **Extracción local directa**: Lee los archivos `.ldb` (SSTables) y `.log` (Write-Ahead Logs) de LevelDB de Teams con descompresión Snappy nativa.
- 🧩 **Decodificación de V8**: Parsea estructuras binarias serializadas por el motor V8 Structured Clone de Chromium.
- 🗂️ **Organización multidimensional**:
  - **Por Día**: Cronología organizada por jornada con fecha y hora exacta (UTC).
  - **Por Usuario**: Mensajes e intervenciones agrupados por cada participante.
  - **Por Pull Request**: Identifica y agrupa solicitudes y temas resueltos vinculados a PRs (`PR #xxx`, enlaces a GitHub, GitLab, etc.).
  - **Exportación en JSON**: Datos limpios y estructurados para consumo por otras herramientas o análisis posterior.
- 📋 **Descubrimiento de Hilos (`--list`)**: Permite inspeccionar todos los canales, grupos, reuniones y chats privados almacenados en la caché local junto con sus participantes detectados.
- ⚙️ **Configuración flexible**: Soporta parámetros por línea de comandos (`CLI`) y archivo de configuración `config.json`.

---

## Requisitos previos

- **Python 3.10+** (probado en Python 3.14)
- **Windows 10 / 11** con Microsoft Teams instalado
- Dependencia de descompresión Snappy:
  ```powershell
  pip install cramjam
  ```

---

## Instalación y Configuración

1. Clona o descarga este repositorio en tu equipo:
   ```powershell
   git clone <url-del-repo>
   cd team-reverse
   ```

2. Instala la dependencia requerida:
   ```powershell
   pip install cramjam
   ```

3. Copia el archivo de configuración de ejemplo:
   ```powershell
   copy config.json.example config.json
   ```

   El archivo `config.json` permite definir la conversación por defecto que deseas procesar:
   ```json
   {
     "default_topic": "Proyecto Cloud Infraestructura",
     "default_thread_id": "19:0123456789abcdef0123456789abcdef@thread.v2",
     "output_base_dir": "extracted_chat"
   }
   ```

---

## Uso

### 1. Listar todas las conversaciones en la caché local
Descubre todos los canales, grupos y chats privados almacenados en disco:
```powershell
python parse_teams_chat.py --list
```
*Salida de ejemplo:*
```text
================================================================================
                      CONVERSACIONES / GRUPOS EN LA CACHÉ                       
================================================================================
• Tópico       : Proyecto Cloud Infraestructura
  ID           : 19:0123456789abcdef0123456789abcdef@thread.v2
  Eventos      : 2802
--------------------------------------------------------------------------------
• Tópico       : DevOps Team
  ID           : 19:112233445566778899aabbccddeeff00@thread.v2
  Eventos      : 26
--------------------------------------------------------------------------------
• Tópico       : (Chat privado sin título)
  ID           : 19:abcdef0123456789abcdef0123456789@thread.v2
  Participantes: Juan Pérez, Carlos Gómez
  Eventos      : 23
```

---

### 2. Extraer la conversación por defecto
Ejecuta la extracción configurada en `config.json`:
```powershell
python parse_teams_chat.py
```

---

### 3. Extraer una conversación por nombre o palabra clave
Usa el argumento `--topic` con cualquier parte del título del grupo o reunión:
```powershell
python parse_teams_chat.py --topic "DevOps Team"
```
```powershell
python parse_teams_chat.py --topic "Cloud Infra"
```

---

### 4. Extraer un chat privado o hilo específico por ID
Usa el argumento `--id` con el Thread ID (`19:...@thread.v2`):
```powershell
python parse_teams_chat.py --id "19:abcdef0123456789abcdef0123456789@thread.v2"
```

---

### 5. Personalizar la carpeta de salida
```powershell
python parse_teams_chat.py --topic "DevOps Team" --output "mis_reportes"
```

---

## Estructura de los Archivos Generados

Cada extracción se almacena en su propia carpeta dentro de `extracted_chat/<Nombre_del_Tema>/`:

| Archivo | Descripción |
|---|---|
| `reporte_por_pull_request.md` | Mensajes organizados por cada Pull Request (`PR #xxx`), revisiones y temas clave. |
| `reporte_por_dia.md` | Cronología ordenada día a día con marcas de tiempo UTC y autor. |
| `reporte_por_usuario.md` | Historial de mensajes clasificado por cada miembro del equipo. |
| `chat_<Nombre>.json` | Archivo JSON con todos los objetos de mensaje (`id`, `timestamp`, `author`, `content`). |

---

## ¿Cómo obtener el Thread ID de un chat?

1. **Desde este script**: Ejecuta `python parse_teams_chat.py --list`.
2. **Desde Teams de escritorio**:
   - Haz clic en los **tres puntos (`...`)** del canal o chat.
   - Selecciona **"Copiar vínculo al canal/chat"**.
   - Pega el enlace: el fragmento entre `19%3A` y `%40thread.v2` corresponde al Thread ID (`19:...@thread.v2`).
3. **Desde Teams Web**:
   - En la barra de direcciones del navegador verás: `teams.microsoft.com/_#/conversations/19:...@thread.v2?ctx=chat`.

---

## Consejos para Actualizar y Sincronizar Mensajes

- **Mensajes nuevos**: Simplemente vuelve a ejecutar el comando y el script actualizará los reportes con los datos más recientes guardados por Teams.
- **Mensajes antiguos no descargados**: La base de datos local almacena lo que Teams ha cargado en caché. Si necesitas historial de meses anteriores que aún no figure en disco, abre Teams en ese canal/chat y haz scroll hacia arriba para forzar a la aplicación a descargarlos; a continuación, vuelve a ejecutar el script.
