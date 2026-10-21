---
name: helm-chart
description: Creates or changes a Helm chart with a documented values interface, templates that
  render for every supported configuration, and lint, kubeconform and helm-unittest verification.
  Use when writing, changing or reviewing a Helm chart. Trigger phrases: write a chart,
  helm template, values.yaml, helm lint, helm-unittest, Helm Chart schreiben, Chart Werte,
  Chart Version.
---

# Helm chart

Write a chart that renders correctly for every documented combination of values.

## When to use

- A repository ships a chart for its own application.
- A chart is needed for a public tool that has none.
- An existing chart needs a change or a review.

## Steps

1. Define the values interface first: what is configurable, what is required, what the defaults
   are. Defaults must produce a working installation on a normal cluster.
2. Lay out the chart: `Chart.yaml`, `values.yaml`, `values.schema.json`, `templates/`,
   `README.md`, `tests/` for the helm-unittest suite.
3. Templates:
   - a `_helpers.tpl` with name, fullname, labels and selector labels, used everywhere.
   - the standard labels, including `app.kubernetes.io/version` and the chart version.
   - no namespace in a template, the release decides the namespace.
   - every object guarded by its feature flag, no orphaned object when a feature is off.
   - resources, probes, security context and service account configurable with safe defaults.
   - a checksum annotation on the pod template for a ConfigMap or Secret that must trigger a
     restart.
   - no CRD in `templates/`. CRDs are a separate concern, see `kubernetes-conventions`.
4. Keep `values.schema.json` in sync with `values.yaml` so a misconfiguration fails early.
5. Verify and report the real output:
   - `helm lint`.
   - `helm template` for the default values and for every documented non default combination.
   - `kubeconform` (or an equivalent schema check) on the rendered output.
   - `helm-unittest` suites in `tests/*_test.yaml`, one case per values combination, asserting what
     the rendered output says. Schema validity is `kubeconform`'s job, the decisions the chart
     encodes are not. Never render a chart in a throwaway script to grep the output.
   - `helm-unittest` is a Helm plugin, not a `mise` tool. Install it with
     `helm plugin install <url> --version <tag>`, pinned, with the version stated in the chart's
     own documentation so a machine and CI use the same one.
6. Document the chart `README.md`: purpose, prerequisites, the values table, upgrade notes, and
   the uninstall behaviour including what stays behind.
7. Version the chart with release-please. Chart version and application version are separate
   fields and both stay current.
8. Publish the chart as an OCI artifact from this repository's own release workflow, named and
   shaped per `ci-conventions`. Where no publish step exists yet, reference the chart inline or
   by path, and say so.

## Guardrails

- No CRD in a chart's templates.
- No namespace hardcoded in a template.
- No feature flag that leaves an orphaned object behind when turned off.
- Never claim `helm lint`, `helm template` or `helm-unittest` passed without having run them.

## References

- `kubernetes-conventions` for CRDs, namespaces and the workload baseline.
- `opentofu-conventions` for the `helm_release` that installs the chart.
