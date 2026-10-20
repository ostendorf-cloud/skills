---
name: talos-ops
description: Runs Talos Linux node operations one node at a time, with a stated upgrade or
  apply-config mode and a health and etcd quorum gate between nodes. Use when upgrading,
  rebooting or reconfiguring Talos nodes or the Kubernetes version. Trigger phrases: talosctl
  upgrade, apply-config, node reboot, etcd quorum, Talos Node aktualisieren, Node neu starten.
---

# Talos operations

Change nodes one at a time and never lose etcd quorum.

## When to use

- Upgrading Talos or Kubernetes on the cluster.
- Rebooting or reconfiguring a node.
- A node is unhealthy and needs intervention.

## Steps

1. Establish the baseline before touching anything:
   - cluster health and etcd member health.
   - node list with versions and roles.
   - pending pods, failing workloads, pod disruption budgets that would block a drain.
   - an etcd backup, verified to exist rather than assumed.
2. Read the upstream release notes for the target version. Note deprecations, required ordering
   and anything that cannot be rolled back.
3. Plan the order explicitly: workers first, control plane nodes last, one at a time, unless the
   release notes require a different order. State the plan and get confirmation before the first
   node.
4. Config changes go through the infrastructure code, never as an ad hoc `talosctl patch`. Diff
   the machine config before applying, prefer the least disruptive apply mode, and say whether a
   reboot is implied.
5. Per node:
   - verify quorum and health are green before starting.
   - run `talosctl upgrade` or `talosctl apply-config`, with `--mode` stated explicitly.
   - wait for the node to come back, rejoin, and report Ready, and for etcd to be healthy again.
   - check kubelet status and any pending CSR on the node.
   - verify workloads rescheduled and nothing is stuck.
   - only then continue to the next node.
6. Stop on the first anomaly. Do not continue a rolling operation on a degraded cluster, and do
   not parallelize nodes to save time.
7. Afterwards: report versions, cluster health, etcd health, and anything that needed manual
   intervention. State the rollback plan if the operation is not yet complete.

## Guardrails

- Never run `talosctl reset`.
- Never touch more than one node at a time.
- Never continue past an anomaly to finish faster.
- Never patch a node's config ad hoc, only through the infrastructure code.
- Never skip the etcd backup check before a control plane change.

## References

- `kubernetes-conventions` for what runs on top of the cluster.
- `opentofu-conventions` for how machine configuration is generated and applied.
