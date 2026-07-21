# Infra policy (docs/11 §3): applied by Conftest to the rendered Helm manifests
# (`helm template ... | conftest test -`). Enforces the restricted-workload
# invariants so a chart change can never quietly ship a privileged or root pod.
package main

import rego.v1

# ── Pod-bearing workloads: pull the pod spec + containers ────────────────────

workload_kinds := {"Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet"}

pod_spec := input.spec.template.spec if input.kind in workload_kinds

pod_spec := input.spec if input.kind == "Pod"

all_containers contains c if {
	some c in object.get(pod_spec, "containers", [])
}

all_containers contains c if {
	some c in object.get(pod_spec, "initContainers", [])
}

# ── Image pinning ────────────────────────────────────────────────────────────

deny contains msg if {
	some c in all_containers
	endswith(c.image, ":latest")
	msg := sprintf("%s/%s: image %q must be pinned, not :latest", [input.kind, c.name, c.image])
}

deny contains msg if {
	some c in all_containers
	not contains(c.image, ":")
	msg := sprintf("%s/%s: image %q must carry an explicit tag", [input.kind, c.name, c.image])
}

# ── Container security context ───────────────────────────────────────────────

deny contains msg if {
	some c in all_containers
	c.securityContext.allowPrivilegeEscalation != false
	msg := sprintf("%s/%s: allowPrivilegeEscalation must be false", [input.kind, c.name])
}

deny contains msg if {
	some c in all_containers
	c.securityContext.readOnlyRootFilesystem != true
	msg := sprintf("%s/%s: readOnlyRootFilesystem must be true", [input.kind, c.name])
}

deny contains msg if {
	some c in all_containers
	c.securityContext.privileged == true
	msg := sprintf("%s/%s: privileged containers are forbidden", [input.kind, c.name])
}

deny contains msg if {
	some c in all_containers
	not container_drops_all(c)
	msg := sprintf("%s/%s: must drop ALL capabilities", [input.kind, c.name])
}

container_drops_all(c) if {
	some cap in c.securityContext.capabilities.drop
	cap == "ALL"
}

# ── Pod-level: run as non-root ───────────────────────────────────────────────

deny contains msg if {
	pod_spec
	not pod_runs_non_root
	msg := sprintf("%s: pod or every container must set runAsNonRoot: true", [input.kind])
}

pod_runs_non_root if pod_spec.securityContext.runAsNonRoot == true

pod_runs_non_root if {
	some c in all_containers
	c.securityContext.runAsNonRoot == true
}

# ── Exec sandbox Jobs must be non-retrying and deadline-bounded ──────────────

deny contains msg if {
	input.kind == "Job"
	input.metadata.namespace == "spidey-exec"
	input.spec.backoffLimit != 0
	msg := "exec Job: backoffLimit must be 0 (hostile code runs at most once)"
}

deny contains msg if {
	input.kind == "Job"
	input.metadata.namespace == "spidey-exec"
	not input.spec.activeDeadlineSeconds
	msg := "exec Job: activeDeadlineSeconds must be set (hard wall-clock kill)"
}
