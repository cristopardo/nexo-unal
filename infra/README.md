# Google Cloud con Terraform

Este código prepara un despliegue reproducible; su presencia en GitHub **no significa que el servicio ya esté desplegado**.

## Recursos

- Cloud Run: una imagen por digest, HTTPS, escala de 0 a 2 instancias (máximo configurable), 1 CPU / 512 MiB, timeout de solicitud de 300 segundos.
- Firestore nativo: métricas agregables y registro de deduplicación; TTL en `expires_at` para las colecciones `metrics` y `deliveries`. La eliminación por TTL es asíncrona.
- Artifact Registry y Cloud Build, con cuenta de servicio propia para construir.
- Secret Manager: contenedores para credenciales. Los valores se cargan por entrada estándar; Terraform nunca los recibe.
- Cuenta de ejecución con acceso a Firestore, a los secretos utilizados y, opcionalmente, Vertex AI. Sin claves JSON de cuentas de servicio.
- Bucket privado para fuentes de construcción, con borrado tras siete días.

El servicio permite acceso público a la demostración y al webhook. `/api/metrics` exige `X-Admin-Token`; el webhook verifica la firma de Meta. No se debe poner un token administrativo en código de frontend. Los límites de instancias reducen la escala; no constituyen un límite de facturación.

## Requisitos

Terraform 1.10 o posterior, `gcloud`, Git y un proyecto de Google Cloud **dedicado**, con facturación y permisos para administrar los recursos anteriores. El código no crea una cuenta de facturación ni reutiliza automáticamente el proyecto configurado en `gcloud`.

El operador que ejecute Terraform necesita permisos para habilitar APIs, crear cuentas de servicio y configurar IAM, Cloud Run, Firestore, Artifact Registry, Secret Manager y Storage. Para construir necesita crear builds, subir objetos al bucket de fuentes y `iam.serviceAccounts.actAs` sobre la cuenta builder. Esas facultades pertenecen al operador, no al contenedor de la aplicación.

Si el proyecto ya tiene una base Firestore `(default)`, impórtala antes del primer `apply` y conserva su ubicación:

```bash
terraform -chdir=infra import \
  -var-file=terraform.tfvars \
  google_firestore_database.application \
  'projects/PROJECT_ID/databases/(default)'
```

## Crear un proyecto dedicado (opcional)

`infra/project/` mantiene un estado separado para la creación del proyecto y su enlace a una cuenta de facturación existente. El proyecto queda protegido contra borrado (`deletion_policy = "PREVENT"`) y no crea una red predeterminada. No crea ni modifica la cuenta de facturación.

```bash
cp infra/project/terraform.tfvars.example infra/project/terraform.tfvars
# Editar el project_id y el ID de la cuenta de facturación en ese archivo local ignorado.
terraform -chdir=infra/project init
terraform -chdir=infra/project plan -out=project.tfplan
terraform -chdir=infra/project apply project.tfplan
terraform -chdir=infra/project output -raw project_id
```

El ID de proyecto debe estar disponible globalmente. Si `nexo-unal-2026` ya está ocupado, elegir un sufijo antes del primer `apply`. El operador necesita permisos para crear proyectos y asociarlos a la cuenta de facturación. Especificar `organization_id` o `folder_id` solo si la cuenta y las políticas de organización lo requieren. Copiar el ID obtenido a `infra/terraform.tfvars` para desplegar el resto de recursos.

## Despliegue

1. Autenticar al operador y configurar Application Default Credentials:

   ```bash
   gcloud auth login
   gcloud auth application-default login
   cp infra/terraform.tfvars.example infra/terraform.tfvars
   ```

   Si `gcloud` ya está autenticado y ADC necesita renovación, se puede usar temporalmente un token del operador sin escribirlo en archivos:

   ```bash
   export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"
   # Ejecutar Terraform y los scripts durante la validez del token.
   # Al terminar:
   # unset GOOGLE_OAUTH_ACCESS_TOKEN
   ```

   El proveedor usa ADC cuando la variable no está presente. Renovar la variable si expira; no guardar el token en `.tfvars`, scripts, planes ni Git.

   Editar el archivo local y poner el `project_id` dedicado. Para la primera aplicación dejar `container_image` sin definir. Los archivos `.tfvars`, el estado y los planes no se publican.

