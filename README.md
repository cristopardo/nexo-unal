# Nexo UNAL

**El campus, a un mensaje.** Asistente virtual para consultar información de la Universidad Nacional de Colombia por WhatsApp, con un tablero de uso y fuentes institucionales citadas.

El piloto está pensado para Ciencias de la Computación de la Sede Bogotá. La meta es extender el catálogo a programas y sedes de toda la Universidad: trámites, matrícula, bienestar, bibliotecas y vida universitaria.

WhatsApp reduce la fricción de acceso por su adopción cotidiana. Algunos planes móviles incluyen su uso sin descontar datos; las condiciones dependen del operador, el plan y el tipo de contenido.

Iniciativa estudiantil independiente. Las respuestas orientan hacia fuentes de la Universidad y no reemplazan sus canales oficiales.

## Desarrollo inicial

- API de consultas con recuperación de un catálogo curado y enlaces de referencia.
- Integración de WhatsApp Cloud API con verificación de webhook y firma de Meta.
- Tablero de métricas agregadas, protegido por token de administración.
- Generación opcional con Gemini en Vertex AI; modo extractivo local sin credenciales.
- Infraestructura como código en Google Cloud con Terraform.

## Ejecutar localmente

Requiere Python 3.12 y [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
cp .env.example .env
uv run uvicorn app.main:app --reload --port 8080 --env-file .env --no-access-log
```

Abre <http://localhost:8080>. El chat funciona con las fuentes incluidas; el tablero requiere el valor de `ADMIN_TOKEN`. Las credenciales se configuran localmente y no se suben al repositorio.

```bash
uv run pytest
uv run ruff check .
```

## Google Cloud

Consulta [la guía de infraestructura](infra/README.md) para aprovisionar recursos, publicar la imagen y desplegar con Terraform. El despliegue requiere un proyecto Google Cloud con facturación habilitada y permisos suficientes. La licencia de Google AI Pro y el consumo de Vertex AI son productos distintos: la licencia no debe asumirse como crédito para las APIs.

La integración real de WhatsApp requiere una aplicación de Meta, un número habilitado y sus credenciales. Sin esa configuración se puede usar la interfaz web.

## Catálogo y privacidad

Consulta [las fuentes y su revisión](docs/sources.md). La versión inicial recupera entradas curadas; no indexa automáticamente todos los documentos de la Universidad. Cuando no encuentra evidencia, remite a los canales institucionales.

El tablero guarda conteos, categoría, canal y tiempos de respuesta. No guarda el texto de las preguntas ni números de teléfono. Consulta [arquitectura y operación](docs/architecture.md) para los límites del piloto y la ruta de ampliación.

Código bajo licencia [MIT](LICENSE).
