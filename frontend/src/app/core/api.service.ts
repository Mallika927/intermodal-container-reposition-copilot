import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { CycleResult, DecisionAction, ImbalanceReport, PlannerDecision } from './models';

export interface DecisionRequestBody {
  action: DecisionAction;
  modified_units?: number | null;
  reason?: string | null;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  getImbalance(seed?: number): Observable<ImbalanceReport> {
    return this.http.get<ImbalanceReport>('/api/scoring/imbalance', {
      params: seed != null ? { seed } : {},
    });
  }

  runCycle(seed?: number): Observable<CycleResult> {
    return this.http.post<CycleResult>('/api/agent/run', null, {
      params: seed != null ? { seed } : {},
    });
  }

  getLatestCycle(): Observable<CycleResult> {
    return this.http.get<CycleResult>('/api/agent/cycles/latest');
  }

  submitDecision(recId: string, body: DecisionRequestBody): Observable<PlannerDecision> {
    return this.http.post<PlannerDecision>(`/api/recommendations/${recId}/decision`, body);
  }
}
