/** One hook for every page: the data model plus the running simulation (shared store) and the name helpers. */
import { useCallback, useEffect } from "react";
import { specialistApi, useSpecialistDecisions } from "../api/specialist";
import type { DecisionAction, PatientAction } from "./sim/simulation";
import { dispatchSim, useSimulation } from "./sim/useSimulation";
import { useTowerData, type TowerModel } from "./useTowerData";

/** Idempotency key of one decision: the same subject + action never creates a second row on replay. */
const decisionKey = (
  origin: string,
  kind: string,
  id: string,
  action: string,
) => `ui-${origin}-${kind}-${id}-${action}`.replace(/[^A-Za-z0-9._:-]/g, "_");

/** Store a decision on the server (fire and forget: the simulation already holds it). */
export function persistDecision(
  model: TowerModel,
  runId: string,
  kind: "alert" | "patient",
  id: string,
  action: DecisionAction | PatientAction,
  comment: string,
  simDay: number,
) {
  const alert = model.alerts.find((a) =>
    kind === "alert" ? a.id === id : false,
  );
  const patient =
    kind === "patient" ? model.patients.find((p) => p.id === id) : undefined;
  const org = alert?.org ?? patient?.org ?? null;
  void specialistApi
    .createDecision({
      origin: model.origin,
      run_id: runId,
      sim_day: simDay,
      subject_kind: kind,
      subject_id: id,
      region_code: alert?.region ?? patient?.region ?? null,
      org_code: org,
      profile_code: alert?.profile ?? patient?.profile ?? null,
      action,
      comment: comment || null,
      actor: null,
      idempotency_key: decisionKey(runId, kind, id, action),
    })
    .catch(() => undefined);
}

/** Replay the decisions of the current run stored on the server into the simulation (once per load / run). */
export function useHydrateDecisions(
  model: TowerModel | null,
  runId: string | null,
) {
  const stored = useSpecialistDecisions(model?.origin ?? null, runId);
  useEffect(() => {
    if (!stored.data) return;
    dispatchSim({
      type: "hydrate",
      decisions: stored.data.items.map((d) => ({
        subject_kind: d.subject_kind,
        subject_id: d.subject_id,
        sim_day: d.sim_day,
        action: d.action,
        comment: d.comment,
      })),
    });
  }, [stored.data]);
}

export function useNames(model: TowerModel | null) {
  const hospital = useCallback(
    (org: string) => model?.byOrg.get(org)?.name ?? org,
    [model],
  );
  const profile = useCallback(
    (code: string) => model?.profileName(code) ?? code,
    [model],
  );
  const region = useCallback(
    (code: string) => model?.regionName(code) ?? code,
    [model],
  );
  return { hospital, profile, region };
}

export function useTowerSimulation(model: TowerModel, speed = 1) {
  const regionName = useCallback(
    (code: string) => model.regionName(code),
    [model],
  );
  const sim = useSimulation(
    model.origin,
    model.alerts,
    model.patients,
    model.dailyBase,
    model.outageRegion,
    regionName,
    speed,
  );
  const runId = sim.state.runId;
  useHydrateDecisions(model, runId);
  const day = sim.state.day;
  const decide = useCallback(
    (alertId: string, action: DecisionAction, comment: string) => {
      sim.decide(alertId, action, comment);
      persistDecision(model, runId, "alert", alertId, action, comment, day);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [model, runId, day, sim.decide],
  );
  const decidePatient = useCallback(
    (patientId: string, action: PatientAction, comment: string) => {
      sim.decidePatient(patientId, action, comment);
      persistDecision(model, runId, "patient", patientId, action, comment, day);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [model, runId, day, sim.decidePatient],
  );
  return { ...sim, decide, decidePatient };
}

export { useTowerData };
