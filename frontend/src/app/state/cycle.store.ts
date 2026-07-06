import { computed, inject } from '@angular/core';
import { patchState, signalStore, withComputed, withMethods, withState } from '@ngrx/signals';
import { rxMethod } from '@ngrx/signals/rxjs-interop';
import { EMPTY, catchError, pipe, switchMap, tap } from 'rxjs';

import { ApiService } from '../core/api.service';
import { CycleResult, DecisionAction, ImbalanceReport, Priority, Recommendation } from '../core/models';

interface CycleState {
  cycle: CycleResult | null;
  imbalance: ImbalanceReport | null;
  loadingImbalance: boolean;
  loadingCycle: boolean;
  error: string | null;
  decisionInFlight: Record<string, boolean>;
}

const initialState: CycleState = {
  cycle: null,
  imbalance: null,
  loadingImbalance: false,
  loadingCycle: false,
  error: null,
  decisionInFlight: {},
};

const PRIORITY_RANK: Record<Priority, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };

export const CycleStore = signalStore(
  { providedIn: 'root' },
  withState(initialState),
  withComputed((store) => ({
    pendingRecommendations: computed(() =>
      (store.cycle()?.recommendations ?? []).filter((rec) => rec.status === 'pending')
    ),
    decidedCount: computed(
      () => (store.cycle()?.recommendations ?? []).filter((rec) => rec.status !== 'pending').length
    ),
    sortedByPriorityThenNet: computed(() => {
      const recommendations = store.cycle()?.recommendations ?? [];
      return [...recommendations].sort((a, b) => {
        const priorityDiff = PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
        return priorityDiff !== 0 ? priorityDiff : b.net_benefit_usd - a.net_benefit_usd;
      });
    }),
  })),
  withMethods((store, api = inject(ApiService)) => ({
    loadImbalance: rxMethod<number | undefined>(
      pipe(
        tap(() => patchState(store, { loadingImbalance: true, error: null })),
        switchMap((seed) =>
          api.getImbalance(seed).pipe(
            tap((imbalance) => patchState(store, { imbalance, loadingImbalance: false })),
            catchError(() => {
              patchState(store, {
                loadingImbalance: false,
                error: 'Failed to load the imbalance report.',
              });
              return EMPTY;
            })
          )
        )
      )
    ),
    runCycle: rxMethod<number | undefined>(
      pipe(
        tap(() => patchState(store, { loadingCycle: true, error: null })),
        switchMap((seed) =>
          api.runCycle(seed).pipe(
            tap((cycle) => patchState(store, { cycle, loadingCycle: false })),
            catchError(() => {
              patchState(store, {
                loadingCycle: false,
                error: 'Failed to run the analysis cycle.',
              });
              return EMPTY;
            })
          )
        )
      )
    ),
    decide(recId: string, action: DecisionAction, modifiedUnits?: number, reason?: string): void {
      const cycle = store.cycle();
      const target = cycle?.recommendations.find((rec) => rec.id === recId);
      if (!cycle || !target) {
        return;
      }
      const previousStatus = target.status;

      const withStatus = (recommendations: Recommendation[], status: Recommendation['status']) =>
        recommendations.map((rec) => (rec.id === recId ? { ...rec, status } : rec));

      patchState(store, (state) => ({
        decisionInFlight: { ...state.decisionInFlight, [recId]: true },
        cycle: state.cycle
          ? { ...state.cycle, recommendations: withStatus(state.cycle.recommendations, action) }
          : state.cycle,
      }));

      api.submitDecision(recId, { action, modified_units: modifiedUnits, reason }).subscribe({
        next: () => {
          patchState(store, (state) => ({
            decisionInFlight: { ...state.decisionInFlight, [recId]: false },
          }));
        },
        error: () => {
          patchState(store, (state) => ({
            decisionInFlight: { ...state.decisionInFlight, [recId]: false },
            cycle: state.cycle
              ? { ...state.cycle, recommendations: withStatus(state.cycle.recommendations, previousStatus) }
              : state.cycle,
            error: 'Failed to submit the decision. Please try again.',
          }));
        },
      });
    },
  }))
);
