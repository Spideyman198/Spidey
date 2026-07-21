{{/* Chart name, overridable. */}}
{{- define "spidey.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully-qualified release name. */}}
{{- define "spidey.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Common labels. */}}
{{- define "spidey.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "spidey.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: spidey
{{- end -}}

{{/* Selector labels for a component. Usage: include "spidey.selectorLabels" (dict "root" $ "component" "api"). */}}
{{- define "spidey.selectorLabels" -}}
app.kubernetes.io/name: {{ include "spidey.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* The app image reference (tag defaults to appVersion). */}}
{{- define "spidey.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{/* ServiceAccount name for app pods. */}}
{{- define "spidey.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "spidey.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* The Secret name app pods consume env from. */}}
{{- define "spidey.secretName" -}}
{{- printf "%s-secrets" (include "spidey.fullname" .) -}}
{{- end -}}

{{/* envFrom: non-secret ConfigMap + the secret. */}}
{{- define "spidey.envFrom" -}}
- configMapRef:
    name: {{ include "spidey.fullname" . }}-config
- secretRef:
    name: {{ include "spidey.secretName" . }}
{{- end -}}
