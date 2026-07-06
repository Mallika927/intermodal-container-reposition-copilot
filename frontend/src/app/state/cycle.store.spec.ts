import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { CycleResult, Recommendation } from '../core/models';
import { CycleStore } from './cycle.store';

function buildRecommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    id: 'REC-2026-0704-001',
    created_ts: '2026-07-04T23:00:00Z',
    lane_id: 'LAX-ICTF_DEN-RG',
    equipment_type: '53FT-DRY',
    units: 100,
    priority: 'HIGH',
    execution_legs: [],
    cost_usd: 24500,
    revenue_protected_usd: 185000,
    net_benefit_usd: 162900,
    reasoning_summary: 'Test recommendation.',
    risks: [],
    alternatives_considered: [],
    source_option_id: 'OPT-LAX-ICTF-DEN-RG-cover',
    status: 'pending',
    expires_at: '2026-07-05T11:00:00Z',
    ...overrides,
  };
}

function buildCycle(recommendations: Recommendation[]): CycleResult {
  return {
    cycle_id: 'CYCLE-test',
    started_ts: '2026-07-04T23:00:00Z',
    completed_ts: '2026-07-04T23:00:05Z',
    recommendations,
    no_action_rationale: null,
    trace: [],
    replay: false,
  };
}

describe('CycleStore', () => {
  let httpMock: HttpTestingController;
  let store: InstanceType<typeof CycleStore>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    store = TestBed.inject(CycleStore);
  });

  afterEach(() => {
    httpMock.verify();
  });

  /** Seeds store.cycle() through the store's own runCycle() + a mocked HTTP response. */
  function seedCycle(recommendation: Recommendation): void {
    store.runCycle(undefined);
    httpMock.expectOne((req) => req.url === '/api/agent/run').flush(buildCycle([recommendation]));
  }

  it('optimistically updates status and rolls back on HTTP error', () => {
    const recommendation = buildRecommendation();
    seedCycle(recommendation);

    store.decide(recommendation.id, 'approved');

    expect(store.cycle()?.recommendations[0].status).toBe('approved');
    expect(store.decisionInFlight()[recommendation.id]).toBe(true);

    const req = httpMock.expectOne(`/api/recommendations/${recommendation.id}/decision`);
    expect(req.request.method).toBe('POST');
    req.flush('server error', { status: 500, statusText: 'Internal Server Error' });

    expect(store.cycle()?.recommendations[0].status).toBe('pending');
    expect(store.decisionInFlight()[recommendation.id]).toBe(false);
    expect(store.error()).toBeTruthy();
  });

  it('keeps the optimistic status when the request succeeds', () => {
    const recommendation = buildRecommendation();
    seedCycle(recommendation);

    store.decide(recommendation.id, 'rejected', undefined, 'Not needed this cycle.');

    expect(store.cycle()?.recommendations[0].status).toBe('rejected');

    const req = httpMock.expectOne(`/api/recommendations/${recommendation.id}/decision`);
    req.flush({
      id: 'DEC-2026-0704-001',
      recommendation_id: recommendation.id,
      action: 'rejected',
      modified_units: null,
      reason: 'Not needed this cycle.',
      decided_ts: '2026-07-04T23:05:00Z',
    });

    expect(store.cycle()?.recommendations[0].status).toBe('rejected');
    expect(store.decisionInFlight()[recommendation.id]).toBe(false);
    expect(store.error()).toBeNull();
  });
});
