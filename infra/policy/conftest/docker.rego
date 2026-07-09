# Infra policy (docs/11 §3): applied by Conftest to Dockerfiles and compose files.
package main

import rego.v1

# ── Dockerfile rules (input is the parsed instruction array) ─────────────────

dockerfile_input if is_array(input)

deny contains msg if {
	dockerfile_input
	some instruction in input
	instruction.Cmd == "from"
	some value in instruction.Value
	endswith(value, ":latest")
	msg := sprintf("Dockerfile: base image %q must be pinned, not :latest", [value])
}

deny contains msg if {
	dockerfile_input
	not dockerfile_has_user
	msg := "Dockerfile: runtime must switch to a non-root USER"
}

dockerfile_has_user if {
	some instruction in input
	instruction.Cmd == "user"
}

# ── Compose rules (input is the parsed YAML document) ────────────────────────

deny contains msg if {
	some name, service in input.services
	service.privileged == true
	msg := sprintf("compose: service %q must not be privileged", [name])
}

deny contains msg if {
	some name, service in input.services
	endswith(service.image, ":latest")
	msg := sprintf("compose: service %q image must be pinned, not :latest", [name])
}

deny contains msg if {
	some name, service in input.services
	some port in service.ports
	is_string(port)
	not startswith(port, "127.0.0.1:")
	msg := sprintf("compose: service %q publishes %q — bind published ports to loopback", [name, port])
}