2. Crear los recursos base y revisar el plan antes de aplicarlo:

   ```bash
   ./scripts/bootstrap.sh
   ```

3. Generar un token administrativo aleatorio de al menos 32 bytes, guardarlo en un gestor de contraseñas y cargarlo sin escribirlo como argumento ni en Terraform:

   ```bash
   ./scripts/set-secret.sh PROJECT_ID nexo-unal-admin-token
   ```

   El comando imprime el identificador de versión. Ajustar `admin_secret_version` en `infra/terraform.tfvars` si no es `1`.

4. Con el código probado y confirmado en Git, construir y desplegar:

   ```bash
   ./scripts/deploy.sh
   ```

   El script usa el proyecto del estado Terraform, construye con una cuenta de servicio propia, resuelve el digest, guarda su referencia en el archivo local ignorado `infra/deployment.auto.tfvars`, muestra el plan y aplica ese plan. Al terminar verifica `/healthz` y muestra la URL. Si se usa un archivo de variables alternativo, pasar su ruta **absoluta** como primer argumento a ambos scripts. La imagen no se cambia mediante `gcloud run deploy`; la configuración del servicio permanece en Terraform.

No se debe pasar una credencial mediante `-var` ni crear `google_secret_manager_secret_version`: el valor acabaría en el estado. Los planes y el estado también contienen metadatos del proyecto y deben almacenarse de forma privada. Para trabajo en equipo, migrar el estado a un bucket GCS privado con versionado y acceso mínimo antes de compartirlo; el backend local es suficiente para el primer despliegue individual.

## Activar WhatsApp

Crear una aplicación de Meta con WhatsApp Cloud API y registrar un número autorizado. Cargar por separado las tres credenciales:

```bash
./scripts/set-secret.sh PROJECT_ID nexo-unal-whatsapp-verify-token
./scripts/set-secret.sh PROJECT_ID nexo-unal-whatsapp-app-secret
./scripts/set-secret.sh PROJECT_ID nexo-unal-whatsapp-access-token
```

Configurar `enable_whatsapp = true`, `whatsapp_phone_number_id`, la versión de Graph API de la aplicación y las versiones numéricas de secretos en el archivo local de variables. Volver a desplegar. En Meta configurar `https://SERVICE_URL/webhooks/whatsapp` y el mismo verify token. No se activa un número ni se envían mensajes hasta disponer de estas credenciales.

## Activar Vertex AI

Configurar `enable_vertex_ai = true` y un `gemini_model` disponible en el proyecto; volver a desplegar. La app usa ADC de la cuenta de ejecución y el endpoint global (`VERTEX_LOCATION=global`), sin API key. El acceso a una licencia de Google AI Pro para uso personal y el consumo de Vertex AI son productos diferentes: la licencia no sustituye la facturación ni los permisos de la API.

## Operación

```bash
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
```

El webhook procesa los mensajes secuencialmente dentro de la solicitud en este piloto; el timeout permite generación y reintentos de envío. Para mayor volumen, migrar el procesamiento a una cola y un worker antes de aumentar la concurrencia.

La CI ejecuta estas validaciones y las pruebas de la aplicación sin credenciales cloud. No despliega automáticamente desde un repositorio público.

Cloud Run y Firestore tienen protección contra borrado. La base conserva sus datos al retirar el recurso de Terraform (`ABANDON`). Para retirar el entorno, revisar los recursos, quitar conscientemente las protecciones correspondientes y limpiar el bucket de fuentes antes de destruirlo. La infraestructura no crea reglas de alertas de facturación: el operador debe definirlas según su presupuesto en USD.

Referencias oficiales: [Cloud Run y secretos](https://docs.cloud.google.com/run/docs/configuring/services/secrets), [contenedores en Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/containers), [Cloud Build con cuenta propia](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts), [proveedor Google de Terraform](https://registry.terraform.io/providers/hashicorp/google/latest/docs).
