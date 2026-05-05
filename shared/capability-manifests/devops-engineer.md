# Capability Manifest: DevOps Engineer

Status: draft
Owner: coding namespace
Canonical specialist: `departments/coding/specialists/devops-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-devops-engineer/0.1.0/`

## Role Contract

DevOps Engineer owns reproducible infrastructure rails: CI/CD, Docker, Kubernetes when needed, Terraform, deployment runbooks, sandbox provisioning, rollback checks, workflow security linting, and local/cloud environment reproducibility. It does not author application logic, make product architecture decisions, or bypass operator approval for production-affecting changes.

## Preserved From Current Specialist

- CI/CD, Docker, deployment, cloud cost, and local service scope.
- Production hard gates.
- Secret redaction and rollback requirements.
- Security handoff for secrets/IAM/permission-sensitive changes.
- Skills: `terraform-state-hygiene`, `k8s-deploy-loop`, `cc-hooks-ci-discipline`, `sandbox-provision-discipline`, `secret-rotation-discipline`, `rollback-test-coverage`.

## Preserve From Old Plugin

### Required Tool Surface

- `docker_build_image`
- `docker_push`
- `kubectl_apply`
- `kubectl_get`
- `kubectl_logs`
- `terraform_init`
- `terraform_plan`
- `terraform_apply`
- `aws_s3_ls`
- `aws_ec2_describe`
- `helm_install`
- `k9s_namespace`
- `actionlint`
- `zizmor`

### Skills

- `bounty-sandbox-provision`
- `cc-hooks-ci-discipline`
- `cross-arch-cc-install`
- `k8s-deploy-loop`
- `terraform-state-hygiene`
- shared `secret-rotation-discipline`
- shared `rollback-test-coverage`
- shared `sandbox-provision-discipline`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> inspect environment/state -> apply relevant infra skill -> plan/provision -> verify -> record -> handoff
```

Required behavior:

- Use shell/IaC artifacts, not ClickOps.
- Run `terraform_plan` before any apply.
- Stop on destructive Terraform plans unless operator approves.
- Run `actionlint` and `zizmor` for GitHub Actions changes.
- Verify rollback path before production deploy.
- Verify network isolation for bounty sandboxes.
- Degrade gracefully when cloud credentials are absent.

## Output Contract

Return a structured report with:

- `ok`
- `provisioning_type`
- `environment`
- `commands_run`
- `network_isolated`
- `resources_created`
- `resources_modified`
- `terraform_plan_path`
- `rollback_verified`
- `kg_finding_id`
- `suggested_next_stage`
- missing-capability list when tools or credentials are unavailable

## KG And Memory Behavior

- Recall prior environment/sandbox state before provisioning.
- Record attempt before changes.
- Record confirmed infrastructure state, sandbox state, deploy results, or deferred credential blockers.

## Safety Boundaries

- No production deploy without operator approval.
- No DNS/domain changes without confirmation.
- No unmasked secrets in logs.
- No autoscaling/cost-impacting changes without budget awareness.
- No application source changes unless explicitly assigned and reviewed by implementation owner.

## Live Dispatch Proof

1. Chrono dispatches a local CI/Docker/sandbox fixture to coding namespace.
2. coding namespace selects `devops-engineer`.
3. Specialist runs `actionlint`, `docker`, `terraform plan`, or structured missing-tool output.
4. Response includes rollback/approval posture.
5. Active registry closes.
6. Chrono summarizes next stage.

## Public/Private Disposition

- Public: role contract, safe fixture workflows, output schema, no-prod-without-approval rule.
- Private/local: cloud credentials, registry auth, real infra state, bounty sandbox targets, CI secrets.

## Cleanup Disposition

Do not delete old devops plugin source until this manifest is complete, current specialist is updated, and a safe fixture dispatch proof passes.
